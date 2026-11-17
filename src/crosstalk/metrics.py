"""Descriptive lexical and embedded-image measurements."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from crosstalk.analysis_records import CategoryHit, TermCount, TextMetrics, VisualMetrics
from crosstalk.lexicon import CATEGORIES, HEDGES, MODALS, STOPWORDS, TOKEN
from crosstalk.visual_asset import measure_recorded_asset

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.records import PageRecord


def text_metrics(text: str) -> TextMetrics:
    """Count Unicode alphabetic tokens and declared English lexical proxies."""
    counts = Counter(match.group().casefold() for match in TOKEN.finditer(text))
    tokens = counts.total()
    hedges = sum(counts[term] for term in HEDGES)
    modals = sum(counts[term] for term in MODALS)
    ranked = sorted(
        (
            (term, count)
            for term, count in counts.items()
            if term not in STOPWORDS and len(term) > 2
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return TextMetrics(
        tokens=tokens,
        types=len(counts),
        type_token_ratio=len(counts) / tokens if tokens else None,
        hedge_tokens=hedges,
        modal_tokens=modals,
        hedge_per_1000=hedges * 1000 / tokens if tokens else None,
        modal_per_1000=modals * 1000 / tokens if tokens else None,
        terms=tuple(TermCount(term=term, count=count) for term, count in ranked[:100]),
    )


def categorize(pages: tuple[PageRecord, ...]) -> tuple[CategoryHit, ...]:
    """Return multi-label keyword matches and their physical page indexes."""
    labels: list[CategoryHit] = []
    for category, terms in CATEGORIES.items():
        evidence: set[str] = set()
        indexes: set[int] = set()
        for page in pages:
            matches = {
                term
                for term in terms
                if re.search(r"\b" + re.escape(term) + r"\b", page.text, re.IGNORECASE)
            }
            if matches:
                evidence.update(matches)
                indexes.add(page.page_index)
        if evidence:
            labels.append(
                CategoryHit(
                    category=category,
                    evidence_terms=tuple(sorted(evidence)),
                    page_indexes=tuple(sorted(indexes)),
                )
            )
    return tuple(labels)


def image_metrics(root: Path, pages: tuple[PageRecord, ...]) -> tuple[VisualMetrics, ...]:
    """Measure each distinct saved image; preserve all page occurrences."""
    digests = sorted(
        {
            image.sha256
            for page in pages
            for image in page.images
            if image.path is not None and image.sha256 is not None
        }
    )
    return tuple(
        measure_recorded_asset(
            root,
            tuple(
                (page, image) for page in pages for image in page.images if image.sha256 == digest
            ),
        )
        for digest in digests
    )
