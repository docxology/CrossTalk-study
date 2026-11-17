"""Typed exploratory analysis outputs with explicit scientific limits."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from crosstalk.image_preview import ImagePreview  # noqa: TC001 -- Pydantic resolves this field.
from crosstalk.records import Record
from crosstalk.visual_records import VisualObservation  # noqa: TC001 -- Pydantic runtime field.

type PixelDecoder = Literal["pillow", "pymupdf-source-context"]


class TermCount(Record):
    """One normalized lexical form and its observed count."""

    term: str
    count: int


class CategoryHit(Record):
    """Provisional keyword retrieval label with page-level evidence."""

    category: str
    evidence_terms: tuple[str, ...]
    page_indexes: tuple[int, ...]
    status: str = "provisional-rule-based"


class TextMetrics(Record):
    """Raw descriptive counts, not a validated measure of writing quality."""

    tokens: int
    types: int
    type_token_ratio: float | None
    hedge_tokens: int
    modal_tokens: int
    hedge_per_1000: float | None
    modal_per_1000: float | None
    terms: tuple[TermCount, ...]


class VisualMetrics(Record):
    """Base-image measurements; no semantic interpretation or figure detection."""

    sha256: str
    path: str
    width: int
    height: int
    aspect_ratio: float
    grayscale_entropy_bits: float
    mean_rgb: tuple[float, float, float]
    occurrence_count: int
    page_indexes: tuple[int, ...]
    pixel_decoder: PixelDecoder = "pillow"
    pixel_decoder_version: str = "unrecorded"
    pixel_source_pdf: str | None = None
    pixel_source_sha256: str | None = None
    pixel_source_page_index: int | None = None
    pixel_source_xref: int | None = None
    pixel_decoder_initial_error: str | None = None
    mask_composited: Literal[False] = False
    preview: ImagePreview | None = None


class AnalysisFailure(Record):
    """Explicit source-stage exclusions, including both decoder failures where applicable."""

    issue_id: str
    stage: Literal[
        "extraction",
        "pdf",
        "page-cache",
        "provenance",
        "image-integrity",
        "image-pillow",
        "image-native",
    ]
    path: str | None
    reason: str
    error_type: str | None = None
    initial_error: str | None = None


class IssueAnalysis(Record):
    """Descriptive analysis of extracted issue pages, never inferred articles."""

    analysis_method_version: Literal["2", "3"] = "2"
    issue_id: str
    title: str
    issued: str | None
    source_url: str | None
    source_sha256: str
    pages: int
    low_text_pages: int
    text: TextMetrics
    categories: tuple[CategoryHit, ...]
    images: tuple[VisualMetrics, ...]
    visual: VisualObservation | None = None

    @model_validator(mode="after")
    def coherent_visual_method(self) -> IssueAnalysis:
        """Legacy empty images remain historical, without acquiring new visual-zero evidence."""
        if (self.analysis_method_version == "3") != (self.visual is not None):
            message = "analysis method3 requires explicit visual coverage; method2 is historical"
            raise ValueError(message)
        if (
            self.visual is not None
            and tuple(image.sha256 for image in self.images) != self.visual.measured_asset_sha256s
        ):
            message = "analysis images disagree with their declared measured asset identities"
            raise ValueError(message)
        if self.visual is not None and any(
            failure.issue_id != self.issue_id for failure in self.visual.failures
        ):
            message = "visual failure belongs to a different native source identity"
            raise ValueError(message)
        return self


class AnalysisSummary(Record):
    """Corpus scope, duplicate exclusions and explicitly exploratory results."""

    method_version: Literal["2", "3"] = "2"
    issues: tuple[IssueAnalysis, ...]
    visual_unavailable_issues: tuple[str, ...] = ()
    visual_partial_issues: tuple[str, ...] = ()
    duplicate_issues: tuple[str, ...]
    unavailable_issues: tuple[str, ...]
    unavailable_details: tuple[AnalysisFailure, ...] = ()
    corpus_text: TextMetrics
    status: str = "exploratory-not-peer-reviewed"
    limitations: tuple[str, ...] = (
        "Local downloaded subset only; no archive completeness claim",
        "Issue-level analysis; article boundaries are not inferred",
        "Native-text baseline excludes separate OCR derivatives; English lexicons require review",
        "Type-token ratios depend on text length; hedging and modality are lexical proxies",
        "Base images exclude vectors and unavailable inline images; masks remain uncomposited",
        "Native custody targets the NPS Issue manifest; publisher-family custody is separate",
    )

    @model_validator(mode="after")
    def coherent_method_scope(self) -> AnalysisSummary:
        """New native/visual coverage cannot be inferred from old mixed reports."""
        if any(issue.analysis_method_version != self.method_version for issue in self.issues):
            message = "analysis summary and issue method versions disagree"
            raise ValueError(message)
        unavailable = tuple(
            issue.issue_id
            for issue in self.issues
            if issue.visual is not None and issue.visual.status == "unavailable"
        )
        partial = tuple(
            issue.issue_id
            for issue in self.issues
            if issue.visual is not None and issue.visual.status == "partial"
        )
        if unavailable != self.visual_unavailable_issues or partial != self.visual_partial_issues:
            message = "visual coverage issue lists disagree with explicit observations"
            raise ValueError(message)
        return self
