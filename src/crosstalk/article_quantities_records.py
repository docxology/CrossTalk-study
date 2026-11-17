"""Exact quantitative-expression observations are retrieval aids, never effect estimates."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from crosstalk.article_records import ArticleError, ArticleRecord, Digest, Passage

QuantityForm = Literal[
    "percent-form",
    "percentage-point-form",
    "fold-form",
    "colon-form",
    "ratio-word-form",
    "count-unit-form",
]
CueForm = Literal[
    "assumption-or-estimation-word",
    "model-or-simulation-word",
    "observation-word",
    "qualification-word",
    "future-or-proposal-word",
    "attribution-or-source-word",
    "comparison-word",
    "statistical-word",
]


def _identity(passage: Passage) -> tuple[str, str, int, str, str, str, str]:
    """One exact physical source and derivative layer identity."""
    return (
        passage.issue_id,
        passage.pdf_sha256,
        passage.page_index,
        passage.layer,
        passage.artifact_path,
        passage.artifact_sha256,
        passage.page_text_sha256,
    )


class QuantitySettings(ArticleRecord):
    """Capacity excess refuses the run; no omitted pages or truncated expression census."""

    selection_label: str = Field(default="caller-supplied-pages", min_length=1, max_length=240)
    context_characters_each_side: int = Field(default=240, ge=20, le=1000)
    maximum_cues_per_expression: int = Field(default=24, ge=1, le=100)
    maximum_pages: int = Field(default=30_000, ge=1, le=100_000)
    maximum_characters: int = Field(default=100_000_000, ge=1, le=250_000_000)
    maximum_expressions: int = Field(default=100_000, ge=1, le=250_000)
    maximum_expressions_per_page: int = Field(default=5000, ge=1, le=20_000)


class QuantitySource(ArticleRecord):
    """One admitted page layer, including its observed empty/no-match state."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    page_label: str
    layer: Literal["native", "ocr"]
    artifact_path: str
    artifact_sha256: Digest
    page_text_sha256: Digest
    characters: int = Field(ge=0)
    flags: tuple[str, ...]


class NearbyCue(ArticleRecord):
    """A local lexical form, not an attachment, negation or evidence-status judgment."""

    form: CueForm
    source: Passage
    semantic_attachment_verified: Literal[False] = False


class QuantityMention(ArticleRecord):
    """A literal expression plus raw context; no normalized number or effect is calculated."""

    mention_id: Digest
    form: QuantityForm
    value_observed: str = Field(min_length=1, max_length=120)
    unit_observed: str = Field(min_length=1, max_length=80)
    source: Passage
    context: Passage
    nearby_cues: tuple[NearbyCue, ...]
    omitted_nearby_cues: int = Field(ge=0)
    flags: tuple[str, ...]
    evidence_status: Literal["unassessed"] = "unassessed"
    effect_estimate_calculated: Literal[False] = False

    @model_validator(mode="after")
    def local_scope(self) -> QuantityMention:
        """A context or cue cannot quietly cross physical page, PDF, layer or artifact."""
        if _identity(self.source) != _identity(self.context) or not (
            self.context.start <= self.source.start < self.source.end <= self.context.end
        ):
            raise ArticleError("quantitative context crosses its exact source identity or bounds")
        for cue in self.nearby_cues:
            if _identity(cue.source) != _identity(self.source) or not (
                self.context.start <= cue.source.start < cue.source.end <= self.context.end
            ):
                raise ArticleError("nearby quantitative cue crosses the bounded source context")
        return self


class QuantityFormCount(ArticleRecord):
    """Syntactic form counts are not counts of empirical claims or effect sizes."""

    form: QuantityForm
    expressions: int = Field(ge=0)


class QuantityLayerSummary(ArticleRecord):
    """Native and OCR opportunities remain separate, including zero-match pages."""

    layer: Literal["native", "ocr"]
    pages: int = Field(ge=0)
    issues: int = Field(ge=0)
    raw_characters: int = Field(ge=0)
    expression_pages: int = Field(ge=0)
    no_expression_pages: int = Field(ge=0)
    form_counts: tuple[QuantityFormCount, ...]

    @model_validator(mode="after")
    def page_counts(self) -> QuantityLayerSummary:
        """An observed no-match page is retained without being called missing or empty print."""
        if self.expression_pages + self.no_expression_pages != self.pages:
            raise ArticleError("quantitative retrieval page denominators disagree")
        if len({row.form for row in self.form_counts}) != len(self.form_counts):
            raise ArticleError("quantitative form summary repeats a category")
        return self


class QuantityRun(ArticleRecord):
    """Complete bounded syntactic retrieval, conditional on supplied current source text."""

    method_version: Literal["quantitative-expression-retrieval-1"] = (
        "quantitative-expression-retrieval-1"
    )
    input_sha256: Digest
    implementation_sha256: Digest
    settings_sha256: Digest
    settings: QuantitySettings
    sources: tuple[QuantitySource, ...]
    expressions: tuple[QuantityMention, ...]
    layers: tuple[QuantityLayerSummary, ...]
    matching_scope: str
    semantic_accuracy_validated: Literal[False] = False
    historical_completeness_inferred: Literal[False] = False

    @model_validator(mode="after")
    def count_scope(self) -> QuantityRun:
        """Layer counts and unique observations must agree with their retained source records."""
        if len({row.mention_id for row in self.expressions}) != len(self.expressions):
            raise ArticleError("quantitative retrieval repeats an expression identity")
        if tuple(row.layer for row in self.layers) != ("native", "ocr"):
            raise ArticleError("quantitative retrieval requires separate native and OCR summaries")
        for layer in self.layers:
            expressions = tuple(row for row in self.expressions if row.source.layer == layer.layer)
            sources = tuple(row for row in self.sources if row.layer == layer.layer)
            if layer.pages != len(sources) or sum(c.expressions for c in layer.form_counts) != len(
                expressions
            ):
                raise ArticleError(
                    "quantitative retrieval summary disagrees with retained observations"
                )
        return self
