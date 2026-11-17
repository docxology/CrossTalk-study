"""Measure saved raster peers independently after native-only source admission."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from crosstalk.analysis_records import VisualMetrics
from crosstalk.image_decode import RasterDecodeError
from crosstalk.visual_asset import measure_recorded_asset
from crosstalk.visual_records import (
    PageVisualCoverage,
    VisualAssetFailure,
    VisualObservation,
    visual_scope_status,
)

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.records import ImageOccurrence, PageRecord


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    """One recorded digest with all physical occurrences, including metadata conflicts."""

    sha256: str | None
    occurrences: tuple[tuple[PageRecord, ImageOccurrence], ...]


@dataclass(frozen=True, slots=True)
class VisualMeasurement:
    """Accepted peer pixels and their independent typed scope/missingness observation."""

    images: tuple[VisualMetrics, ...]
    coverage: VisualObservation


def _assets(pages: tuple[PageRecord, ...]) -> tuple[AssetCandidate, ...]:
    """Deduplicate measured bytes without discarding an incompatible repeated observation."""
    grouped: dict[str, list[tuple[PageRecord, ImageOccurrence]]] = defaultdict(list)
    for page in pages:
        for image in page.images:
            if image.path is not None:
                grouped[image.sha256 or image.path].append((page, image))
    return tuple(
        AssetCandidate(rows[0][1].sha256, tuple(rows)) for _, rows in sorted(grouped.items())
    )


def _measure_asset(
    root: Path, issue_id: str, candidate: AssetCandidate
) -> VisualMetrics | VisualAssetFailure:
    """Codec failures remain local; preview/publication failures propagate as operational errors."""
    _, first = candidate.occurrences[0]
    descriptions = {
        (image.path, image.sha256, image.width, image.height) for _, image in candidate.occurrences
    }
    if candidate.sha256 is None or len(descriptions) != 1:
        return VisualAssetFailure(
            issue_id=issue_id,
            sha256=candidate.sha256,
            path=first.path,
            stage="asset-metadata",
            reason="saved asset digest or repeated metadata is unavailable or conflicting",
        )
    try:
        measured = measure_recorded_asset(root, candidate.occurrences)
    except RasterDecodeError as error:
        return VisualAssetFailure(
            issue_id=issue_id,
            sha256=candidate.sha256,
            path=error.path,
            stage=error.stage,
            reason=error.reason,
            error_type=error.error_type,
            initial_error=error.initial_error,
        )
    return measured


def _page_coverage(page: PageRecord, measured: set[str]) -> PageVisualCoverage:
    """Retain known attributed entry counts even when reference classification is unavailable."""
    inventory = page.image_inventory
    return PageVisualCoverage(
        page_index=page.page_index,
        reference_inventory_status=inventory.status
        if inventory is not None
        else "legacy-unobserved",
        native_inventory_entries=inventory.occurrence_count if inventory is not None else None,
        native_inventory_entry_basis=(
            inventory.occurrence_count_basis if inventory is not None else None
        ),
        reference_status_counts=inventory.reference_status_counts if inventory is not None else (),
        inventory_reason=inventory.reason if inventory is not None else "legacy inventory absent",
        recorded_saved_occurrences=sum(image.path is not None for image in page.images),
        recorded_unsaved_occurrences=sum(image.path is None for image in page.images),
        measured_occurrences=sum(image.sha256 in measured for image in page.images),
    )


def measure_visuals(root: Path, issue_id: str, pages: tuple[PageRecord, ...]) -> VisualMeasurement:
    """Preserve native eligibility and every independently measured saved raster peer."""
    candidates = _assets(pages)
    images: list[VisualMetrics] = []
    failures: list[VisualAssetFailure] = []
    for candidate in candidates:
        observation = _measure_asset(root, issue_id, candidate)
        match observation:
            case VisualAssetFailure():
                failures.append(observation)
            case VisualMetrics():
                images.append(observation)
            case _:
                assert_never(observation)
    measured = {image.sha256 for image in images}
    coverage = tuple(_page_coverage(page, measured) for page in pages)
    unknown = sum(page.native_inventory_entries is None for page in coverage)
    known_sum = sum(page.native_inventory_entries or 0 for page in coverage)
    observation = VisualObservation(
        status=visual_scope_status(coverage, len(candidates), len(images)),
        pages=coverage,
        measured_asset_sha256s=tuple(image.sha256 for image in images),
        failures=tuple(failures),
        saved_asset_candidates=len(candidates),
        measured_assets=len(images),
        native_inventory_entries=known_sum if not unknown else None,
        known_native_inventory_entry_sum=known_sum,
        unknown_native_inventory_pages=unknown,
        unavailable_reference_pages=sum(
            page.reference_inventory_status != "enumerated" for page in coverage
        ),
    )
    return VisualMeasurement(tuple(images), observation)
