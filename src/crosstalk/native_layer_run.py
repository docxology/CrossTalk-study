"""A separately bounded NPS native phase produces reusable sealed layer observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from crosstalk.acquisition_lock import project_lock
from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError, Issue
from crosstalk.native_layer_html import render_native_layers
from crosstalk.native_layer_records import (
    NativeIssueObservation,
    NativeLayerFailure,
    NativeLayerRun,
    NativeRunSettings,
)
from crosstalk.native_layer_store import (
    implementation_digest,
    locator_membership,
    publish_issue,
    publish_run,
)
from crosstalk.native_layer_variants import variants
from crosstalk.native_layers.source import NativeRequest, current_native_layers_locked
from crosstalk.records import ExtractionSummary

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.native_layers.records import IssueLayers
    from crosstalk.records import IssueExtraction


def analyze_native_layers(root: Path, settings: NativeRunSettings | None = None) -> NativeLayerRun:
    """Run this phase independently; no raster decoder or OCR derivative determines admission."""
    with project_lock(root):
        return _analyze_native_layers(root, settings or NativeRunSettings(), IndexReader(root))


@dataclass(frozen=True, slots=True)
class NativeSelection:
    """Exactly selected, deferred and outside-frame extraction members."""

    inventory: int
    selected: tuple[IssueExtraction, ...]
    deferred: tuple[str, ...]
    outside: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeMeasurements:
    """Current source-distinct observations and explicit source-stage refusals."""

    evidence: tuple[NativeIssueObservation, ...]
    issues: tuple[IssueLayers, ...]
    failures: tuple[NativeLayerFailure, ...]
    duplicates: tuple[str, ...]


def _selection(reader: IndexReader, config: NativeRunSettings) -> NativeSelection:
    extraction = ExtractionSummary.model_validate_json(
        reader.read("output/reports/extraction.jsonl").strip()
    )
    inventory = tuple(
        Issue.model_validate_json(line)
        for line in reader.read("data/manifest/issues.jsonl").splitlines()
        if line.strip()
    )
    _ = reader.read("data/manifest/catalog.jsonl")
    identifiers = tuple(row.issue_id for row in extraction.issues)
    membership = {row.issue_id for row in inventory}
    if (
        max(len(inventory), len(identifiers)) > 10_000
        or len(membership) != len(inventory)
        or len(set(identifiers)) != len(identifiers)
    ):
        raise AcquisitionError(
            "native layer phase requires bounded unique manifest/extraction identities"
        )
    candidates = tuple(row for row in extraction.issues if row.issue_id in membership)
    selected = candidates[config.offset : config.offset + config.max_issues]
    selected_ids = {row.issue_id for row in selected}
    return NativeSelection(
        len(extraction.issues),
        selected,
        tuple(row.issue_id for row in candidates if row.issue_id not in selected_ids),
        tuple(row.issue_id for row in extraction.issues if row.issue_id not in membership),
    )


def _measure(
    root: Path,
    selected: tuple[IssueExtraction, ...],
    config: NativeRunSettings,
    reader: IndexReader,
) -> NativeMeasurements:
    evidence: list[NativeIssueObservation] = []
    accepted: list[IssueLayers] = []
    failures: list[NativeLayerFailure] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for outcome in selected:
        try:
            current = current_native_layers_locked(
                root,
                NativeRequest(issue_id=outcome.issue_id, source_kind=config.source_kind),
                reader,
            )
        except (OSError, ValueError) as error:
            failures.append(NativeLayerFailure(issue_id=outcome.issue_id, reason=str(error)))
            continue
        digest = current.layers.identity.pdf_sha256
        if digest in seen:
            duplicates.append(outcome.issue_id)
            continue
        evidence.append(publish_issue(root, current))
        accepted.append(current.layers)
        seen.add(digest)
    return NativeMeasurements(tuple(evidence), tuple(accepted), tuple(failures), tuple(duplicates))


def _analyze_native_layers(
    root: Path, config: NativeRunSettings, reader: IndexReader
) -> NativeLayerRun:
    implementation = implementation_digest()
    scope = _selection(reader, config)
    ledger = locator_membership(reader)
    measured = _measure(root, scope.selected, config, reader)
    result = NativeLayerRun(
        observed_at=datetime.now(UTC).isoformat(),
        implementation_sha256=implementation,
        producer=reader.producer,
        settings=config,
        inventory_issue_units=scope.inventory,
        selected_issue_ids=tuple(row.issue_id for row in scope.selected),
        deferred_issue_ids=scope.deferred,
        outside_nps_manifest_issue_ids=scope.outside,
        duplicate_issue_ids=measured.duplicates,
        issues=measured.evidence,
        unavailable=measured.failures,
        variants=variants(measured.issues, config),
        input_bindings=reader.source_bindings(),
        locator_ledger_paths=ledger,
    )
    if locator_membership(reader) != ledger or implementation_digest() != implementation:
        raise AcquisitionError("native-layer ledger or implementation changed during the phase")
    reader.recheck()
    _ = publish_run(root, result, render_native_layers(result))
    return result
