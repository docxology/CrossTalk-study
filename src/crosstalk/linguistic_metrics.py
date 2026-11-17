"""Deterministic page-bounded lexical diagnostics without semantic inference."""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Literal

from crosstalk.lexicon import TOKEN
from crosstalk.linguistic_records import (
    BoilerplateCandidate,
    LinguisticMeasures,
    NGramFrequency,
    NGramProfile,
    NormalizedFrequency,
    PageDistribution,
    WindowDiversity,
)

if TYPE_CHECKING:
    from crosstalk.linguistic_records import LinguisticSettings
    from crosstalk.records import PageRecord


def normalized_tokens(text: str) -> tuple[str, ...]:
    """Normalize a derivative without changing stored original text or dropping stopwords."""
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return tuple(match.group() for match in TOKEN.finditer(normalized))


def fixed_window_diversity(tokens: tuple[str, ...], size: int) -> WindowDiversity:
    """Measure complete, disjoint windows and disclose every discarded tail token."""
    if size < 2:
        message = "window size must be at least two tokens"
        raise ValueError(message)
    complete = len(tokens) // size
    ratios = tuple(
        len(set(tokens[start : start + size])) / size for start in range(0, complete * size, size)
    )
    return WindowDiversity(
        window_size=size,
        complete_windows=complete,
        tokens_used=complete * size,
        tokens_discarded=len(tokens) - complete * size,
        mean_type_token_ratio=sum(ratios) / complete if complete else None,
        status="available" if complete else "insufficient-data",
    )


def _ngrams(
    token_pages: tuple[tuple[str, ...], ...], size: Literal[2, 3], limit: int
) -> NGramProfile:
    """Count each adjacency once, with no joins across physical page boundaries."""
    counts: Counter[tuple[str, ...]] = Counter()
    locations: dict[tuple[str, ...], set[int]] = {}
    opportunities = 0
    for index, tokens in enumerate(token_pages):
        eligible = max(0, len(tokens) - size + 1)
        opportunities += eligible
        for start in range(eligible):
            gram = tokens[start : start + size]
            counts[gram] += 1
            locations.setdefault(gram, set()).add(index)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return NGramProfile(
        size=size,
        opportunities=opportunities,
        distinct_ngrams=len(counts),
        frequencies=tuple(
            NGramFrequency(
                tokens=gram,
                count=count,
                per_1000_opportunities=1000 * count / opportunities,
                page_indexes=tuple(sorted(locations[gram])),
            )
            for gram, count in ranked
        ),
    )


def _boilerplate(
    pages: tuple[PageRecord, ...], settings: LinguisticSettings
) -> tuple[int, tuple[BoilerplateCandidate, ...]]:
    """Screen exact normalized repeated lines; repetition alone never proves boilerplate."""
    locations: dict[str, set[int]] = {}
    for page in pages:
        for line in page.text.splitlines():
            tokens = normalized_tokens(line)
            if settings.boilerplate_min_tokens <= len(tokens) <= settings.boilerplate_max_tokens:
                locations.setdefault(" ".join(tokens), set()).add(page.page_index)
    candidates = (
        (line, indexes)
        for line, indexes in locations.items()
        if len(indexes) >= settings.boilerplate_min_pages
        and len(indexes) / len(pages) >= settings.boilerplate_min_fraction
    )
    ranked = sorted(candidates, key=lambda item: (-len(item[1]), item[0]))
    return len(ranked), tuple(
        BoilerplateCandidate(
            normalized_line=line,
            page_indexes=tuple(sorted(indexes)),
            page_fraction=len(indexes) / len(pages),
        )
        for line, indexes in ranked[: settings.top_boilerplate]
    )


def measure_pages(
    pages: tuple[PageRecord, ...], settings: LinguisticSettings
) -> LinguisticMeasures:
    """Compute frequencies, page distributions and equal-length lexical measurements."""
    if any(page.page_index != index for index, page in enumerate(pages)):
        message = "pages must have unique consecutive zero-based indexes"
        raise ValueError(message)
    token_pages = tuple(normalized_tokens(page.text) for page in pages)
    counts = Counter(token for tokens in token_pages for token in tokens)
    total = counts.total()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: settings.top_terms]
    distributions = tuple(
        PageDistribution(
            page_index=page.page_index,
            page_label=page.page_label,
            tokens=len(tokens),
            types=len(set(tokens)),
            fraction_of_issue_tokens=len(tokens) / total if total else None,
            quality=page.quality,
            diversity=fixed_window_diversity(tokens, settings.window_size),
        )
        for page, tokens in zip(pages, token_pages, strict=True)
    )
    windows = sum(page.diversity.complete_windows for page in distributions)
    weighted = sum(
        (page.diversity.mean_type_token_ratio or 0) * page.diversity.complete_windows
        for page in distributions
    )
    boilerplate_count, boilerplate = _boilerplate(pages, settings)
    return LinguisticMeasures(
        tokens=total,
        types=len(counts),
        frequencies=tuple(
            NormalizedFrequency(token=token, count=count, per_1000_tokens=1000 * count / total)
            for token, count in ranked
        ),
        bigrams=_ngrams(token_pages, 2, settings.top_ngrams),
        trigrams=_ngrams(token_pages, 3, settings.top_ngrams),
        pages=distributions,
        complete_windows=windows,
        mean_window_type_token_ratio=weighted / windows if windows else None,
        boilerplate_candidates_total=boilerplate_count,
        boilerplate_candidates=boilerplate,
    )
