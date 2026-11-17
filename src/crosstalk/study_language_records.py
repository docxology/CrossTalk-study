"""Finite source-text inputs and descriptive language/contrast result contracts."""

from __future__ import annotations

import hashlib
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=240)]
Layer = Literal["native", "ocr"]


class StudyError(ValueError):
    """A structured input/method refusal, without modifying any scientific input."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Retain the reason for structured caller reporting."""
        self.reason = reason
        super().__init__(reason)


class Record(BaseModel):
    """Immutable finite persisted records; custody admission remains the caller's job."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class SourceTextUnit(Record):
    """One supplied page/region text layer, never an automatically verified article."""

    unit_id: Identifier
    issue_id: Identifier
    pdf_sha256: Digest
    page_index: int = Field(ge=0, le=499)
    text: Annotated[str, Field(max_length=2_000_000)]
    layer: Layer
    layer_artifact_sha256: Digest
    article_id: Identifier | None = None
    region_id: Identifier | None = None
    quality: tuple[str, ...] = ()

    @property
    def text_sha256(self) -> str:
        """Exact original UTF-8 text identity, before reversible token normalization."""
        return hashlib.sha256(self.text.encode()).hexdigest()


class LanguageSettings(Record):
    """Declared bounded displays; term counts retain the complete selected vocabulary."""

    window_tokens: int = Field(default=100, ge=2, le=10_000)
    displayed_terms: int = Field(default=100, ge=1, le=2000)
    displayed_pairs: int = Field(default=100, ge=1, le=2000)
    minimum_pair_count: int = Field(default=3, ge=1)
    maximum_units: int = Field(default=30_000, ge=1, le=100_000)
    maximum_tokens: int = Field(default=20_000_000, ge=1, le=50_000_000)
    maximum_vocabulary: int = Field(default=500_000, ge=1, le=1_000_000)


class TermCount(Record):
    """A complete count, with its issue's denominator on the enclosing record."""

    term: str
    count: int = Field(ge=1)


class IssueCounts(Record):
    """One physical-source issue/layer cluster; all terms, including stopwords, retained."""

    issue_id: Identifier
    pdf_sha256: Digest
    tokens: int = Field(ge=0)
    units: int = Field(ge=1)
    terms: tuple[TermCount, ...]

    @model_validator(mode="after")
    def complete_counts(self) -> IssueCounts:
        """Refuse edited totals and duplicate vocabulary rows at the persisted boundary."""
        if sum(row.count for row in self.terms) != self.tokens or len(
            {row.term for row in self.terms}
        ) != len(self.terms):
            raise StudyError("issue vocabulary counts disagree with the token denominator")
        return self


class TermProfile(Record):
    """Frequency and dispersion among positive-token issue clusters."""

    term: str
    count: int
    per_1000_tokens: float
    observed_issues: int
    eligible_issues: int
    issue_prevalence: float
    deviation_from_token_share: float


class PairProfile(Record):
    """Within-unit adjacent token association; no syntactic or semantic relation inferred."""

    left: str
    right: str
    count: int
    log_dice: float


class UnitMeasure(Record):
    """Equal-length windows restart at every supplied unit; tails remain disclosed."""

    unit_id: Identifier
    issue_id: Identifier
    article_id: Identifier | None
    tokens: int
    types: int
    complete_windows: int
    discarded_tokens: int
    mean_window_ttr: float | None


class LayerMeasure(Record):
    """A layer-specific observed corpus; absent layers are never pooled or imputed."""

    layer: Layer
    units: tuple[UnitMeasure, ...]
    issues: tuple[IssueCounts, ...]
    tokens: int
    types: int
    zero_token_units: int
    eligible_issues: int
    pair_opportunities: int
    frequencies: tuple[TermProfile, ...]
    adjacent_pairs: tuple[PairProfile, ...]


class LanguageRun(Record):
    """Content-addressed pure measurement, not independent admission or accuracy evidence."""

    method_version: Literal["study-language-1"] = "study-language-1"
    implementation_sha256: Digest
    input_sha256: Digest
    settings: LanguageSettings
    layers: tuple[LayerMeasure, ...]
    input_units: int
    normalization: str = "NFKC; casefold; curly apostrophe to ASCII; existing alphabetic TOKEN"


class ContrastPlan(Record):
    """Frozen disjoint issue cohorts; labels/genres/chronology are supplied observations."""

    name: Identifier
    layer: Layer
    cohort_a: tuple[Identifier, ...]
    cohort_b: tuple[Identifier, ...]
    minimum_total_count: int = Field(default=10, ge=1)
    minimum_observed_issues: int = Field(default=2, ge=1)
    maximum_terms: int = Field(default=50, ge=1, le=500)
    pseudocount: float = Field(default=0.5, gt=0, le=10)
    minimum_cluster_issues: int = Field(default=5, ge=2, le=100)
    resamples: int = Field(default=999, ge=100, le=5000)
    seed: int = Field(default=7301, ge=0)

    @model_validator(mode="after")
    def distinct_cohorts(self) -> ContrastPlan:
        """Reject repeated or overlapping clusters before any ranking or resampling."""
        joined = (*self.cohort_a, *self.cohort_b)
        if not self.cohort_a or not self.cohort_b or len(joined) != len(set(joined)):
            raise StudyError("contrast needs two nonempty disjoint cohorts of unique issue IDs")
        return self


class KeynessTerm(Record):
    """Effect and conditional marginal interval; G squared is exclusively a ranking score."""

    term: str
    count_a: int
    count_b: int
    tokens_a: int
    tokens_b: int
    observed_issues_a: int
    observed_issues_b: int
    g_squared_rank_score: float
    log2_rate_ratio: float
    interval_status: Literal["available-diagnostic", "below-cluster-gate"]
    lower: float | None
    upper: float | None


class CountComparison(Record):
    """Two token-rate counts with their own positive opportunity denominators."""

    count_a: int = Field(ge=0)
    count_b: int = Field(ge=0)
    tokens_a: int = Field(gt=0)
    tokens_b: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_counts(self) -> CountComparison:
        """A term cannot occur more often than its selected token denominator."""
        if self.count_a > self.tokens_a or self.count_b > self.tokens_b:
            raise StudyError("term count exceeds its token denominator")
        return self


class ContrastResult(Record):
    """Exact exploratory contrast with explicit eligible clusters and no token p-values."""

    plan: ContrastPlan
    plan_sha256: Digest
    language_input_sha256: Digest
    implementation_sha256: Digest
    eligible_a: tuple[str, ...]
    eligible_b: tuple[str, ...]
    zero_token_issue_ids: tuple[str, ...]
    tested_vocabulary: int
    terms: tuple[KeynessTerm, ...]
    interval_scope: str = (
        "Nominal marginal 95% percentile diagnostics, independently resampling whole issues "
        + "within supplied cohorts; conditional on observed text and cohort selection. "
        + "No multiplicity-adjusted, temporal-independence, causal or accuracy claim."
    )


class StudyFigure(Record):
    """Self-contained vector source; callers publish with their complete source binding set."""

    name: str
    svg: str
    caption: str
