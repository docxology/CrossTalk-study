"""Small source-bound native-layer reports reference immutable detailed observations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from crosstalk.extraction_method import ExtractionProducer  # noqa: TC001 -- Pydantic field.
from crosstalk.index_records import IndexBinding  # noqa: TC001 -- Pydantic field.
from crosstalk.models import AcquisitionError, Digest
from crosstalk.native_layers.cohort_records import CohortLayers  # noqa: TC001 -- Pydantic field.
from crosstalk.native_layers.records import LayerRecord
from crosstalk.statistical_records import BootstrapSettings

type LowTextFraction = Annotated[float, Field(ge=0, le=1)]


class NativeRunSettings(LayerRecord):
    """Bound a separate native phase; thresholds are declared workflow sensitivity only."""

    offset: int = Field(default=0, ge=0, le=10_000)
    max_issues: int = Field(default=10, ge=1, le=1000)
    source_kind: Literal["journal", "software-fixture"] = "journal"
    thresholds: tuple[LowTextFraction, ...] = Field(
        default=(0.0, 0.1, 0.2, 0.5, 1.0), min_length=1, max_length=10
    )
    bootstrap: BootstrapSettings = Field(default_factory=BootstrapSettings)

    @model_validator(mode="after")
    def distinct_thresholds(self) -> NativeRunSettings:
        """Unique ordered settings prevent duplicate views from looking independent."""
        if self.thresholds != tuple(sorted(set(self.thresholds))):
            raise AcquisitionError("native sensitivity thresholds must be unique and increasing")
        return self


class NativeIssueObservation(LayerRecord):
    """A compact observation points to retained page/line/rule evidence by exact digest."""

    issue_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    title: str
    pdf_sha256: Digest
    page_artifact_sha256: Digest
    evidence_path: str
    evidence_sha256: Digest
    physical_pdf_pages: int
    extracted_pages: int
    raw_tokens: int
    wrapper_minus_tokens: int
    matched_wrapper_page_indexes: tuple[int, ...]
    review_page_indexes: tuple[int, ...]
    zero_native_body: bool

    @model_validator(mode="after")
    def evidence_identity(self) -> NativeIssueObservation:
        """Only this issue's immutable native evidence can back the compact projection."""
        expected = f"output/data/native-layers/issues/{self.issue_id}-{self.evidence_sha256}.jsonl"
        if self.evidence_path != expected:
            raise AcquisitionError(
                "native-layer issue evidence locator disagrees with its identity"
            )
        return self


class NativeLayerFailure(LayerRecord):
    """A failed native-layer observation is unavailable, not a zero-rate source unit."""

    issue_id: str
    reason: str


class NativeLayerVariant(LayerRecord):
    """Each variant retains its own actual eligible IDs and marginal diagnostics."""

    label: str
    maximum_low_text_fraction: LowTextFraction | None
    cohort: CohortLayers
    interval_scope: str = (
        "Nominal marginal conditional whole-issue diagnostics; no joint-family coverage"
    )
    comparison_limit: str = (
        "Eligible frames may differ by view; no across-view difference inference"
    )


class NativeLayerRun(LayerRecord):
    """Current NPS native-only evidence; OCR and raster eligibility remain separate."""

    method_version: Literal["1"] = "1"
    observed_at: str
    implementation_sha256: Digest
    producer: ExtractionProducer
    settings: NativeRunSettings
    inventory_issue_units: int
    selected_issue_ids: tuple[str, ...]
    deferred_issue_ids: tuple[str, ...]
    outside_nps_manifest_issue_ids: tuple[str, ...]
    duplicate_issue_ids: tuple[str, ...]
    issues: tuple[NativeIssueObservation, ...]
    unavailable: tuple[NativeLayerFailure, ...]
    variants: tuple[NativeLayerVariant, ...]
    input_bindings: tuple[IndexBinding, ...]
    locator_ledger_paths: tuple[str, ...]
    scope: str = "Current NPS manifest native text only; raw/wrapper/rich views remain separate"
    accuracy_status: Literal["unmeasured-exploratory-template-rule"] = (
        "unmeasured-exploratory-template-rule"
    )


class NativeLayerReceipt(LayerRecord):
    """An independent current pointer seals immutable report and escaped HTML bytes."""

    summary_path: str
    summary_sha256: Digest
    html_path: str
    html_sha256: Digest

    @model_validator(mode="after")
    def immutable_locators(self) -> NativeLayerReceipt:
        """Content digests also identify the only admitted generated file paths."""
        if (
            self.summary_path != f"output/data/native-layers/runs/{self.summary_sha256}.jsonl"
            or self.html_path != f"output/reports/native-layers-{self.html_sha256}.html"
        ):
            raise AcquisitionError(
                "native-layer receipt points outside its immutable artifact slots"
            )
        return self
