"""Article observations distinguish discovery, boundary adjudication and interpretation."""

from __future__ import annotations

import hashlib
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Box = tuple[float, float, float, float]


class ArticleError(ValueError):
    """Explicit refusal of article provenance or an unsupported review assertion."""


class ArticleRecord(BaseModel):
    """Immutable, finite, extra-forbidding research record."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class SourceBlock(ArticleRecord):
    """Unchanged native or OCR block; its order is not a reading-order assertion."""

    block_number: int = Field(ge=0)
    bbox: Box
    text: str = Field(max_length=100_000)


class ArticlePage(ArticleRecord):
    """A page of independently sealed text, retaining acquisition layer and geometry."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    page_label: str
    layer: Literal["native", "ocr"]
    artifact_path: str
    artifact_sha256: Digest
    text: str = Field(max_length=1_000_000)
    blocks: tuple[SourceBlock, ...]
    flags: tuple[str, ...] = ()


class Passage(ArticleRecord):
    """Exact substring witness with both artifact and page-text identities."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    layer: Literal["native", "ocr"]
    artifact_path: str
    artifact_sha256: Digest
    page_text_sha256: Digest
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def length_agrees(self) -> Passage:
        """A passage cannot claim a different span length from its exact source text."""
        if self.end - self.start != len(self.text):
            raise ArticleError("passage offsets disagree with text")
        return self


class ArticleObservation(ArticleRecord):
    """A source-listed title or detected heading is provisional until adjudicated."""

    observation_id: Digest
    issue_id: str
    title_observed: str = Field(min_length=1, max_length=1000)
    printed_start_observed: str | None = None
    author_observed: str | None = None
    kind: Literal["contents-entry", "native-heading", "archival-index", "manual-witness"]
    witnesses: tuple[Passage, ...] = Field(min_length=1)
    target_page_indices: tuple[int, ...] = ()
    target_layer: Literal["native", "ocr"] | None = None
    title_match_score: float | None = Field(default=None, ge=0, le=1)
    discovery_method: str = "explicit-contents-row-v1"
    layout_artifact_sha256: Digest | None = None
    discovery_flags: tuple[str, ...] = ()
    boundary_status: Literal["unresolved", "start-corroborated", "regions-adjudicated"] = (
        "unresolved"
    )
    genre: Literal["unreviewed", "article", "editorial", "news", "review", "other"] = "unreviewed"


class ArticleRegion(ArticleRecord):
    """Explicit ordered regions, supporting mixed pages and nonconsecutive continuations."""

    observation_id: Digest
    order: int = Field(ge=0)
    page_index: int = Field(ge=0)
    bbox: Box
    role: Literal["title", "byline", "abstract", "body", "reference", "caption"]
    passage: Passage
    adjudicator: str = Field(min_length=1)
    adjudication_basis: str = Field(min_length=10)


class ReviewItem(ArticleRecord):
    """Source-checked interpretation; independent human validation remains separate."""

    observation_id: Digest
    question: str
    contribution: str
    setting: str
    evidence_basis: str
    claims: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    implications: tuple[str, ...]
    supporting_passages: tuple[Passage, ...] = Field(min_length=1)
    contrary_passages: tuple[Passage, ...] = ()
    status: Literal["source-checked-ai", "independently-human-reviewed"] = "source-checked-ai"
    reviewer: str
    full_article_read: bool = False
    independent_review_receipt: str | None = None

    @model_validator(mode="after")
    def human_receipt(self) -> ReviewItem:
        """Prevent automated records from manufacturing independent validation."""
        if self.status == "independently-human-reviewed" and not self.independent_review_receipt:
            raise ArticleError("independent human review requires a receipt")
        return self


def text_digest(text: str) -> str:
    """Hash exact UTF-8 text without normalization or silent deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def witness(page: ArticlePage, start: int, end: int) -> Passage:
    """Bind an exact nonempty page substring to its immutable derivative."""
    if start < 0 or end > len(page.text) or end <= start:
        raise ArticleError("witness is outside the exact source page")
    return Passage(
        issue_id=page.issue_id,
        pdf_sha256=page.pdf_sha256,
        page_index=page.page_index,
        layer=page.layer,
        artifact_path=page.artifact_path,
        artifact_sha256=page.artifact_sha256,
        page_text_sha256=text_digest(page.text),
        start=start,
        end=end,
        text=page.text[start:end],
    )


def standalone_folio(page: ArticlePage, value: str) -> Passage | None:
    """Bind one unambiguous standalone folio, never a phone/date suffix."""
    found: list[tuple[int, int]] = []
    offset = 0
    for raw in page.text.splitlines(keepends=True):
        if raw.strip() == value:
            start = offset + len(raw) - len(raw.lstrip())
            found.append((start, start + len(value)))
        offset += len(raw)
    return witness(page, *found[0]) if len(found) == 1 else None
