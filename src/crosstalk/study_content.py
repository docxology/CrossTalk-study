"""Full counts feed disclosed word displays and within-unit adjacent-pair support diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.study_content_records import (
    ContentLayer,
    ContentRun,
    ContentSettings,
    ContentTerm,
    PairIssueCounts,
    SupportedPair,
)
from crosstalk.study_language import implementation_digest as tokenization_identity
from crosstalk.study_language import tokenize
from crosstalk.study_language_records import StudyError, TermProfile
from crosstalk.study_unit_sources import source_units, unit_frame

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crosstalk.study_language_records import Layer, SourceTextUnit

METHOD_FILES: Final = ("study_content.py", "study_content_records.py", "study_unit_sources.py")


def implementation_digest() -> str:
    """Bind the display method to its exact source and existing tokenizer/runtime identity."""
    directory = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest()) for name in METHOD_FILES
    )
    return hashlib.sha256(
        json.dumps((members, tokenization_identity()), separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _Counts:
    """Fixed issue identity with mutable counting buffers; all stopwords remain counted."""

    issue_id: str = ""
    terms: Counter[str] = field(default_factory=Counter)
    pairs: Counter[tuple[str, str]] = field(default_factory=Counter)
    left: Counter[str] = field(default_factory=Counter)
    right: Counter[str] = field(default_factory=Counter)

    def include(self, tokens: tuple[str, ...]) -> None:
        """Restart adjacency at every admitted supplied unit."""
        self.terms.update(tokens)
        for first, second in pairwise(tokens):
            self.pairs[(first, second)] += 1
            self.left[first] += 1
            self.right[second] += 1


def _display(term: str, settings: ContentSettings) -> bool:
    return (
        settings.minimum_characters <= len(term) <= settings.maximum_display_characters
        and term not in settings.stoplist
    )


def _terms(
    issues: tuple[_Counts, ...], settings: ContentSettings
) -> tuple[tuple[ContentTerm, ...], int]:
    positive = tuple(issue for issue in issues if issue.terms)
    counts = Counter[str]()
    for issue in positive:
        counts.update(issue.terms)
    total = counts.total()
    selected = tuple(
        (term, count)
        for term, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))
        if _display(term, settings)
        and sum(bool(issue.terms[term]) for issue in positive) >= settings.minimum_issue_support
    )
    return tuple(
        ContentTerm(
            frequency=TermProfile(
                term=term,
                count=count,
                per_1000_tokens=1000 * count / total,
                observed_issues=sum(bool(issue.terms[term]) for issue in positive),
                eligible_issues=len(positive),
                issue_prevalence=sum(bool(issue.terms[term]) for issue in positive) / len(positive),
                deviation_from_token_share=0.5
                * sum(
                    abs(issue.terms[term] / count - issue.terms.total() / total)
                    for issue in positive
                ),
            ),
            maximum_issue_count_share=max(issue.terms[term] for issue in positive) / count,
            maximum_issue_ids=tuple(
                issue.issue_id
                for issue in positive
                if issue.terms[term] == max(peer.terms[term] for peer in positive)
            ),
        )
        for term, count in selected[: settings.displayed_terms]
    ), len(selected)


def _pair(pair: tuple[str, str], issues: tuple[_Counts, ...], totals: _Counts) -> SupportedPair:
    first, second = pair
    count, left, right = totals.pairs[pair], totals.left[first], totals.right[second]
    eligible = tuple(issue for issue in issues if issue.pairs)
    deleted = tuple(
        14
        + math.log2(
            2
            * (count - issue.pairs[pair])
            / (left + right - issue.left[first] - issue.right[second])
        )
        for issue in eligible
        if count > issue.pairs[pair]
    )
    return SupportedPair(
        left=first,
        right=second,
        count=count,
        left_opportunities=left,
        right_opportunities=right,
        total_pair_opportunities=totals.pairs.total(),
        per_1000_pair_opportunities=1000 * count / totals.pairs.total(),
        log_dice=14 + math.log2(2 * count / (left + right)),
        observed_issues=sum(bool(issue.pairs[pair]) for issue in eligible),
        eligible_pair_issues=len(eligible),
        maximum_issue_count_share=max(issue.pairs[pair] for issue in eligible) / count,
        deletion_eligible_issues=len(deleted),
        leave_one_issue_out_log_dice_min=min(deleted, default=None),
        leave_one_issue_out_log_dice_max=max(deleted, default=None),
        issue_counts=tuple(
            PairIssueCounts(
                issue_id=issue.issue_id,
                count=issue.pairs[pair],
                left_opportunities=issue.left[first],
                right_opportunities=issue.right[second],
                pair_opportunities=issue.pairs.total(),
            )
            for issue in eligible
        ),
    )


def _layer(
    rows: tuple[SourceTextUnit, ...], layer: Layer, settings: ContentSettings
) -> ContentLayer:
    issues: dict[str, _Counts] = {}
    totals = _Counts()
    total_tokens = 0
    for row in rows:
        tokens = tokenize(row.text)
        total_tokens += len(tokens)
        totals.include(tokens)
        issue = issues.get(row.issue_id)
        if issue is None:
            issue = _Counts(issue_id=row.issue_id)
            issues[row.issue_id] = issue
        issue.include(tokens)
        if (
            total_tokens > settings.maximum_tokens
            or len(totals.pairs) > settings.maximum_distinct_pairs
        ):
            raise StudyError("content token/pair capacity exceeded")
    peers = tuple(issues.values())
    terms, screened_terms = _terms(peers, settings)
    pairs = tuple(
        pair
        for pair, count in sorted(totals.pairs.items(), key=lambda row: (-row[1], row[0]))
        if count >= settings.minimum_pair_count
        and all(_display(term, settings) for term in pair)
        and sum(bool(issue.pairs[pair]) for issue in peers) >= settings.minimum_issue_support
    )
    return ContentLayer(
        layer=layer,
        supplied_units=len(rows),
        tokens=total_tokens,
        positive_token_issues=sum(bool(issue.terms) for issue in peers),
        pair_opportunities=totals.pairs.total(),
        eligible_pair_issues=sum(bool(issue.pairs) for issue in peers),
        vocabulary=len(totals.terms),
        distinct_pairs=len(totals.pairs),
        screened_terms=screened_terms,
        screened_pairs=len(pairs),
        terms=terms,
        pairs=tuple(_pair(pair, peers, totals) for pair in pairs[: settings.displayed_pairs]),
    )


def content_diagnostics(
    units: Iterable[SourceTextUnit], settings: ContentSettings | None = None
) -> ContentRun:
    """Measure admitted units with separate layers and complete denominators."""
    options = settings if settings is not None else ContentSettings()
    if any(tokenize(term) != (term,) for term in options.stoplist):
        raise StudyError(
            "content stoplist entries must be single exis" + "ting-normalization tokens"
        )
    rows = source_units(units, options.maximum_units)
    method = implementation_digest()
    layers = tuple(
        _layer(selected, layer, options)
        for layer in ("native", "ocr")
        for selected in (tuple(row for row in rows if row.layer == layer),)
        if selected
    )
    if sum(layer.tokens for layer in layers) > options.maximum_tokens:
        raise StudyError("content token capacity exceeded across text layers")
    if implementation_digest() != method:
        raise StudyError("content method changed during computation")
    return ContentRun(
        implementation_sha256=method,
        unit_frame_sha256=unit_frame(rows),
        settings=options,
        layers=layers,
    )
