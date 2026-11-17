"""Extractive article candidate evidence cards without unearned semantic labels."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from crosstalk.article_records import (
    ArticleError,
    ArticleObservation,
    ArticlePage,
    ArticleRecord,
    Passage,
    witness,
)
from crosstalk.article_validation import validate_evidence

_CUES = {
    "objective": r"\b(?:objective|purpose|we aim|this (?:paper|article|work)|propos\w*)\b",
    "method": r"\b(?:method\w*|experiment\w*|case stud\w*|survey\w*|interview\w*|simulat\w*)\b",
    "evaluation": r"\b(?:evaluat\w*|measur\w*|sample\w*|dataset\w*|metric\w*|compar\w*)\b",
    "finding": r"\b(?:result\w*|found|findings|show\w*|conclu\w*)\b",
    "qualification": r"\b(?:limit\w*|however|caution\w*|uncertain\w*|future work|threat\w*)\b",
    "recommendation": r"\b(?:recommend\w*|should|suggest\w*|must|guideline\w*)\b",
}


class CuePassage(ArticleRecord):
    """A lexical cue is a search aid and may have an unrelated meaning in context."""

    cue: str
    passage: Passage


class EvidenceCard(ArticleRecord):
    """Auditably extracted candidate context; no review or boundary certification."""

    observation_id: str
    issue_id: str
    title_observed: str
    extraction_status: str
    source_layer: Literal["native", "ocr"] | None = None
    physical_page_indices: tuple[int, ...]
    passages: tuple[CuePassage, ...]
    omitted_matching_sentences: int = Field(ge=0)
    omission_count_unit: Literal["cue-sentence pairs"] = "cue-sentence pairs"
    candidate_window_rule: str = (
        "Single corroborated start up to next unique corroborated start in same issue/layer; "
        + "an extraction window only, not adjudicated article ownership or reading order."
    )
    semantic_review_complete: bool = False
    article_boundaries_verified: bool = False


def _admit_sources(
    item: ArticleObservation,
    observations: tuple[ArticleObservation, ...],
    pages: tuple[ArticlePage, ...],
) -> None:
    """Direct API calls require the same current frame and witnesses as inventory calls."""
    same_id = tuple(row for row in observations if row.observation_id == item.observation_id)
    if any(row != item for row in same_id):
        raise ArticleError("candidate-window item conflicts with its supplied observation")
    selected = observations if same_id else (*observations, item)
    _ = validate_evidence(pages, selected)


def evidence_card(
    item: ArticleObservation,
    issue_observations: tuple[ArticleObservation, ...],
    pages: tuple[ArticlePage, ...],
    *,
    maximum_per_cue: int = 3,
) -> EvidenceCard:
    """Extract bounded, verbatim sentence contexts for every identified lexical cue."""
    if not 1 <= maximum_per_cue <= 10:
        raise ArticleError("extractive cue capacity must be between one and ten")
    if any(o.issue_id != item.issue_id for o in issue_observations):
        raise ArticleError("candidate-window observations cross issue identity")
    _admit_sources(item, issue_observations, pages)
    starts = item.target_page_indices
    if (
        item.boundary_status != "start-corroborated"
        or len(starts) != 1
        or item.target_layer is None
    ):
        return EvidenceCard(
            observation_id=item.observation_id,
            issue_id=item.issue_id,
            title_observed=item.title_observed,
            extraction_status="start-unresolved",
            physical_page_indices=(),
            passages=(),
            omitted_matching_sentences=0,
        )
    layer = item.target_layer
    next_starts = [
        o.target_page_indices[0]
        for o in issue_observations
        if o.observation_id != item.observation_id
        and o.boundary_status == "start-corroborated"
        and len(o.target_page_indices) == 1
        and o.target_layer == layer
        and o.target_page_indices[0] > starts[0]
    ]
    end = min(next_starts, default=None)
    selected = tuple(
        sorted(
            (
                p
                for p in pages
                if p.issue_id == item.issue_id
                and p.layer == layer
                and starts[0] <= p.page_index
                and (end is None or p.page_index < end)
            ),
            key=lambda page: page.page_index,
        )
    )
    if not selected or not any(page.page_index == starts[0] for page in selected):
        return EvidenceCard(
            observation_id=item.observation_id,
            issue_id=item.issue_id,
            title_observed=item.title_observed,
            extraction_status="target-page-unavailable",
            source_layer=layer,
            physical_page_indices=(),
            passages=(),
            omitted_matching_sentences=0,
        )
    matches: list[CuePassage] = []
    counts = dict.fromkeys(_CUES, 0)
    omitted = 0
    for page in selected:
        for sentence in re.finditer(r"[^.!?\n](?:[^.!?]|\.(?=\d)){39,1200}[.!?]", page.text):
            sample = sentence.group()
            for cue, expression in _CUES.items():
                if re.search(expression, sample, re.IGNORECASE):
                    if counts[cue] < maximum_per_cue:
                        matches.append(
                            CuePassage(
                                cue=cue,
                                passage=witness(page, sentence.start(), sentence.end()),
                            )
                        )
                        counts[cue] += 1
                    else:
                        omitted += 1
    return EvidenceCard(
        observation_id=item.observation_id,
        issue_id=item.issue_id,
        title_observed=item.title_observed,
        extraction_status="candidate-window-extracted",
        source_layer=layer,
        physical_page_indices=tuple(p.page_index for p in selected),
        passages=tuple(matches),
        omitted_matching_sentences=omitted,
    )
