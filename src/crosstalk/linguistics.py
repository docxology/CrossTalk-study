"""Source-bound orchestration for deterministic linguistic diagnostics."""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, assert_never

from crosstalk.acquisition_lock import project_lock
from crosstalk.extraction_method import EXTRACTION_IMPLEMENTATION_FILES
from crosstalk.index_observe import IndexReader
from crosstalk.linguistic_metrics import measure_pages
from crosstalk.linguistic_records import (
    IssueLinguistics,
    LinguisticFailure,
    LinguisticRun,
    LinguisticSettings,
)
from crosstalk.linguistic_report import write_linguistic_report
from crosstalk.models import AcquisitionError, file_digest, load_manifest, safe_directory
from crosstalk.records import (
    EXTRACTOR_VERSION,
    ExtractionSummary,
    write_records,
)
from crosstalk.text_source import MeasurementInputs, TextAdmissionFailure, admit_text_source

if TYPE_CHECKING:
    from crosstalk.models import Issue
    from crosstalk.records import IssueExtraction, PageRecord

IMPLEMENTATION_FILES: Final = (
    "linguistics.py",
    "linguistic_metrics.py",
    "linguistic_records.py",
    "linguistic_report.py",
    "lexicon.py",
    "records.py",
    "models.py",
    "text_source.py",
    "index_observe.py",
    "index_records.py",
    *EXTRACTION_IMPLEMENTATION_FILES,
)


@dataclass(frozen=True, slots=True)
class DiagnosticSource:
    """One verified PDF/cache pairing and its optional inventory identity."""

    issue_id: str
    title: str
    source_url: str | None
    pdf_sha256: str
    artifact_sha256: str
    extraction_status: Literal["complete", "partial"]
    total_pdf_pages: int | None
    pages: tuple[PageRecord, ...]


def _source(
    root: Path, outcome: IssueExtraction, issue: Issue | None, *, reader: IndexReader | None = None
) -> DiagnosticSource:
    """Reuse current native custody without invoking any pixel decoder."""
    admitted = admit_text_source(root, outcome, issue, reader=reader)
    match admitted:
        case TextAdmissionFailure():
            raise AcquisitionError(f"{admitted.stage}: {admitted.reason}")
        case MeasurementInputs():
            pass
        case _:
            assert_never(admitted)
    match outcome.status:
        case "complete" | "partial":
            status = outcome.status
        case "failed":
            raise AcquisitionError("failed extraction cannot authorize a native diagnostic")
        case _:
            assert_never(outcome.status)
    return DiagnosticSource(
        issue_id=outcome.issue_id,
        title=issue.title if issue else outcome.issue_id,
        source_url=issue.landing_url if issue else None,
        pdf_sha256=admitted.sha256,
        artifact_sha256=admitted.page_artifact_sha256,
        extraction_status=status,
        total_pdf_pages=admitted.total_pdf_pages,
        pages=admitted.pages,
    )


def analyze_linguistics(root: Path, settings: LinguisticSettings | None = None) -> LinguisticRun:
    """Write native-only diagnostics under the same actual project operation lock."""
    with project_lock(root):
        return analyze_linguistics_locked(root, settings or LinguisticSettings(), IndexReader(root))


def analyze_linguistics_locked(
    root: Path, config: LinguisticSettings, reader: IndexReader
) -> LinguisticRun:
    """Compose beneath an actual outer project_lock; current producer is shared per pass."""
    for directory in ("data/raw/pdf", "data/processed/pages", "data/manifest", "output/reports"):
        _ = safe_directory(root, directory)
    raw = reader.read("output/reports/extraction.jsonl")
    extraction = ExtractionSummary.model_validate_json(raw.strip())
    identifiers = tuple(outcome.issue_id for outcome in extraction.issues)
    if len(set(identifiers)) != len(identifiers):
        message = "duplicate issue identifiers in extraction receipt"
        raise ValueError(message)
    manifest_path = root / "data/manifest/issues.jsonl"
    if manifest_path.is_symlink():
        message = "issue inventory path is a symlink"
        raise ValueError(message)
    manifest_digest = file_digest(manifest_path) if manifest_path.exists() else None
    metadata = (
        {issue.issue_id: issue for issue in load_manifest(manifest_path)}
        if manifest_path.exists()
        else {}
    )
    if manifest_path.exists() and file_digest(manifest_path) != manifest_digest:
        message = "inventory changed while diagnostics parsed it"
        raise ValueError(message)
    selected = extraction.issues[: config.max_issues]
    issues: list[IssueLinguistics] = []
    unavailable: list[LinguisticFailure] = []
    duplicates: list[str] = []
    observed_hashes: set[str] = set()
    for outcome in selected:
        try:
            source = _source(root, outcome, metadata.get(outcome.issue_id), reader=reader)
            if source.pdf_sha256 in observed_hashes:
                duplicates.append(source.issue_id)
                continue
            measures = measure_pages(source.pages, config)
        except (OSError, ValueError) as error:
            unavailable.append(LinguisticFailure(issue_id=outcome.issue_id, reason=str(error)))
            continue
        observed_hashes.add(source.pdf_sha256)
        issues.append(
            IssueLinguistics(
                issue_id=source.issue_id,
                title=source.title,
                source_url=source.source_url,
                source_sha256=source.pdf_sha256,
                page_artifact_sha256=source.artifact_sha256,
                extraction_status=source.extraction_status,
                total_pdf_pages=source.total_pdf_pages,
                measures=measures,
            )
        )
    code = hashlib.sha256()
    for filename in IMPLEMENTATION_FILES:
        code.update(filename.encode())
        code.update(Path(__file__).with_name(filename).read_bytes())
    lock = root / "uv.lock"
    run = LinguisticRun(
        observed_at=datetime.now(UTC).isoformat(),
        implementation_sha256=code.hexdigest(),
        extraction_receipt_sha256=hashlib.sha256(raw).hexdigest(),
        extractor_version=EXTRACTOR_VERSION,
        manifest_sha256=manifest_digest,
        environment_lock_sha256=file_digest(lock) if lock.exists() else None,
        python_version=platform.python_version(),
        settings=config,
        inventory_issues=len(extraction.issues),
        selected_issues=len(selected),
        issues=tuple(issues),
        duplicate_issue_ids=tuple(duplicates),
        unavailable=tuple(unavailable),
    )
    reader.recheck()
    write_records(root / "output/reports/linguistics.jsonl", (run,))
    write_linguistic_report(root, run)
    return run
