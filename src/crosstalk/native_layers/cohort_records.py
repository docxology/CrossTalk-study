"""Named native layers and weighting retain independent post-selection denominators."""

from __future__ import annotations

from typing import Literal, assert_never

from pydantic import Field, model_validator

from crosstalk.models import AcquisitionError
from crosstalk.native_layers.records import LayerRecord
from crosstalk.statistical_records import BootstrapSettings

type ViewName = Literal["raw-native", "native-minus-matched-repository-wrapper"]
type LexicalMeasure = Literal["hedge-lexicon-per-1000", "modal-lexicon-per-1000"]
type Weighting = Literal["token-weighted", "equal-issue-weighted"]


class LayerInterval(LayerRecord):
    """A whole-issue diagnostic excludes extraction and classifier uncertainty."""

    measure: LexicalMeasure
    weighting: Weighting
    eligible_issue_ids: tuple[str, ...]
    estimate: float | None
    lower: float | None
    upper: float | None
    valid_resamples: int
    status: Literal["available-diagnostic", "below-resampling-gate", "no-eligible-data"]
    constant_issue_values: bool

    @model_validator(mode="after")
    def coherent_availability(self) -> LayerInterval:
        """Unavailable rates cannot acquire invented bounds or resampling counts."""
        match self.status:
            case "available-diagnostic":
                valid = (
                    self.estimate is not None
                    and self.lower is not None
                    and self.upper is not None
                    and self.valid_resamples > 0
                    and self.lower <= self.upper
                )
            case "below-resampling-gate" | "no-eligible-data":
                valid = self.lower is None and self.upper is None and self.valid_resamples == 0
            case _:
                assert_never(self.status)
        if not valid:
            raise AcquisitionError("native-layer interval and availability status disagree")
        return self


class PeriodAvailability(LayerRecord):
    """Descriptive metadata-period missingness is not a prevalence estimate."""

    unit: Literal["metadata-year", "metadata-decade"]
    period_start: int
    observed_issue_units: int
    complete_extraction_issue_units: int
    partial_extraction_issue_units: int
    zero_native_token_issue_units: int
    physical_pdf_pages: int
    selected_native_pages: int
    native_tokens: int


class CohortLayers(LayerRecord):
    """Observed-view counts and bootstrap eligibility are distinct denominators."""

    view: ViewName
    native_rich_restriction: bool
    settings: BootstrapSettings
    observed_issue_ids: tuple[str, ...]
    workflow_selected_issue_ids: tuple[str, ...]
    eligible_complete_nonzero_issue_ids: tuple[str, ...]
    partial_issue_ids: tuple[str, ...]
    zero_native_token_issue_ids: tuple[str, ...]
    observed_physical_pages: int
    excluded_wrapper_pages: int
    observed_native_characters: int
    observed_native_tokens: int
    observed_low_text_pages: int
    observed_low_text_fraction: float | None
    unknown_or_conflicting_date_issue_ids: tuple[str, ...]
    metadata_periods: tuple[PeriodAvailability, ...]
    intervals: tuple[LayerInterval, ...]
    inference_scope: Literal["conditional-observed-source-issues-only"] = (
        "conditional-observed-source-issues-only"
    )


class CohortSettings(LayerRecord):
    """Declare a named layer, workflow restriction and bounded whole-issue bootstrap."""

    view: ViewName
    bootstrap: BootstrapSettings = Field(default_factory=BootstrapSettings)
    native_rich: bool = False
