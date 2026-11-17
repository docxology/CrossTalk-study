"""Typed, finite statistical observations with explicit units and source bindings."""

from __future__ import annotations

from typing import ClassVar, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crosstalk.analysis_records import PixelDecoder  # noqa: TC001 -- Pydantic resolves this type.
from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves this field type at runtime.
from crosstalk.statistical_scope import require_native_visual_scope


class StatisticalRecord(BaseModel):
    """Refuse untyped extras and nonfinite results at the artifact boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class BootstrapSettings(StatisticalRecord):
    """Predeclared diagnostic measures; minimum size is a heuristic, not a guarantee."""

    seed: int = Field(default=20261105, ge=0, le=2**63 - 1)
    resamples: int = Field(default=2000, ge=100, le=10_000)
    minimum_issues: int = Field(default=10, ge=5, le=1000)
    confidence: float = Field(default=0.95, gt=0, lt=1)
    max_issues: int = Field(default=1000, ge=1, le=10_000)
    window_size: int = Field(default=100, ge=2, le=10_000)


class SourceBinding(StatisticalRecord):
    """A current PDF and page artifact jointly accepted by both analysis producers."""

    issue_id: str
    pdf_sha256: Digest
    page_artifact_sha256: Digest


class StatisticalFailure(StatisticalRecord):
    """Explicit exclusions and unavailable observations, never zero measurements."""

    issue_id: str
    reason: str


class IssueStatistic(SourceBinding):
    """One source-distinct issue observation, with metadata dates kept conditional."""

    title: str
    issued: str | None
    date_status: Literal["metadata-only", "missing", "invalid", "conflict", "ambiguous"]
    date_precision: Literal["year", "month", "day", "unknown"]
    metadata_year: int | None
    metadata_decade: int | None
    extraction_status: Literal["complete", "partial"]
    pages: int = Field(ge=1)
    total_pdf_pages: int | None = Field(default=None, ge=1)
    extracted_page_fraction: float | None = Field(default=None, gt=0, le=1)
    raw_tokens: int
    normalized_tokens: int
    hedge_tokens: int
    modal_tokens: int
    hedge_per_1000: float | None
    modal_per_1000: float | None
    complete_windows: int
    mean_window_ttr: float | None
    low_text_pages: int
    visual_status: Literal[
        "complete-declared-raster-scope",
        "partial",
        "unavailable",
        "empty-declared-raster-scope",
        "legacy-unobserved",
    ] = "legacy-unobserved"
    measured_distinct_assets: int | None = Field(default=None, ge=0)
    measured_occurrences: int | None = Field(default=None, ge=0)
    native_inventory_entries: int | None = Field(default=None, ge=0)
    known_native_inventory_entry_sum: int | None = Field(default=None, ge=0)
    unknown_native_inventory_pages: int | None = Field(default=None, ge=0)
    unavailable_reference_pages: int | None = Field(default=None, ge=0)
    saved_distinct_assets: int
    saved_occurrences: int
    skipped_occurrences: int

    @model_validator(mode="after")
    def coherent_page_coverage(self) -> IssueStatistic:
        """Unknown totals stay unknown; complete status cannot contradict a known total."""
        total = self.total_pdf_pages
        if total is None:
            if self.extracted_page_fraction is not None:
                message = "unknown total PDF pages require unavailable coverage"
                raise ValueError(message)
        elif (
            self.pages > total
            or self.extracted_page_fraction != self.pages / total
            or (self.extraction_status == "complete" and self.pages != total)
        ):
            message = "known PDF page coverage disagrees with extraction scope or status"
            raise ValueError(message)
        return self


class PageStatistic(SourceBinding):
    """A physical-page measurement; pages are not independent bootstrap clusters."""

    page_index: int
    normalized_tokens: int
    types: int
    complete_windows: int
    mean_window_ttr: float | None
    saved_occurrences: int
    skipped_occurrences: int
    native_inventory_entries: int | None = Field(default=None, ge=0)
    native_inventory_entry_basis: Literal["native-occurrence-inventory"] | None = None
    reference_inventory_status: Literal["enumerated", "unavailable", "legacy-unobserved"] = (
        "legacy-unobserved"
    )
    low_text: bool


class ImageStatistic(SourceBinding):
    """An issue/asset pair; the same asset may occur in several issues and pages."""

    image_sha256: Digest
    path: str
    width: int
    height: int
    aspect_ratio: float
    grayscale_entropy_bits: float
    occurrence_count: int
    pixel_decoder: PixelDecoder = "pillow"
    pixel_decoder_version: str = "unrecorded"
    pixel_source_pdf: str | None = None
    pixel_source_sha256: str | None = None
    pixel_source_page_index: int | None = None
    pixel_source_xref: int | None = None
    pixel_decoder_initial_error: str | None = None


class Distribution(StatisticalRecord):
    """Finite captured-population distribution; null summaries mean no observations."""

    measure: str
    unit: str
    observed_units: int
    missing_units: int
    minimum: float | None
    q25: float | None
    median: float | None
    q75: float | None
    maximum: float | None
    mean: float | None
    unit_frame_complete: bool | None = None
    unknown_frame_pages: int | None = Field(default=None, ge=0)


class BootstrapInterval(StatisticalRecord):
    """Issue-cluster percentile interval; no p value or universal-population claim."""

    measure: Literal["pooled_hedge_per_1000", "pooled_modal_per_1000", "issue_mean_window_ttr"]
    estimand: str
    eligible_source_issue_units: int
    excluded_issue_units: int
    excluded_partial_issue_units: int
    excluded_unknown_coverage_issue_units: int
    excluded_metric_unavailable_issue_units: int
    denominator: str
    estimate: float | None
    lower: float | None
    upper: float | None
    valid_resamples: int
    constant_issue_values: bool
    diagnostic_interval_degenerate: bool
    status: Literal["available-diagnostic", "below-resampling-gate", "no-eligible-data"]

    @model_validator(mode="after")
    def coherent_interval(self) -> BootstrapInterval:
        """Unavailable inference cannot carry fabricated bounds or resample counts."""
        match self.status:
            case "available-diagnostic":
                if (
                    self.estimate is None
                    or self.lower is None
                    or self.upper is None
                    or self.valid_resamples < 1
                    or self.lower > self.upper
                ):
                    message = "available diagnostics require ordered bounds and resamples"
                    raise ValueError(message)
            case "below-resampling-gate" | "no-eligible-data":
                if self.lower is not None or self.upper is not None or self.valid_resamples != 0:
                    message = (
                        "unavailable bootstrap diagnostics must have null bounds and zero resamples"
                    )
                    raise ValueError(message)
            case _:
                assert_never(self.status)
        return self


class DecadeSummary(StatisticalRecord):
    """Repository-metadata decades, descriptive only and excluding unresolved dates."""

    metadata_decade: int
    issues: int
    pages: int
    raw_tokens: int
    saved_occurrences: int
    mean_issue_pages: float


class StatisticalRun(StatisticalRecord):
    """Current-source statistics with separate descriptive and diagnostic evidence."""

    method_version: Literal["2", "3"] = "2"
    observed_at: str
    source_binding_sha256: Digest
    implementation_sha256: Digest
    analysis_receipt_sha256: Digest
    linguistics_receipt_sha256: Digest
    extraction_receipt_sha256: Digest
    manifest_sha256: Digest | None
    settings: BootstrapSettings
    python_version: str
    extraction_issue_units: int
    selected_issue_units: int
    native_text_issue_units: int | None = Field(default=None, ge=0)
    pixel_measured_issue_units: int | None = Field(default=None, ge=0)
    visual_partial_issue_units: int | None = Field(default=None, ge=0)
    visual_unavailable_issue_units: int | None = Field(default=None, ge=0)
    visual_complete_scope_issue_units: int | None = Field(default=None, ge=0)
    complete_extraction_issue_units: int
    partial_extraction_issue_units: int
    unknown_page_coverage_issue_units: int
    principal_diagnostic_issue_units: int
    descriptive_scope: str = "All accepted source-distinct complete and partial extracted content"
    principal_diagnostic_scope: str = (
        "Complete-status source-distinct issues with known total PDF pages and full page coverage"
    )
    deferred_issue_ids: tuple[str, ...]
    random_generator: str = "Python random.Random MT19937; canonical issue order; integer seed"
    resampling: str = (
        "Sample eligible complete whole issues with replacement; preserve all within-issue data"
    )
    interval_method: str = (
        "Linear-interpolated percentile bootstrap; conditional captured-issue diagnostic"
    )
    issues: tuple[IssueStatistic, ...]
    pages: tuple[PageStatistic, ...]
    images: tuple[ImageStatistic, ...]
    distributions: tuple[Distribution, ...]
    bootstrap: tuple[BootstrapInterval, ...]
    decades: tuple[DecadeSummary, ...]
    unavailable: tuple[StatisticalFailure, ...]
    duplicate_issue_ids: tuple[str, ...]
    date_excluded_issue_ids: tuple[str, ...]
    unique_saved_assets: int
    limitations: tuple[str, ...] = (
        "Captured source-distinct issue PDFs are not an independently reconciled historical census",
        "Minimum issue count is a heuristic, not an independence or interval-coverage guarantee",
        "No article units, p values, causal effects or historical trend tests are produced",
        "Lexical proxies retain unreviewed layout, references and boilerplate",
        "Image masks remain uncomposited; partial extraction does not recover missing content",
        "Metadata dates are not independently verified printed publication dates",
        "Intervals condition on convenience-archive observations; representativeness is unproven",
        "Archive coverage, OCR/layout and annotation uncertainty are outside bootstrap bounds",
        "Constant observations can yield zero-width diagnostics without population certainty",
        "Zero-token issues are descriptive units but cannot supply pooled lexical-proxy rates",
        "Adjacent issues may share temporal/editorial dependence omitted by whole-issue resampling",
        "Distinct source digests do not establish independence between issues",
        "Principal diagnostics exclude partial extractions and issues with unknown page coverage",
        "NPS native custody only; publisher sources require a separate current-source adapter",
    )

    @model_validator(mode="after")
    def coherent_native_visual_scope(self) -> StatisticalRun:
        """New separate denominators cannot be inferred from a legacy mixed report."""
        require_native_visual_scope(self)
        return self
