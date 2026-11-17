"""Find long exact token repeats on nonadjacent pages of the same PDF."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

_TOKEN = re.compile(r"[^\W_]+")
_SEED = 12
_STRIDE = 8
_MINIMUM_PAGE_DISTANCE = 2


@dataclass(frozen=True, slots=True)
class RepeatedPassage:
    """Longest exact repeat for one pair of physical pages."""

    first_page: int
    second_page: int
    first_token: int
    second_token: int
    words: int
    passage_sha256: str


def tokens(text: str) -> tuple[str, ...]:
    """Normalize Unicode, case, and soft line-break hyphens."""
    return tuple(_TOKEN.findall(unicodedata.normalize("NFKC", text).casefold().replace("\xad", "")))


def _extent(
    first: tuple[str, ...], second: tuple[str, ...], x: int, y: int
) -> tuple[int, int, int]:
    left = 0
    while x > left and y > left and first[x - left - 1] == second[y - left - 1]:
        left += 1
    right = _SEED
    while (
        x + right < len(first) and y + right < len(second) and first[x + right] == second[y + right]
    ):
        right += 1
    return x - left, y - left, left + right


def repeated_passages(
    pages: tuple[tuple[str, ...], ...], *, minimum_words: int = 32
) -> tuple[RepeatedPassage, ...]:
    """Return one deterministic maximum per pair; scan every stride phase via full queries."""
    if minimum_words < _SEED + _STRIDE - 1:
        raise ValueError("minimum is shorter than guaranteed seeded detection")
    index: defaultdict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for page, words in enumerate(pages):
        for start in range(0, len(words) - _SEED + 1, _STRIDE):
            index[words[start : start + _SEED]].append((page, start))
    output: dict[tuple[int, int], RepeatedPassage] = {}
    covered: dict[tuple[int, int, int], int] = {}
    for second_page, second in enumerate(pages):
        for second_token in range(len(second) - _SEED + 1):
            key = second[second_token : second_token + _SEED]
            for first_page, first_token in index.get(key, ()):
                if second_page - first_page < _MINIMUM_PAGE_DISTANCE:
                    continue
                alignment = (first_page, second_page, first_token - second_token)
                if covered.get(alignment, 0) > second_token:
                    continue
                first = pages[first_page]
                x, y, length = _extent(first, second, first_token, second_token)
                covered[alignment] = y + length - _SEED + 1
                pair = (first_page, second_page)
                old = output.get(pair)
                current = (-old.words, old.first_token, old.second_token) if old else (0, 0, 0)
                if length < minimum_words or current <= (-length, x, y):
                    continue
                signature = hashlib.sha256(" ".join(first[x : x + length]).encode()).hexdigest()
                output[pair] = RepeatedPassage(first_page, second_page, x, y, length, signature)
    return tuple(output[key] for key in sorted(output))
