"""Bounded lexical contexts preserve full counts and prove original offsets independently."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.lexicon import TOKEN
from crosstalk.study_concordance_records import ConcordanceRun, KwicExample, TermConcordance
from crosstalk.study_language import implementation_digest as tokenization_identity
from crosstalk.study_language import tokenize
from crosstalk.study_language_records import StudyError
from crosstalk.study_unit_sources import source_units, unit_frame

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crosstalk.study_concordance_records import ConcordanceSettings
    from crosstalk.study_language_records import Layer, SourceTextUnit

METHOD_FILES: Final = (
    "study_concordance.py",
    "study_concordance_records.py",
    "study_language.py",
    "study_language_records.py",
    "study_unit_sources.py",
    "lexicon.py",
)


def implementation_digest() -> str:
    """Frame every local implementation/tokenization dependency for this derived method."""
    directory = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest()) for name in METHOD_FILES
    )
    return hashlib.sha256(
        json.dumps((members, tokenization_identity()), separators=(",", ":")).encode()
    ).hexdigest()


def _example(
    unit: SourceTextUnit, position: int, selected: tuple[tuple[str, ...], int]
) -> KwicExample:
    tokens, width = selected
    start, end = max(0, position - width), min(len(tokens), position + width + 1)
    matches = tuple(TOKEN.finditer(unit.text))
    mapped = tuple(tokenize(match.group()) for match in matches)
    aligned = all(len(row) == 1 for row in mapped) and tuple(row[0] for row in mapped) == tokens
    raw_start = matches[start].start() if aligned else None
    raw_end = matches[end - 1].end() if aligned else None
    excerpt = (
        unit.text[raw_start:raw_end] if raw_start is not None and raw_end is not None else None
    )
    return KwicExample(
        term=tokens[position],
        layer=unit.layer,
        unit_id=unit.unit_id,
        issue_id=unit.issue_id,
        pdf_sha256=unit.pdf_sha256,
        page_index=unit.page_index,
        layer_artifact_sha256=unit.layer_artifact_sha256,
        unit_text_sha256=unit.text_sha256,
        region_id=unit.region_id,
        article_id=unit.article_id,
        token_index=position,
        normalized_left=tokens[start:position],
        normalized_match=tokens[position],
        normalized_right=tokens[position + 1 : end],
        original_excerpt=excerpt,
        original_start=raw_start,
        original_end=raw_end,
        excerpt_status="exact-original-text-excerpt" if aligned else "normalized-context-only",
        quality=unit.quality,
    )


@dataclass(frozen=True, slots=True)
class ConcordanceTally:
    """One complete count pass owns mutable local buffers before bounded example selection."""

    occurrences: Counter[tuple[Layer, str]]
    matched_units: dict[tuple[Layer, str], set[str]]
    examples: dict[tuple[Layer, str], dict[str, KwicExample]]
    supplied_units: Counter[Layer]
    supplied_tokens: Counter[Layer]
    positive_issues: dict[Layer, set[str]]


def _tally(ordered: tuple[SourceTextUnit, ...], settings: ConcordanceSettings) -> ConcordanceTally:
    """Count all observations before applying the display cap; preserve first-hit computation."""
    occurrences: Counter[tuple[Layer, str]] = Counter()
    matched_units: dict[tuple[Layer, str], set[str]] = defaultdict(set)
    examples: dict[tuple[Layer, str], dict[str, KwicExample]] = defaultdict(dict)
    supplied_units: Counter[Layer] = Counter()
    supplied_tokens: Counter[Layer] = Counter()
    positive_issues: dict[Layer, set[str]] = defaultdict(set)
    targets = set(settings.targets)
    for row in ordered:
        tokens = tokenize(row.text)
        supplied_units[row.layer] += 1
        supplied_tokens[row.layer] += len(tokens)
        if sum(supplied_tokens.values()) > settings.maximum_tokens:
            raise StudyError("concordance token capacity exceeded")
        if tokens:
            positive_issues[row.layer].add(row.issue_id)
        for index, token in enumerate(tokens):
            if token not in targets:
                continue
            key = row.layer, token
            occurrences[key] += 1
            matched_units[key].add(row.unit_id)
            if row.issue_id not in examples[key]:
                examples[key][row.issue_id] = _example(
                    row, index, (tokens, settings.context_tokens)
                )
    return ConcordanceTally(
        occurrences, matched_units, examples, supplied_units, supplied_tokens, positive_issues
    )


def concordance(units: Iterable[SourceTextUnit], settings: ConcordanceSettings) -> ConcordanceRun:
    """Count every target before choosing at most one first-hit candidate per source issue."""
    if any(tokenize(term) != (term,) for term in settings.targets):
        raise StudyError("concordance targets must be single existing-normalization tokens")
    ordered = source_units(units, settings.maximum_units)
    method = implementation_digest()
    counted = _tally(ordered, settings)
    results: list[TermConcordance] = []
    for layer in sorted(counted.supplied_units):
        for term in settings.targets:
            peers = counted.examples[(layer, term)]
            chosen = sorted(
                peers,
                key=lambda issue: hashlib.sha256(
                    json.dumps((settings.seed, layer, term, issue), separators=(",", ":")).encode()
                ).hexdigest(),
            )[: settings.examples_per_term_layer]
            results.append(
                TermConcordance(
                    term=term,
                    layer=layer,
                    occurrences=counted.occurrences[(layer, term)],
                    matching_units=len(counted.matched_units[(layer, term)]),
                    matching_issues=len(peers),
                    supplied_units=counted.supplied_units[layer],
                    positive_token_issues=len(counted.positive_issues[layer]),
                    supplied_tokens=counted.supplied_tokens[layer],
                    examples=tuple(peers[issue] for issue in chosen),
                )
            )
    if implementation_digest() != method:
        raise StudyError("concordance method changed during retrieval")
    return ConcordanceRun(
        implementation_sha256=method,
        unit_frame_sha256=unit_frame(ordered),
        settings=settings,
        units=len(ordered),
        terms=tuple(results),
    )
