"""Source-linked lexical retrieval records; examples never establish semantic labels."""

from __future__ import annotations

from typing import Literal, assert_never

from pydantic import Field, model_validator

from crosstalk.study_language_records import Digest, Identifier, Layer, Record, StudyError


class ConcordanceSettings(Record):
    """Freeze targets, context width and bounded diagnostic example selection."""

    targets: tuple[str, ...] = Field(min_length=1, max_length=100)
    context_tokens: int = Field(default=16, ge=1, le=50)
    examples_per_term_layer: int = Field(default=8, ge=1, le=30)
    seed: int = Field(default=7301, ge=0)
    maximum_units: int = Field(default=30_000, ge=1, le=100_000)
    maximum_tokens: int = Field(default=20_000_000, ge=1, le=50_000_000)

    @model_validator(mode="after")
    def unique_targets(self) -> ConcordanceSettings:
        """Duplicate targets cannot create repeated outcome rows that resemble replication."""
        if len(self.targets) != len(set(self.targets)) or any(not term for term in self.targets):
            raise StudyError("concordance targets must be unique and nonempty")
        return self


class KwicExample(Record):
    """One physical-source example, retaining exact offsets only when alignment is proved."""

    term: str
    layer: Layer
    unit_id: str
    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    layer_artifact_sha256: Digest
    unit_text_sha256: Digest
    region_id: Identifier | None
    article_id: Identifier | None
    token_index: int = Field(ge=0)
    normalized_left: tuple[str, ...]
    normalized_match: str
    normalized_right: tuple[str, ...]
    original_excerpt: str | None
    original_start: int | None = Field(default=None, ge=0)
    original_end: int | None = Field(default=None, gt=0)
    excerpt_status: Literal["exact-original-text-excerpt", "normalized-context-only"]
    quality: tuple[str, ...]
    offset_scope: Literal["SourceTextUnit.text character offsets"] = (
        "SourceTextUnit.text character offsets"
    )
    review_status: Literal["unreviewed-retrieval-context"] = "unreviewed-retrieval-context"

    @model_validator(mode="after")
    def excerpt_identity(self) -> KwicExample:
        """Refuse partial or contradictory original-text locator claims."""
        observed = (self.original_excerpt, self.original_start, self.original_end)
        match self.excerpt_status:
            case "normalized-context-only":
                valid = observed == (None, None, None)
            case "exact-original-text-excerpt":
                valid = (
                    self.original_excerpt is not None
                    and self.original_start is not None
                    and self.original_end is not None
                    and self.original_end - self.original_start == len(self.original_excerpt)
                )
            case _:
                assert_never(self.excerpt_status)
        if not valid:
            raise StudyError("concordance excerpt status/offsets disagree")
        return self


class TermConcordance(Record):
    """Full occurrence/issue/unit counts precede every diagnostic display cap."""

    term: str
    layer: Layer
    occurrences: int = Field(ge=0)
    matching_units: int = Field(ge=0)
    matching_issues: int = Field(ge=0)
    supplied_units: int = Field(ge=0)
    positive_token_issues: int = Field(ge=0)
    supplied_tokens: int = Field(ge=0)
    examples: tuple[KwicExample, ...]


class ConcordanceRun(Record):
    """Deterministic retrieval diagnostics, with unchanged original text and explicit sampling."""

    method_version: Literal["study-concordance-1"] = "study-concordance-1"
    implementation_sha256: Digest
    unit_frame_sha256: Digest
    settings: ConcordanceSettings
    units: int
    terms: tuple[TermConcordance, ...]
    example_selection: str = (
        ("First hit per issue in sorted physical-page," + " unit/region-ID and token order; ")
        + (
            "unit/region-ID order is not verified reading"
            + " order. Seed-framed SHA256 issue order; "
        )
        + (
            "at most the declared examples per term/layer"
            + ". Diagnostic examples, not a validation samp"
            + "le."
        )
    )
    accuracy_status: None = None
    interpretation: str = (
        (
            "Normalized token windows are retrieval conte"
            + "xts, not quotations. Exact-original excerpts"
            + " "
        )
        + ("retain extraction order and require external" + " source/reading-order inspection. ")
        + "A hit does not establish topic, word error, speaker or genre."
    )
