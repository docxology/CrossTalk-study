"""Source-only case admission through the independent native-text seam."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from crosstalk.case_files import parse_ledger, read_bytes
from crosstalk.case_geometry import check_pdf_geometry
from crosstalk.case_records import (
    AdmittedEvidence,
    CaseError,
    InputBinding,
    ValidatedCases,
    Version,
)
from crosstalk.index_observe import IndexReader
from crosstalk.models import Issue
from crosstalk.records import ExtractionSummary
from crosstalk.text_source import TextAdmissionFailure, admit_text_source

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crosstalk.case_records import Evidence
    from crosstalk.text_source import MeasurementInputs


def admit_page(evidence: Evidence, inputs: MeasurementInputs) -> AdmittedEvidence:
    """Check the reviewed content; a newer native artifact never impersonates the old one."""
    if evidence.source_pdf_sha256 != inputs.sha256 or evidence.page_index >= len(inputs.pages):
        raise CaseError("reviewed PDF or physical page is unavailable in the current source")
    page = inputs.pages[evidence.page_index]
    version = TypeAdapter(Version).validate_python(page.extractor_version)
    if (
        page.issue_id != evidence.issue_id
        or page.page_index != evidence.page_index
        or hashlib.sha256(page.text.encode()).hexdigest() != evidence.page_text_sha256
        or (page.width, page.height) != (evidence.width, evidence.height)
    ):
        raise CaseError("reviewed case physical-page identity, text or geometry changed")
    if (
        page.extractor_version == evidence.reviewed_extractor_version
        and inputs.page_artifact_sha256 == evidence.reviewed_native_artifact_sha256
    ):
        compatibility = "exact-reviewed-native-artifact"
    elif evidence.reviewed_extractor_version == "2" and page.extractor_version == "3":
        compatibility = "native-text-geometry-v2-to-v3"
    else:
        raise CaseError(
            "native artifact change is outside the explicit version-2-to-3 content rule"
        )
    return AdmittedEvidence(
        reviewed=evidence,
        current_native_artifact_sha256=inputs.page_artifact_sha256,
        current_extractor_version=version,
        compatibility=compatibility,
    )


def recheck_cases(root: Path, result: ValidatedCases) -> None:
    """Rehash the complete admitted case input set before a caller publishes its dossier."""
    if hashlib.sha256(read_bytes(Path(result.ledger_path))).hexdigest() != result.ledger_sha256:
        raise CaseError("case ledger changed after admission")
    reader = IndexReader(root)
    for binding in result.native_bindings:
        raw = read_bytes(reader.path(binding.path), 100_000_000)
        if hashlib.sha256(raw).hexdigest() != binding.sha256:
            raise CaseError("case source binding changed after native admission")
    reader.recheck()


def native_bindings(inputs_by_issue: Mapping[str, MeasurementInputs]) -> tuple[InputBinding, ...]:
    """Require a coherent complete source frame across the separately admitted issues."""
    bindings: dict[str, InputBinding] = {}
    for inputs in inputs_by_issue.values():
        for binding in inputs.bindings:
            item = InputBinding(path=binding.path, sha256=binding.sha256)
            if item.path in bindings and bindings[item.path] != item:
                raise CaseError("case pages were admitted under conflicting current source frames")
            bindings[item.path] = item
    expected = {"data/manifest/issues.jsonl", "output/reports/extraction.jsonl"}
    for issue_id in inputs_by_issue:
        expected.update((f"data/raw/pdf/{issue_id}.pdf", f"data/processed/pages/{issue_id}.jsonl"))
    if set(bindings) != expected:
        raise CaseError("native source admission did not return the complete expected binding set")
    return tuple(bindings[name] for name in sorted(bindings))


def validate_case_ledger(root: Path, ledger_path: Path) -> ValidatedCases:
    """Admit all curated pages together; callers compose any project lock without nesting."""
    raw = read_bytes(ledger_path)
    ledger = parse_ledger(raw)
    reader = IndexReader(root)
    manifest = tuple(
        Issue.model_validate_json(line)
        for line in reader.read("data/manifest/issues.jsonl").splitlines()
        if line.strip()
    )
    extraction = ExtractionSummary.model_validate_json(
        reader.read("output/reports/extraction.jsonl")
    )
    issues = {row.issue_id: row for row in manifest}
    outcomes = {row.issue_id: row for row in extraction.issues}
    if len(issues) != len(manifest) or len(outcomes) != len(extraction.issues):
        raise CaseError("case sources need unique current manifest and extraction issue identities")
    inputs_by_issue: dict[str, MeasurementInputs] = {}
    for evidence in ledger.evidence:
        issue = issues.get(evidence.issue_id)
        outcome = outcomes.get(evidence.issue_id)
        if (
            issue is None
            or outcome is None
            or issue.landing_url != evidence.source_url
            or issue.title != evidence.catalog_title
        ):
            raise CaseError("case issue, source URL or catalog title differs from current manifest")
        if evidence.issue_id not in inputs_by_issue:
            admitted = admit_text_source(root, outcome, issue)
            if isinstance(admitted, TextAdmissionFailure):
                raise CaseError(
                    f"case native source refused at {admitted.stage}: {admitted.reason}"
                )
            inputs_by_issue[evidence.issue_id] = admitted
    admitted_evidence = tuple(
        admit_page(row, inputs_by_issue[row.issue_id]) for row in ledger.evidence
    )
    for issue_id, inputs in inputs_by_issue.items():
        selected = {
            row.page_index: (row.width, row.height)
            for row in ledger.evidence
            if row.issue_id == issue_id
        }
        check_pdf_geometry(root, issue_id, inputs.sha256, selected)
    result = ValidatedCases(
        ledger=ledger,
        ledger_path=str(ledger_path),
        ledger_sha256=hashlib.sha256(raw).hexdigest(),
        native_bindings=native_bindings(inputs_by_issue),
        evidence=admitted_evidence,
    )
    reader.recheck()
    recheck_cases(root, result)
    return result
