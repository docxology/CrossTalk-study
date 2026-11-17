"""Measure how literal topic incidence changes under exact-repeat deletion."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crosstalk.study_repetition import RepeatedPassage

THRESHOLDS = (32, 64, 96)
type PhraseIndex = Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]]


def phrase_index(lexicons: Mapping[str, list[tuple[str, ...]]]) -> PhraseIndex:
    """Build an index by first word without changing supplied phrase identity."""
    index: defaultdict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    for family, phrases in lexicons.items():
        for phrase in phrases:
            if not phrase:
                raise ValueError("empty phrase")
            index[phrase[0]].append((family, phrase))
    return {word: tuple(rows) for word, rows in index.items()}


def masks(candidates: tuple[RepeatedPassage, ...], threshold: int) -> dict[int, set[int]]:
    """Union the token positions on later pages of eligible repeat pairs."""
    removed: defaultdict[int, set[int]] = defaultdict(set)
    for row in candidates:
        if row.words >= threshold:
            start = row.second_token
            removed[row.second_page].update(range(start, start + row.words))
    return dict(removed)


def hit_families(
    words: tuple[str, ...],
    phrases: PhraseIndex,
    removed: set[int] | None = None,
) -> set[str]:
    """Find contiguous phrase hits without spanning any omitted token."""
    hits: set[str] = set()
    omitted = removed or set()
    for start, word in enumerate(words):
        for family, phrase in phrases.get(word, ()):
            end = start + len(phrase)
            if words[start:end] == phrase and omitted.isdisjoint(range(start, end)):
                hits.add(family)
    return hits
