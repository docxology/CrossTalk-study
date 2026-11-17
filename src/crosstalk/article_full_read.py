"""Bind a declared complete reading to exact article regions and inspected physical pages."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from crosstalk.article_records import (
    ArticleError,
    ArticleRecord,
    Digest,
    Passage,
    text_digest,
)

if TYPE_CHECKING:
    from crosstalk.article_records import ArticleObservation, ArticlePage, ArticleRegion, ReviewItem


class InspectedArticlePage(ArticleRecord):
    """Identify a manually inspected page, including an explicit exclusion for intervening gaps."""

    page_index: int = Field(ge=0)
    page_text_sha256: Digest
    render_sha256: Digest
    excluded_reason: str | None = Field(default=None, min_length=12, max_length=1000)


class FullArticleReadEvidence(ArticleRecord):
    """An explicit reader's coverage attestation; upstream must verify the referenced renders."""

    observation_id: Digest
    reviewer: str = Field(min_length=1, max_length=500)
    opening: Passage
    ending: Passage
    end_basis: str = Field(min_length=20, max_length=2000)
    inspected_pages: tuple[InspectedArticlePage, ...] = Field(min_length=1, max_length=256)
    reviewed_region_orders: tuple[int, ...] = Field(min_length=2, max_length=2048)


class VisualArticleTitle(ArticleRecord):
    """A title transcribed from the selected page render, in raster coordinates."""

    title: str = Field(min_length=1, max_length=1000)
    page_index: int = Field(ge=0)
    render_sha256: Digest
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    bounds_px: tuple[int, int, int, int]

    @model_validator(mode="after")
    def check_bounds(self) -> VisualArticleTitle:
        """Refuse an empty title or a crop outside the exact image extent."""
        x0, y0, x1, y1 = self.bounds_px
        if not self.title.strip() or not (
            0 <= x0 < x1 <= self.width_px and 0 <= y0 < y1 <= self.height_px
        ):
            raise ArticleError("visual title is empty or outside the inspected raster")
        return self


class VisualArticleReadEvidence(FullArticleReadEvidence):
    """A complete reading whose title is in artwork and whose text has exact offsets."""

    title_image: VisualArticleTitle


def _location(passage: Passage) -> tuple[str, str, int, str, str, str]:
    return (
        passage.issue_id,
        passage.pdf_sha256,
        passage.page_index,
        passage.layer,
        passage.artifact_path,
        passage.artifact_sha256,
    )


def _contained(inner: Passage, outer: Passage) -> bool:
    return (
        _location(inner) == _location(outer) and outer.start <= inner.start < inner.end <= outer.end
    )


def _inspect_pages(
    proof: FullArticleReadEvidence,
    regions: tuple[ArticleRegion, ...],
    pages: dict[tuple[str, int, str], ArticlePage],
) -> None:
    owned = {region.page_index for region in regions}
    first, last = min(owned), max(owned)
    if len(proof.inspected_pages) != last - first + 1:
        raise ArticleError("full reading requires inspection of every physical page in its span")
    for index, item in enumerate(proof.inspected_pages, first):
        source = pages.get((proof.opening.issue_id, index, proof.opening.layer))
        if (
            item.page_index != index
            or source is None
            or source.pdf_sha256 != proof.opening.pdf_sha256
            or item.page_text_sha256 != text_digest(source.text)
        ):
            raise ArticleError(
                "full reading page inspection does not bind an exact current source page"
            )
        reason = item.excluded_reason
        if (reason is None) != (index in owned) or (reason is not None and not reason.strip()):
            raise ArticleError(
                "full reading needs an explicit exclusion for each unowned intervening page"
            )


def _check_read(
    proof: FullArticleReadEvidence,
    observation: ArticleObservation,
    review: ReviewItem,
    regions: tuple[ArticleRegion, ...],
    pages: dict[tuple[str, int, str], ArticlePage],
) -> None:
    if (
        regions[-1].role not in {"body", "caption", "reference"}
        or proof.opening not in observation.witnesses
        or not _contained(proof.opening, regions[0].passage)
        or not _contained(proof.ending, regions[-1].passage)
        or proof.ending.end != regions[-1].passage.end
        or not proof.end_basis.strip()
    ):
        raise ArticleError(
            "full reading needs a witnessed title opening and terminal article region"
        )
    if tuple(region.order for region in regions) != proof.reviewed_region_orders or any(
        region.passage.layer != proof.opening.layer or not region.passage.text.strip()
        for region in regions
    ):
        raise ArticleError(
            "full reading requires complete ordered regions from one admitted text layer"
        )
    for passage in (*review.supporting_passages, *review.contrary_passages):
        if not any(_contained(passage, region.passage) for region in regions):
            raise ArticleError("full reading passage lies outside the adjudicated article regions")
    _inspect_pages(proof, regions, pages)
    _check_opening(proof, observation, regions[0])


def _check_opening(
    proof: FullArticleReadEvidence, observation: ArticleObservation, first: ArticleRegion
) -> None:
    if not isinstance(proof, VisualArticleReadEvidence):
        if first.role != "title":
            raise ArticleError("full reading needs a witnessed title opening")
        return
    image = proof.title_image
    if (
        first.role not in {"abstract", "body"}
        or observation.kind != "manual-witness"
        or image.page_index != first.page_index
        or image.title.split() != observation.title_observed.split()
        or not any(
            item.page_index == image.page_index and item.render_sha256 == image.render_sha256
            for item in proof.inspected_pages
        )
    ):
        raise ArticleError("visual title does not bind the exact inspected article opening")


def _disjoint_reads(regions: tuple[ArticleRegion, ...]) -> None:
    by_page: dict[tuple[str, str, int, str, str, str], list[tuple[int, int]]] = defaultdict(list)
    for region in regions:
        passage = region.passage
        by_page[_location(passage)].append((passage.start, passage.end))
    for spans in by_page.values():
        previous_end = -1
        for start, end in sorted(spans):
            if start < previous_end:
                raise ArticleError("full reading regions assign overlapping text offsets")
            previous_end = end


def full_read_passages(
    pages: dict[tuple[str, int, str], ArticlePage],
    observations: dict[str, ArticleObservation],
    grouped: dict[str, list[ArticleRegion]],
    reviews: tuple[ReviewItem, ...],
    proofs: tuple[FullArticleReadEvidence, ...],
) -> tuple[Passage, ...]:
    """Require one coverage proof per declared full reading, with no orphaned attestation."""
    selected = tuple(review for review in reviews if review.full_article_read)
    keys = {(review.observation_id, review.reviewer) for review in selected}
    by_review = {(proof.observation_id, proof.reviewer): proof for proof in proofs}
    if len(keys) != len(selected) or len(by_review) != len(proofs) or by_review.keys() != keys:
        raise ArticleError(
            "every full reading requires one exact reader and boundary evidence record"
        )
    admitted: dict[str, tuple[ArticleRegion, ...]] = {}
    witnesses: list[Passage] = []
    for review in selected:
        identity = review.observation_id
        proof = by_review[identity, review.reviewer]
        if identity not in admitted:
            admitted[identity] = tuple(sorted(grouped[identity], key=lambda r: r.order))
        regions = admitted[identity]
        _check_read(proof, observations[identity], review, regions, pages)
        witnesses.extend((proof.opening, proof.ending))
    _disjoint_reads(tuple(region for regions in admitted.values() for region in regions))
    return tuple(witnesses)
