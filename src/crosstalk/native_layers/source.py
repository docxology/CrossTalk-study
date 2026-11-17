"""Current native-only admission rechecks independent extraction seals without decoding rasters."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal, assert_never

from pydantic import Field

from crosstalk.acquisition_lock import project_lock
from crosstalk.index_identity import valid_manifest_binding
from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError
from crosstalk.native_layers.handle_source import retained_handle
from crosstalk.native_layers.layers import measure_layers
from crosstalk.native_layers.records import (
    IssueLayers,
    LayerRecord,
    LayerSettings,
    NativeIdentity,
    NativePage,
)
from crosstalk.records import ExtractionSummary
from crosstalk.signposting_store import read_catalog, read_manifest
from crosstalk.text_source import MeasurementInputs, TextAdmissionFailure, admit_text_source

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.models import Issue
    from crosstalk.records import IssueExtraction


class NativeRequest(LayerRecord):
    """Software controls and journal observations keep distinct caller-declared source kinds."""

    issue_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    source_kind: Literal["journal", "software-fixture"]
    settings: LayerSettings = Field(default_factory=LayerSettings)


class CurrentBinding(LayerRecord):
    """Exact file identity used by the native proposal, without visual eligibility claims."""

    path: str
    sha256: str


class CurrentLayers(LayerRecord):
    """A current guarded derivative and its explicit native-only source boundary."""

    layers: IssueLayers
    bindings: tuple[CurrentBinding, ...]
    source_unchanged: Literal[True]
    raster_reference_integrity: Literal["not-evaluated-native-only"] = "not-evaluated-native-only"


def current_native_layers(root: Path, request: NativeRequest) -> CurrentLayers:
    """Hold actual project admission while checking seals, measuring and rechecking inputs."""
    with project_lock(root):
        reader = IndexReader(root)
        result = current_native_layers_locked(root, request, reader)
        reader.recheck()
        return result


def _admitted_native(
    root: Path, outcome: IssueExtraction, issue: Issue | None, reader: IndexReader
) -> MeasurementInputs:
    """Turn typed native refusals into this source reader's explicit exception boundary."""
    admitted = admit_text_source(root, outcome, issue, reader=reader)
    match admitted:
        case TextAdmissionFailure():
            raise AcquisitionError(f"{admitted.stage}: {admitted.reason}")
        case MeasurementInputs():
            return admitted
        case _:
            assert_never(admitted)


def current_native_layers_locked(
    root: Path, request: NativeRequest, reader: IndexReader
) -> CurrentLayers:
    """Compose beneath actual project_lock; the enclosing pass owns its final reader.recheck()."""
    catalog = read_catalog(root)
    candidates = tuple(row for row in catalog.rows if row.issue_id == request.issue_id)
    if len(candidates) != 1:
        raise AcquisitionError("native source needs exactly one current catalog identity")
    row = candidates[0]
    manifest = read_manifest(root)
    issue = next((entry for entry in manifest.rows if entry.issue_id == request.issue_id), None)
    if not valid_manifest_binding(row, issue):
        raise AcquisitionError("native source manifest does not bind the current catalog identity")
    extraction_path = "output/reports/extraction.jsonl"
    extraction_raw = reader.read(extraction_path)
    summary = ExtractionSummary.model_validate_json(extraction_raw.strip())
    outcomes = tuple(outcome for outcome in summary.issues if outcome.issue_id == row.issue_id)
    if len(outcomes) != 1:
        raise AcquisitionError("native source needs one independent extraction outcome")
    outcome = outcomes[0]
    match outcome.status:
        case "complete" | "partial":
            status = outcome.status
        case "failed":
            raise AcquisitionError("failed extraction cannot authorize a native layer")
        case _:
            assert_never(outcome.status)
    native = _admitted_native(root, outcome, issue, reader)
    pdf_path = f"data/raw/pdf/{row.issue_id}.pdf"
    page_path = f"data/processed/pages/{row.issue_id}.jsonl"
    raw, count = native.raw_pages, native.total_pdf_pages
    pages = tuple(
        NativePage(page=page, record_line_sha256=hashlib.sha256(line).hexdigest())
        for page, line in zip(native.pages, raw.splitlines(keepends=True), strict=True)
    )
    handle = retained_handle(root, row, catalog.sha256)
    identity = NativeIdentity(
        issue_id=row.issue_id,
        title=row.title,
        issued=row.issued_metadata,
        landing_url=row.landing_url,
        catalog_sha256=catalog.sha256,
        pdf_sha256=native.sha256,
        page_artifact_sha256=native.page_artifact_sha256,
        total_pdf_pages=count,
        extraction_status=status,
        source_kind=request.source_kind,
        handle_evidence=handle,
    )
    expected = {
        pdf_path: native.sha256,
        page_path: native.page_artifact_sha256,
        extraction_path: hashlib.sha256(extraction_raw).hexdigest(),
        "data/manifest/catalog.jsonl": catalog.sha256,
        "data/manifest/issues.jsonl": hashlib.sha256(manifest.raw or b"").hexdigest(),
    }
    if handle is not None:
        expected.update(
            {
                handle.snapshot_path: handle.snapshot_sha256,
                f"data/raw/metadata/signposting/{handle.body_sha256}.json": handle.body_sha256,
                f"data/raw/metadata/robots/{handle.robots_sha256}.json": handle.robots_sha256,
            }
        )
    relative = tuple(sorted(expected))
    before = tuple(
        CurrentBinding(path=path, sha256=reader.digest(path).sha256) for path in relative
    )
    if any(binding.sha256 != expected[binding.path] for binding in before):
        raise AcquisitionError("native inputs changed after their independently sealed admission")
    result = measure_layers(identity, pages, request.settings)
    after = tuple(CurrentBinding(path=path, sha256=reader.digest(path).sha256) for path in relative)
    if before != after or read_catalog(root).sha256 != catalog.sha256:
        raise AcquisitionError("native source inputs changed during the derivative measurement")
    return CurrentLayers(layers=result, bindings=before, source_unchanged=True)
