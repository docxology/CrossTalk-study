"""Compose explicit text and geometry discovery without silently merging article variants."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.article_candidates import contents_observations, corroborate_start
from crosstalk.article_evidence import evidence_card
from crosstalk.article_inventory_records import IssueDiscovery
from crosstalk.article_layout import layout_contents
from crosstalk.article_records import ArticleError
from crosstalk.article_validation import validate_evidence, validate_passage

if TYPE_CHECKING:
    from crosstalk.article_inventory_records import LayoutEvidence
    from crosstalk.article_records import ArticleObservation, ArticlePage


def _layout_candidates(
    pages: tuple[ArticlePage, ...],
    layouts: tuple[LayoutEvidence, ...],
) -> tuple[ArticleObservation, ...]:
    """Require each supplied layout to select the same independently supplied native page."""
    native = {page.page_index: page for page in pages if page.layer == "native"}
    if len({row.page.page_index for row in layouts}) != len(layouts):
        raise ArticleError("article inventory layout pages are not unique")
    observations: list[ArticleObservation] = []
    for layout in sorted(layouts, key=lambda row: row.page.page_index):
        if layout.page.page_index not in native:
            raise ArticleError("article inventory layout has no corresponding native page")
        observations.extend(
            layout_contents(
                native[layout.page.page_index],
                layout.page,
                layout.artifact_sha256,
            )
        )
    return tuple(observations)


def discover_issue(
    pages: tuple[ArticlePage, ...],
    layouts: tuple[LayoutEvidence, ...] = (),
) -> IssueDiscovery:
    """Produce replay-stable candidates and source-checked cues for one explicit issue frame."""
    if not pages or len(pages) > 1000:
        raise ArticleError("article issue discovery requires one to 1000 layer pages")
    if len({page.issue_id for page in pages}) != 1:
        raise ArticleError("article issue discovery cannot combine different issue identities")
    _ = validate_evidence(pages, ())
    source = tuple(sorted(pages, key=lambda page: (page.page_index, page.layer)))
    listed = tuple(item for page in source for item in contents_observations(page))
    discovered = (*listed, *_layout_candidates(source, layouts))
    discovery_pages = tuple(sorted({item.witnesses[0].page_index for item in discovered}))
    observations = tuple(
        corroborate_start(item, source, excluded_discovery_pages=discovery_pages)
        for item in discovered
    )
    checked = validate_evidence(source, observations)
    cards = tuple(evidence_card(item, observations, source) for item in observations)
    lookup = {(page.page_index, page.layer): page for page in source}
    for card in cards:
        for cue in card.passages:
            validate_passage(cue.passage, lookup[(cue.passage.page_index, cue.passage.layer)])
    starts = tuple(item for item in observations if item.boundary_status == "start-corroborated")
    return IssueDiscovery(
        issue_id=source[0].issue_id,
        pdf_sha256=source[0].pdf_sha256,
        physical_pages=len({page.page_index for page in source}),
        native_pages=sum(page.layer == "native" for page in source),
        ocr_pages=sum(page.layer == "ocr" for page in source),
        layout_pages=len(layouts),
        status="provisional-observations" if observations else "no-entry-detected-unresolved",
        observations=observations,
        cards=cards,
        corroborated_observations=len(starts),
        unique_physical_starts=len({item.target_page_indices[0] for item in starts}),
        unique_layer_starts=len(
            {(item.target_page_indices[0], item.target_layer) for item in starts}
        ),
        exact_passages_checked=checked["exact_passages_checked"]
        + sum(len(c.passages) for c in cards),
    )
