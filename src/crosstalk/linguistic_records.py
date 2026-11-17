"""Typed settings and descriptive linguistic diagnostic artifacts."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crosstalk.models import Digest, require_nps_url
from crosstalk.records import Record


class LinguisticSettings(BaseModel):
    """Explicit truncation, equal-length sampling and recurrence bounds."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    top_terms: int = Field(default=100, ge=1, le=1000)
    top_ngrams: int = Field(default=50, ge=1, le=500)
    top_boilerplate: int = Field(default=50, ge=1, le=1000)
    window_size: int = Field(default=100, ge=2, le=10_000)
    boilerplate_min_pages: int = Field(default=3, ge=2, le=500)
    boilerplate_min_fraction: float = Field(default=0.5, gt=0, le=1)
    boilerplate_min_tokens: int = Field(default=3, ge=1, le=200)
    boilerplate_max_tokens: int = Field(default=40, ge=1, le=200)
    max_issues: int = Field(default=1000, ge=1, le=10_000)

    @model_validator(mode="after")
    def ordered_line_bounds(self) -> LinguisticSettings:
        """Refuse an impossible repeated-line length interval."""
        if self.boilerplate_min_tokens > self.boilerplate_max_tokens:
            message = "boilerplate_min_tokens must not exceed boilerplate_max_tokens"
            raise ValueError(message)
        return self


class NormalizedFrequency(Record):
    """A normalized token count; denominator includes every retained word token."""

    token: str
    count: int
    per_1000_tokens: float


class NGramFrequency(Record):
    """Contiguous token adjacency with page-level evidence, never a collocation claim."""

    tokens: tuple[str, ...]
    count: int
    per_1000_opportunities: float
    page_indexes: tuple[int, ...]


class NGramProfile(Record):
    """Top adjacency counts with the full page-bounded opportunity denominator."""

    size: Literal[2, 3]
    opportunities: int
    distinct_ngrams: int
    frequencies: tuple[NGramFrequency, ...]


class WindowDiversity(Record):
    """Nonoverlapping complete windows; each page restarts the sampling grid."""

    window_size: int
    complete_windows: int
    tokens_used: int
    tokens_discarded: int
    mean_type_token_ratio: float | None
    status: Literal["available", "insufficient-data"]


class PageDistribution(Record):
    """Physical-page word distribution with extraction quality kept visible."""

    page_index: int
    page_label: str
    tokens: int
    types: int
    fraction_of_issue_tokens: float | None
    quality: tuple[str, ...]
    diversity: WindowDiversity


class BoilerplateCandidate(Record):
    """Repeated normalized line requiring human review before any exclusion."""

    normalized_line: str
    page_indexes: tuple[int, ...]
    page_fraction: float
    status: Literal["candidate-not-excluded"] = "candidate-not-excluded"


class LinguisticMeasures(Record):
    """Page-bounded diagnostics on normalized extracted text, including boilerplate."""

    tokens: int
    types: int
    frequencies: tuple[NormalizedFrequency, ...]
    bigrams: NGramProfile
    trigrams: NGramProfile
    pages: tuple[PageDistribution, ...]
    complete_windows: int
    mean_window_type_token_ratio: float | None
    boilerplate_candidates_total: int
    boilerplate_candidates: tuple[BoilerplateCandidate, ...]


class IssueLinguistics(Record):
    """Measurements bound to exact local source and extracted-page bytes."""

    issue_id: str
    title: str
    source_url: str | None
    source_sha256: Digest
    page_artifact_sha256: Digest
    extraction_status: Literal["complete", "partial"]
    total_pdf_pages: int | None = Field(default=None, ge=1)
    measures: LinguisticMeasures

    @field_validator("source_url")
    @classmethod
    def official_source_url(cls, value: str | None) -> str | None:
        """Keep source links on the same official-host boundary as the inventory."""
        return require_nps_url(value) if value is not None else None


class LinguisticFailure(Record):
    """An unavailable issue observation, preserved independently of peers."""

    issue_id: str
    reason: str


class LinguisticRun(Record):
    """Reproducibility receipt for one explicitly bounded diagnostic run."""

    observed_at: str
    method_version: Literal["1"] = "1"
    normalization: str = "Unicode NFKC, casefold, curly apostrophe to ASCII; alphabetic word tokens"
    sampling: str = "Nonoverlapping complete token windows restarted on each physical PDF page"
    adjacency: str = "Within-page token adjacency; punctuation does not define sentence boundaries"
    implementation_sha256: Digest
    extraction_receipt_sha256: Digest
    extractor_version: str
    manifest_sha256: Digest | None
    environment_lock_sha256: Digest | None
    python_version: str
    settings: LinguisticSettings
    inventory_issues: int
    selected_issues: int
    issues: tuple[IssueLinguistics, ...]
    duplicate_issue_ids: tuple[str, ...]
    unavailable: tuple[LinguisticFailure, ...]
    limitations: tuple[str, ...] = (
        "Descriptive issue/page measurements; no article boundaries or semantic interpretation",
        "OCR, reading order, references and boilerplate can affect all counts",
        "Repeated-line candidates are retained, not automatically removed",
        "Top-frequency lists are truncated; reported denominators include the full selected text",
        "Partial extractions remain partial; no archive completeness or inferential claim",
    )
