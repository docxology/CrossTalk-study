"""Bind explicitly authored review interpretations to exact current source passages."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from crosstalk.article_records import (
    ArticleError,
    ArticleObservation,
    ArticlePage,
    ArticleRecord,
    Passage,
    ReviewItem,
    text_digest,
    witness,
)
from crosstalk.article_validation import validate_evidence


class PassageSelection(ArticleRecord):
    """An exact searched string, explicit physical page/layer and occurrence choice."""

    page_index: int = Field(ge=0)
    layer: Literal["native", "ocr"] = "native"
    exact_text: str = Field(min_length=10, max_length=20_000)
    occurrence: int = Field(default=0, ge=0)


class ReviewSpecification(ArticleRecord):
    """Authored interpretations; code validates custody and does not invent their content."""

    issue_id: str
    title: str
    author_observed: str
    printed_start_observed: str
    title_selection: PassageSelection
    source_page_indices_read: tuple[int, ...]
    question: str
    contribution: str
    setting: str
    evidence_basis: str
    claims: tuple[str, ...]
    limitations: tuple[str, ...]
    implications: tuple[str, ...]
    supporting: tuple[PassageSelection, ...] = Field(min_length=1)
    contrary: tuple[PassageSelection, ...] = ()
    reviewer: str = "Codex; AI-assisted source-text reading; no independent human validation"


def select_passage(
    issue_id: str,
    selection: PassageSelection,
    pages: tuple[ArticlePage, ...],
) -> Passage:
    """Resolve the declared occurrence without fuzzy edits, inferred folios or layer fallback."""
    matches = tuple(
        page
        for page in pages
        if page.issue_id == issue_id
        and page.page_index == selection.page_index
        and page.layer == selection.layer
    )
    if len(matches) != 1:
        raise ArticleError("review selection requires one exact current source page")
    page = matches[0]
    offset = -1
    for _ in range(selection.occurrence + 1):
        offset = page.text.find(selection.exact_text, offset + 1)
        if offset < 0:
            raise ArticleError("authored review source phrase or occurrence is unavailable")
    return witness(page, offset, offset + len(selection.exact_text))


def build_review(
    specification: ReviewSpecification,
    pages: tuple[ArticlePage, ...],
) -> tuple[ArticleObservation, ReviewItem]:
    """Create one source-checked AI record; neither full boundary nor human review is certified."""
    spec = specification
    _ = validate_evidence(pages, ())
    title = select_passage(spec.issue_id, spec.title_selection, pages)
    available = {
        page.page_index
        for page in pages
        if page.issue_id == spec.issue_id and page.layer == spec.title_selection.layer
    }
    if not set(spec.source_page_indices_read) <= available:
        raise ArticleError("review claims reading unavailable physical pages")
    if len(spec.source_page_indices_read) != len(set(spec.source_page_indices_read)):
        raise ArticleError("review source-page selection repeats a physical page")
    if spec.title_selection.page_index not in spec.source_page_indices_read:
        raise ArticleError("review title must belong to its declared reading scope")
    if any(
        selection.page_index not in spec.source_page_indices_read
        or selection.layer != spec.title_selection.layer
        for selection in spec.supporting
    ):
        raise ArticleError("supporting passage is outside the declared reading scope or layer")
    # Contrary evidence may intentionally come from contents or another source layer.
    # Each such selection is still exact and independently bound to this admitted PDF.
    identity = text_digest(
        f"manual-reading-view-v2\0{title.pdf_sha256}\0{title.page_index}\0"
        + f"{title.layer}\0{title.start}:{title.end}\0{spec.title}"
    )
    observation = ArticleObservation(
        observation_id=identity,
        issue_id=spec.issue_id,
        title_observed=spec.title,
        author_observed=spec.author_observed,
        printed_start_observed=spec.printed_start_observed,
        kind="manual-witness",
        discovery_method="authored-exact-passage-selection-v2",
        witnesses=(title,),
        target_page_indices=(title.page_index,),
        target_layer=title.layer,
        boundary_status="start-corroborated",
        genre="article",
    )
    review = ReviewItem(
        observation_id=identity,
        question=spec.question,
        contribution=spec.contribution,
        setting=spec.setting,
        evidence_basis=spec.evidence_basis,
        claims=spec.claims,
        limitations=spec.limitations,
        implications=spec.implications,
        supporting_passages=tuple(select_passage(spec.issue_id, s, pages) for s in spec.supporting),
        contrary_passages=tuple(select_passage(spec.issue_id, s, pages) for s in spec.contrary),
        reviewer=spec.reviewer,
        full_article_read=False,
    )
    return observation, review
