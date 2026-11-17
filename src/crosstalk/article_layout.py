"""Font-aware contents candidates from a separate, explicitly bound native-layout layer."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from crosstalk.article_records import (
    ArticleError,
    ArticleObservation,
    ArticlePage,
    standalone_folio,
    text_digest,
    witness,
)

if TYPE_CHECKING:
    from crosstalk.study_layout_records import NativeLine, PageLayout

_CONTENTS = re.compile(r"\b(?:table\s+of\s+contents|contents|in\s+this\s+issue)\b", re.IGNORECASE)


def _text(line: NativeLine) -> str:
    return "".join(span.text for span in line.spans).strip()


def _size(line: NativeLine) -> float:
    return max((span.size for span in line.spans if span.text.strip()), default=0.0)


def _title_lines(folio: NativeLine, layout: PageLayout) -> tuple[NativeLine, ...]:
    """Require larger-than-body adjacent text, then extend along the same left alignment."""
    median = layout.median_character_weighted_size_points
    if median is None or median <= 0:
        return ()
    available = tuple(
        line
        for line in layout.lines
        if 1.08 * median <= _size(line) <= 2 * median
        and re.search(r"[A-Za-z]", _text(line))
        and folio.bbox[2] - 2 <= line.bbox[0] <= folio.bbox[2] + 60
        and abs(line.bbox[1] - folio.bbox[1]) <= 20
    )
    if not available:
        return ()
    first = min(available, key=lambda line: abs(line.bbox[1] - folio.bbox[1]))
    lines = [first]
    continuations = sorted(
        (
            line
            for line in layout.lines
            if line.bbox[1] > first.bbox[1]
            and abs(line.bbox[0] - first.bbox[0]) <= 12
            and abs(_size(line) - _size(first)) <= 0.25
        ),
        key=lambda line: line.bbox[1],
    )
    for line in continuations:
        if line.bbox[1] - lines[-1].bbox[1] > 1.7 * _size(first) or len(lines) >= 4:
            break
        lines.append(line)
    return tuple(lines)


def layout_contents(
    page: ArticlePage,
    layout: PageLayout,
    layout_artifact_sha256: str,
) -> tuple[ArticleObservation, ...]:
    """Emit provisional title/folio observations; typography is not genre/boundary validation.

    This conservative heuristic is calibrated on the 2022 contents case and tested on
    synthetic geometry. Its historical precision/recall is unmeasured. Small folios,
    atypical layouts and image-only contents can remain unresolved rather than guessed.
    """
    if (
        page.layer != "native"
        or page.pdf_sha256 != layout.pdf_sha256
        or page.page_index != layout.page_index
    ):
        raise ArticleError("contents layout is not the same native physical source page")
    if not _CONTENTS.search(page.text):
        return ()
    median = layout.median_character_weighted_size_points
    if median is None or median <= 0:
        return ()
    folios = tuple(
        line
        for line in layout.lines
        if re.fullmatch(r"\d{1,3}", _text(line)) and _size(line) >= 1.5 * median
    )
    observations: list[ArticleObservation] = []
    for folio in sorted(folios, key=lambda line: (line.bbox[1], line.bbox[0])):
        lines = _title_lines(folio, layout)
        printed = _text(folio)
        number = standalone_folio(page, printed)
        if not lines or number is None:
            continue
        texts = tuple(_text(line) for line in lines)
        offsets = tuple(page.text.find(text) for text in texts)
        if any(offset < 0 for offset in offsets):
            continue
        passages = tuple(
            witness(page, offset, offset + len(text))
            for text, offset in zip(texts, offsets, strict=True)
        )
        title = " ".join(texts)
        observations.append(
            ArticleObservation(
                observation_id=text_digest(
                    f"layout-contents-v1\0{page.pdf_sha256}\0{page.page_index}\0{printed}\0{title}"
                ),
                issue_id=page.issue_id,
                title_observed=title,
                printed_start_observed=printed,
                kind="contents-entry",
                witnesses=(*passages, number),
                discovery_method="larger-than-median-aligned-folio-title-v1",
                layout_artifact_sha256=layout_artifact_sha256,
                discovery_flags=("heuristic-unvalidated", "native-font-metadata-unvalidated"),
            )
        )
    return tuple(observations)
