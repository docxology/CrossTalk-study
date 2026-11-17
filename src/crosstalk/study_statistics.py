"""Exploratory keyness ranks and conditional whole-issue cluster diagnostics."""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.study_language import implementation_digest
from crosstalk.study_language_records import (
    ContrastResult,
    CountComparison,
    KeynessTerm,
    StudyError,
)

if TYPE_CHECKING:
    from crosstalk.study_language_records import ContrastPlan, IssueCounts, LanguageRun


@dataclass(frozen=True, slots=True)
class _Cluster:
    issue_id: str
    tokens: int
    terms: Counter[str]


def g_squared(counts: CountComparison) -> float:
    """Return the full two-by-two likelihood-ratio rank score, never a token p-value."""
    table = (
        (counts.count_a, counts.tokens_a - counts.count_a),
        (counts.count_b, counts.tokens_b - counts.count_b),
    )
    rows = (counts.tokens_a, counts.tokens_b)
    columns = (
        counts.count_a + counts.count_b,
        counts.tokens_a + counts.tokens_b - counts.count_a - counts.count_b,
    )
    total = sum(rows)
    return max(
        0.0,
        2
        * sum(
            observed * math.log(observed / (rows[i] * columns[j] / total))
            for i, row in enumerate(table)
            for j, observed in enumerate(row)
            if observed
        ),
    )


def log2_rate_ratio(counts: CountComparison, pseudocount: float = 0.5) -> float:
    """Binary additive smoothing applies to word and nonword cells, including zero cells."""
    if not math.isfinite(pseudocount) or pseudocount <= 0:
        raise StudyError("rate-ratio pseudocount must be finite and positive")
    first = (counts.count_a + pseudocount) / (counts.tokens_a + 2 * pseudocount)
    second = (counts.count_b + pseudocount) / (counts.tokens_b + 2 * pseudocount)
    return math.log2(first / second)


def _clusters(rows: tuple[IssueCounts, ...], selection: tuple[str, ...]) -> tuple[_Cluster, ...]:
    lookup = {row.issue_id: row for row in rows}
    if not set(selection) <= lookup.keys():
        raise StudyError("contrast cohort contains an issue absent from the selected text layer")
    return tuple(
        _Cluster(
            issue,
            lookup[issue].tokens,
            Counter({term.term: term.count for term in lookup[issue].terms}),
        )
        for issue in selection
        if lookup[issue].tokens
    )


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


@dataclass(frozen=True, slots=True)
class _TermCohorts:
    term: str
    first: tuple[_Cluster, ...]
    second: tuple[_Cluster, ...]


def _interval(cohorts: _TermCohorts, plan: ContrastPlan) -> tuple[float | None, float | None]:
    if min(len(cohorts.first), len(cohorts.second)) < plan.minimum_cluster_issues:
        return None, None
    generator = random.Random(plan.seed)  # noqa: S311 -- Reproducible scientific resampling, not security.
    observations: list[float] = []
    for _ in range(plan.resamples):
        first = generator.choices(cohorts.first, k=len(cohorts.first))
        second = generator.choices(cohorts.second, k=len(cohorts.second))
        counts = CountComparison(
            count_a=sum(row.terms[cohorts.term] for row in first),
            count_b=sum(row.terms[cohorts.term] for row in second),
            tokens_a=sum(row.tokens for row in first),
            tokens_b=sum(row.tokens for row in second),
        )
        observations.append(log2_rate_ratio(counts, plan.pseudocount))
    observations.sort()
    return _quantile(observations, 0.025), _quantile(observations, 0.975)


def _term(cohorts: _TermCohorts, plan: ContrastPlan) -> KeynessTerm:
    counts = CountComparison(
        count_a=sum(row.terms[cohorts.term] for row in cohorts.first),
        count_b=sum(row.terms[cohorts.term] for row in cohorts.second),
        tokens_a=sum(row.tokens for row in cohorts.first),
        tokens_b=sum(row.tokens for row in cohorts.second),
    )
    lower, upper = _interval(cohorts, plan)
    return KeynessTerm(
        term=cohorts.term,
        count_a=counts.count_a,
        count_b=counts.count_b,
        tokens_a=counts.tokens_a,
        tokens_b=counts.tokens_b,
        observed_issues_a=sum(bool(row.terms[cohorts.term]) for row in cohorts.first),
        observed_issues_b=sum(bool(row.terms[cohorts.term]) for row in cohorts.second),
        g_squared_rank_score=g_squared(counts),
        log2_rate_ratio=log2_rate_ratio(counts, plan.pseudocount),
        interval_status="available-diagnostic" if lower is not None else "below-cluster-gate",
        lower=lower,
        upper=upper,
    )


def compare_language(run: LanguageRun, plan: ContrastPlan) -> ContrastResult:
    """Apply a frozen explicit contrast; zero-token clusters cannot become zero-rate issues."""
    method = implementation_digest()
    if run.implementation_sha256 != method:
        raise StudyError("language run implementation is stale")
    layers = tuple(row for row in run.layers if row.layer == plan.layer)
    if len(layers) != 1:
        raise StudyError("requested text layer is unavailable or ambiguous")
    rows = layers[0].issues
    first = _clusters(rows, plan.cohort_a)
    second = _clusters(rows, plan.cohort_b)
    if not first or not second:
        raise StudyError("both contrast cohorts need positive observed token denominators")
    counts: Counter[str] = Counter()
    appearances: Counter[str] = Counter()
    for cluster in (*first, *second):
        counts.update(cluster.terms)
        appearances.update(cluster.terms.keys())
    candidates = tuple(
        term
        for term in sorted(counts)
        if counts[term] >= plan.minimum_total_count
        and appearances[term] >= plan.minimum_observed_issues
    )
    ranked = sorted(
        candidates,
        key=lambda term: (
            -g_squared(
                CountComparison(
                    count_a=sum(row.terms[term] for row in first),
                    count_b=sum(row.terms[term] for row in second),
                    tokens_a=sum(row.tokens for row in first),
                    tokens_b=sum(row.tokens for row in second),
                )
            ),
            term,
        ),
    )[: plan.maximum_terms]
    result = ContrastResult(
        plan=plan,
        plan_sha256=hashlib.sha256(plan.model_dump_json().encode()).hexdigest(),
        language_input_sha256=run.input_sha256,
        implementation_sha256=method,
        eligible_a=tuple(row.issue_id for row in first),
        eligible_b=tuple(row.issue_id for row in second),
        zero_token_issue_ids=tuple(
            row.issue_id
            for row in rows
            if not row.tokens and row.issue_id in (*plan.cohort_a, *plan.cohort_b)
        ),
        tested_vocabulary=len(candidates),
        terms=tuple(_term(_TermCohorts(term, first, second), plan) for term in ranked),
    )
    if implementation_digest() != method:
        raise StudyError("statistical implementation changed during measurement")
    return result
