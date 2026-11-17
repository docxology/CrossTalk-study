"""Layer-separated full-frequency and dispersion measurements on supplied source units."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import unicodedata
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.lexicon import TOKEN
from crosstalk.study_language_records import (
    IssueCounts,
    LanguageRun,
    LanguageSettings,
    LayerMeasure,
    PairProfile,
    StudyError,
    TermCount,
    TermProfile,
    UnitMeasure,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crosstalk.study_language_records import Layer, SourceTextUnit

IMPLEMENTATION_FILES: Final = (
    "study_language_records.py",
    "study_language.py",
    "study_statistics.py",
    "study_layout_records.py",
    "study_layout.py",
    "study_figures.py",
    "study_svg.py",
    "lexicon.py",
)


def implementation_digest() -> str:
    """Frame exact method bytes and the Unicode/Python token-normalization runtime."""
    directory = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest())
        for name in IMPLEMENTATION_FILES
    )
    payload = (members, sys.version, unicodedata.unidata_version)
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def tokenize(text: str) -> tuple[str, ...]:
    """Use the existing word regex and normalization without changing original text."""
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return tuple(match.group() for match in TOKEN.finditer(normalized))


def _unit(row: SourceTextUnit, tokens: tuple[str, ...], size: int) -> UnitMeasure:
    windows = len(tokens) // size
    ratios = [
        len(set(tokens[start : start + size])) / size for start in range(0, windows * size, size)
    ]
    return UnitMeasure(
        unit_id=row.unit_id,
        issue_id=row.issue_id,
        article_id=row.article_id,
        tokens=len(tokens),
        types=len(set(tokens)),
        complete_windows=windows,
        discarded_tokens=len(tokens) - windows * size,
        mean_window_ttr=sum(ratios) / windows if windows else None,
    )


def _sources(rows: tuple[SourceTextUnit, ...]) -> None:
    identities = {(row.layer, row.unit_id) for row in rows}
    if len(identities) != len(rows):
        raise StudyError("duplicate unit ID within one text layer")
    pages: dict[tuple[str, str, int], list[SourceTextUnit]] = defaultdict(list)
    issue_pdf: dict[str, str] = {}
    pdf_issue: dict[str, str] = {}
    for row in rows:
        if issue_pdf.setdefault(row.issue_id, row.pdf_sha256) != row.pdf_sha256:
            raise StudyError("one issue ID refers to multiple physical PDFs")
        if pdf_issue.setdefault(row.pdf_sha256, row.issue_id) != row.issue_id:
            raise StudyError("physical PDF aliases must be reconciled before measurement")
        pages[(row.layer, row.pdf_sha256, row.page_index)].append(row)
    for peers in pages.values():
        regions = {row.region_id for row in peers}
        if len(peers) > 1 and (None in regions or len(regions) != len(peers)):
            raise StudyError("whole-page/region duplication or repeated source region")


def _frequencies(issues: tuple[IssueCounts, ...], limit: int) -> tuple[TermProfile, ...]:
    eligible = tuple(row for row in issues if row.tokens)
    counts = Counter[str]()
    tables = tuple((row.tokens, {term.term: term.count for term in row.terms}) for row in eligible)
    for _, table in tables:
        counts.update(table)
    total = sum(row.tokens for row in eligible)
    return tuple(
        TermProfile(
            term=term,
            count=count,
            per_1000_tokens=1000 * count / total,
            observed_issues=sum(term in table for _, table in tables),
            eligible_issues=len(eligible),
            issue_prevalence=sum(term in table for _, table in tables) / len(eligible),
            deviation_from_token_share=0.5
            * sum(abs(table.get(term, 0) / count - tokens / total) for tokens, table in tables),
        )
        for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    )


def _measure(
    rows: tuple[SourceTextUnit, ...], layer: Layer, settings: LanguageSettings
) -> LayerMeasure:
    units: list[UnitMeasure] = []
    issue_terms: dict[str, Counter[str]] = defaultdict(Counter)
    issue_units: Counter[str] = Counter()
    pdfs: dict[str, str] = {}
    pairs: Counter[tuple[str, str]] = Counter()
    left: Counter[str] = Counter()
    right: Counter[str] = Counter()
    tokens_total = 0
    vocabulary: set[str] = set()
    for row in rows:
        tokens = tokenize(row.text)
        tokens_total += len(tokens)
        vocabulary.update(tokens)
        if tokens_total > settings.maximum_tokens or len(vocabulary) > settings.maximum_vocabulary:
            raise StudyError("language token/vocabulary capacity exceeded")
        units.append(_unit(row, tokens, settings.window_tokens))
        issue_terms[row.issue_id].update(tokens)
        issue_units[row.issue_id] += 1
        pdfs[row.issue_id] = row.pdf_sha256
        for first, second in pairwise(tokens):
            pairs[(first, second)] += 1
            left[first] += 1
            right[second] += 1
    issues = tuple(
        IssueCounts(
            issue_id=issue,
            pdf_sha256=pdfs[issue],
            tokens=counts.total(),
            units=issue_units[issue],
            terms=tuple(
                TermCount(term=term, count=count) for term, count in sorted(counts.items())
            ),
        )
        for issue, counts in sorted(issue_terms.items())
    )
    selected = sorted(pairs.items(), key=lambda item: (-item[1], item[0]))
    return LayerMeasure(
        layer=layer,
        units=tuple(units),
        issues=issues,
        tokens=tokens_total,
        types=len(vocabulary),
        zero_token_units=sum(not unit.tokens for unit in units),
        eligible_issues=sum(bool(issue.tokens) for issue in issues),
        pair_opportunities=pairs.total(),
        frequencies=_frequencies(issues, settings.displayed_terms),
        adjacent_pairs=tuple(
            PairProfile(
                left=pair[0],
                right=pair[1],
                count=count,
                log_dice=14 + math.log2(2 * count / (left[pair[0]] + right[pair[1]])),
            )
            for pair, count in selected[: settings.displayed_pairs]
            if count >= settings.minimum_pair_count
        ),
    )


def analyze_language(
    units: Iterable[SourceTextUnit], settings: LanguageSettings | None = None
) -> LanguageRun:
    """Measure a finite caller-admitted selection; original units and layer gaps are retained."""
    options = settings if settings is not None else LanguageSettings()
    rows: list[SourceTextUnit] = []
    for unit in units:
        if len(rows) >= options.maximum_units:
            raise StudyError("language source-unit capacity exceeded")
        rows.append(unit)
    frozen = tuple(
        sorted(rows, key=lambda row: (row.layer, row.issue_id, row.page_index, row.unit_id))
    )
    _sources(frozen)
    digest = hashlib.sha256()
    for row in frozen:
        raw = row.model_dump_json().encode()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return LanguageRun(
        implementation_sha256=implementation_digest(),
        input_sha256=digest.hexdigest(),
        settings=options,
        input_units=len(frozen),
        layers=tuple(
            _measure(selected, layer, options)
            for layer in ("native", "ocr")
            for selected in (tuple(row for row in frozen if row.layer == layer),)
            if selected
        ),
    )
