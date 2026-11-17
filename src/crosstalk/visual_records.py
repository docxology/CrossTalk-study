"""Independent visual coverage, without changing native text eligibility."""

from __future__ import annotations

from typing import Literal, assert_never

from pydantic import Field, model_validator

from crosstalk.image_inventory import ReferenceStatusCount  # noqa: TC001 -- Pydantic field.
from crosstalk.image_reference_records import Record

type VisualStatus = Literal[
    "complete-declared-raster-scope", "partial", "unavailable", "empty-declared-raster-scope"
]


class VisualAssetFailure(Record):
    """An unavailable asset is an observation, never a fabricated zero or native refusal."""

    issue_id: str
    sha256: str | None
    path: str | None
    stage: Literal["asset-metadata", "image-integrity", "image-pillow", "image-native"]
    reason: str
    error_type: str | None = None
    initial_error: str | None = None


class PageVisualCoverage(Record):
    """Native entry observations and reference coverage have separate missingness."""

    page_index: int = Field(ge=0)
    reference_inventory_status: Literal["enumerated", "unavailable", "legacy-unobserved"]
    native_inventory_entries: int | None = Field(default=None, ge=0)
    native_inventory_entry_basis: Literal["native-occurrence-inventory"] | None = None
    reference_status_counts: tuple[ReferenceStatusCount, ...] = ()
    inventory_reason: str | None = None
    recorded_saved_occurrences: int = Field(ge=0)
    recorded_unsaved_occurrences: int = Field(ge=0)
    measured_occurrences: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent_counts(self) -> PageVisualCoverage:
        """Known zero requires an actual attributed native inventory observation."""
        if (self.native_inventory_entries is None) != (self.native_inventory_entry_basis is None):
            message = "native inventory entry count requires its observation basis"
            raise ValueError(message)
        if self.measured_occurrences > self.recorded_saved_occurrences:
            message = "measured occurrences exceed recorded saved occurrences"
            raise ValueError(message)
        if self.reference_inventory_status != "enumerated" and self.reference_status_counts:
            message = "unavailable reference coverage cannot carry complete status counts"
            raise ValueError(message)
        match self.reference_inventory_status:
            case "enumerated":
                if (
                    self.native_inventory_entries is None
                    or self.inventory_reason is not None
                    or sum(row.count for row in self.reference_status_counts)
                    != self.native_inventory_entries
                    or self.recorded_saved_occurrences + self.recorded_unsaved_occurrences
                    != self.native_inventory_entries
                ):
                    message = (
                        "enumerated native/reference entries disagree with recorded occurrences"
                    )
                    raise ValueError(message)
            case "unavailable" | "legacy-unobserved":
                if self.inventory_reason is None:
                    message = "unavailable or legacy reference coverage requires an explicit reason"
                    raise ValueError(message)
            case _:
                assert_never(self.reference_inventory_status)
        return self


def visual_scope_status(
    pages: tuple[PageVisualCoverage, ...], candidates: int, measured: int
) -> VisualStatus:
    """A native inventory refusal or unsaved occurrence prevents a complete visual claim."""
    covered = bool(pages) and all(
        page.reference_inventory_status == "enumerated"
        and page.native_inventory_entries is not None
        and page.native_inventory_entries
        == page.recorded_saved_occurrences + page.recorded_unsaved_occurrences
        and page.recorded_unsaved_occurrences == 0
        for page in pages
    )
    if measured:
        return "complete-declared-raster-scope" if covered and measured == candidates else "partial"
    if covered and candidates == 0 and all(page.native_inventory_entries == 0 for page in pages):
        return "empty-declared-raster-scope"
    return "unavailable"


class VisualObservation(Record):
    """Pixels and reference coverage are conditional on the declared extraction scope."""

    method_version: Literal["1"] = "1"
    status: VisualStatus
    pages: tuple[PageVisualCoverage, ...] = Field(min_length=1, max_length=500)
    measured_asset_sha256s: tuple[str, ...]
    failures: tuple[VisualAssetFailure, ...]
    saved_asset_candidates: int = Field(ge=0)
    measured_assets: int = Field(ge=0)
    native_inventory_entries: int | None = Field(ge=0)
    known_native_inventory_entry_sum: int = Field(ge=0)
    unknown_native_inventory_pages: int = Field(ge=0)
    unavailable_reference_pages: int = Field(ge=0)
    limitations: tuple[str, ...] = (
        "Native inventory entries may include degenerate metadata placeholders",
        "Entry counts and saved raster measurements are not semantic figure or image totals",
        "Only saved base rasters are measured; vectors and uncomposited masks remain outside scope",
        "Partial extraction and unavailable inventories cannot establish a source-image zero",
    )

    @model_validator(mode="after")
    def coherent_scope(self) -> VisualObservation:
        """An explicit empty state requires observed zero inventory entries on every page."""
        if (
            self.measured_assets != len(self.measured_asset_sha256s)
            or self.measured_assets > self.saved_asset_candidates
        ):
            message = "visual asset counts disagree with accepted measurements"
            raise ValueError(message)
        if (self.native_inventory_entries is None) != (self.unknown_native_inventory_pages > 0):
            message = "unknown native inventory pages require unavailable total entry count"
            raise ValueError(message)
        if self.status == "empty-declared-raster-scope" and (
            not self.pages
            or self.native_inventory_entries != 0
            or self.unavailable_reference_pages
            or self.saved_asset_candidates
            or self.failures
        ):
            message = "empty raster scope requires complete observed zero inventory entries"
            raise ValueError(message)
        unknown = sum(page.native_inventory_entries is None for page in self.pages)
        known = sum(page.native_inventory_entries or 0 for page in self.pages)
        expected_total = known if unknown == 0 else None
        if (
            self.unknown_native_inventory_pages != unknown
            or self.known_native_inventory_entry_sum != known
            or self.native_inventory_entries != expected_total
            or self.unavailable_reference_pages
            != sum(page.reference_inventory_status != "enumerated" for page in self.pages)
        ):
            message = "visual aggregate coverage disagrees with its actual page observations"
            raise ValueError(message)
        if (
            self.status
            != visual_scope_status(self.pages, self.saved_asset_candidates, self.measured_assets)
            or len(self.failures) + self.measured_assets != self.saved_asset_candidates
            or len(set(self.measured_asset_sha256s)) != self.measured_assets
        ):
            message = "visual status or candidate accounting contradicts independent observations"
            raise ValueError(message)
        return self
