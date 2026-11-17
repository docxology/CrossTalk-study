"""Independent source checks and region accounting for article evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from crosstalk.article_full_read import VisualArticleReadEvidence, full_read_passages
from crosstalk.article_records import (
    ArticleError,
    ArticleObservation,
    ArticlePage,
    ArticleRegion,
    Passage,
    ReviewItem,
    text_digest,
)

if TYPE_CHECKING:
    from crosstalk.article_full_read import FullArticleReadEvidence


def validate_passage(passage: Passage, page: ArticlePage) -> None:
    """Reject modified text, wrong physical page, layer or stale source binding."""
    if (
        passage.issue_id != page.issue_id
        or passage.pdf_sha256 != page.pdf_sha256
        or passage.page_index != page.page_index
        or passage.layer != page.layer
        or passage.artifact_path != page.artifact_path
        or passage.artifact_sha256 != page.artifact_sha256
        or passage.page_text_sha256 != text_digest(page.text)
        or page.text[passage.start : passage.end] != passage.text
        or passage.end > len(page.text)
    ):
        raise ArticleError("article passage does not match the exact current source page")


def _page_lookup(pages: tuple[ArticlePage, ...]) -> dict[tuple[str, int, str], ArticlePage]:
    """Keep issue/PDF aliases and duplicate layer observations out of the source frame."""
    lookup: dict[tuple[str, int, str], ArticlePage] = {
        (p.issue_id, p.page_index, p.layer): p for p in pages
    }
    if len(lookup) != len(pages):
        raise ArticleError("article validation received duplicate page identities")
    source_ids: dict[str, str] = {}
    pdf_ids: dict[str, str] = {}
    for page in pages:
        if source_ids.setdefault(page.issue_id, page.pdf_sha256) != page.pdf_sha256:
            raise ArticleError("article issue identity refers to multiple physical PDFs")
        if pdf_ids.setdefault(page.pdf_sha256, page.issue_id) != page.issue_id:
            raise ArticleError("article physical PDF aliases require reconciliation")
    return lookup


def _review_passages(
    reviews: tuple[ReviewItem, ...],
    candidates: dict[str, ArticleObservation],
    grouped: dict[str, list[ArticleRegion]],
    visual_openings: frozenset[str],
) -> list[Passage]:
    """Require explicit source ownership and body-region support for full-reading claims."""
    passages: list[Passage] = []
    for review in reviews:
        if review.observation_id not in candidates:
            raise ArticleError("article review has no observed source title")
        candidate = candidates[review.observation_id]
        if any(
            p.issue_id != candidate.issue_id
            for p in (*review.supporting_passages, *review.contrary_passages)
        ):
            raise ArticleError("article review passage crosses the observed issue identity")
        if review.full_article_read and (
            review.observation_id not in grouped
            or not _has_opening_and_body(
                grouped[review.observation_id],
                has_visual_title=review.observation_id in visual_openings,
            )
            or candidates[review.observation_id].boundary_status != "regions-adjudicated"
        ):
            raise ArticleError("full article review requires explicit adjudicated body regions")
        passages.extend((*review.supporting_passages, *review.contrary_passages))
    return passages


def _has_opening_and_body(regions: list[ArticleRegion], *, has_visual_title: bool) -> bool:
    roles = {region.role for region in regions}
    return "body" in roles and ("title" in roles or has_visual_title)


def validate_evidence(
    pages: tuple[ArticlePage, ...],
    observations: tuple[ArticleObservation, ...],
    regions: tuple[ArticleRegion, ...] = (),
    reviews: tuple[ReviewItem, ...] = (),
    *,
    full_reads: tuple[FullArticleReadEvidence, ...] = (),
) -> dict[str, int]:
    """Recheck every locator and distinguish candidate discovery from full review.

    Geometry/order checks establish internal consistency only, never extraction accuracy.
    Article regions may be nonconsecutive and may share pages; overlapping boxes require
    separate source interpretation and are rejected here to keep published boundaries clear.
    """
    lookup = _page_lookup(pages)
    candidates = {item.observation_id: item for item in observations}
    if len(candidates) != len(observations):
        raise ArticleError("article observation IDs are not unique")
    passages: list[Passage] = []
    for item in observations:
        if any(p.issue_id != item.issue_id for p in item.witnesses):
            raise ArticleError("article witness crosses issue identity")
        passages.extend(item.witnesses)
    grouped = _region_groups(regions, candidates)
    visual_openings = frozenset(
        proof.observation_id for proof in full_reads if isinstance(proof, VisualArticleReadEvidence)
    )
    passages.extend(region.passage for region in regions)
    passages.extend(_review_passages(reviews, candidates, grouped, visual_openings))
    passages.extend(full_read_passages(lookup, candidates, grouped, reviews, full_reads))
    for passage in passages:
        key = (passage.issue_id, passage.page_index, passage.layer)
        if key not in lookup:
            raise ArticleError("article passage refers to an unavailable current page")
        validate_passage(passage, lookup[key])
    return {
        "input_physical_pages": len({(p.issue_id, p.page_index) for p in pages}),
        "native_pages": sum(p.layer == "native" for p in pages),
        "ocr_pages": sum(p.layer == "ocr" for p in pages),
        "observations": len(observations),
        "start_corroborated": sum(o.boundary_status == "start-corroborated" for o in observations),
        "supplied_region_groups": len(grouped),
        "regions_adjudicated": sum(
            candidates[key].boundary_status == "regions-adjudicated"
            and _has_opening_and_body(members, has_visual_title=key in visual_openings)
            for key, members in grouped.items()
        ),
        "review_items": len(reviews),
        "full_article_reviews": sum(r.full_article_read for r in reviews),
        "human_reviewed": sum(r.status == "independently-human-reviewed" for r in reviews),
        "exact_passages_checked": len(passages),
    }


def _region_groups(
    regions: tuple[ArticleRegion, ...],
    candidates: dict[str, ArticleObservation],
) -> dict[str, list[ArticleRegion]]:
    """Check candidate ownership and explicit order without inventing geometric accuracy."""
    grouped: dict[str, list[ArticleRegion]] = defaultdict(list)
    for region in regions:
        if region.observation_id not in candidates:
            raise ArticleError("article region has no observed title")
        if region.passage.issue_id != candidates[region.observation_id].issue_id:
            raise ArticleError("article region crosses the observed issue identity")
        if region.page_index != region.passage.page_index:
            raise ArticleError("article region page disagrees with its passage")
        x0, y0, x1, y1 = region.bbox
        if x1 <= x0 or y1 <= y0:
            raise ArticleError("article region has invalid geometry")
        grouped[region.observation_id].append(region)
    _check_region_order(grouped)
    return grouped


def _check_region_order(grouped: dict[str, list[ArticleRegion]]) -> None:
    """Reject duplicate sequence indices and intersecting regions within each article."""
    for members in grouped.values():
        if sorted(r.order for r in members) != list(range(len(members))):
            raise ArticleError("article regions need one contiguous explicit order")
        for index, a in enumerate(members):
            for b in members[index + 1 :]:
                if a.page_index == b.page_index and (
                    max(a.bbox[0], b.bbox[0]) < min(a.bbox[2], b.bbox[2])
                    and max(a.bbox[1], b.bbox[1]) < min(a.bbox[3], b.bbox[3])
                ):
                    raise ArticleError("article regions overlap on a shared physical page")
