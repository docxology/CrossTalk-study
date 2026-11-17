"""Predeclared issue-cluster diagnostics and finite descriptive summaries."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, assert_never

from crosstalk.statistical_records import BootstrapInterval, Distribution

if TYPE_CHECKING:
    from crosstalk.statistical_records import BootstrapSettings, IssueStatistic

Measure = Literal["pooled_hedge_per_1000", "pooled_modal_per_1000", "issue_mean_window_ttr"]
DESCRIPTIONS: Final[dict[Measure, tuple[str, str]]] = {
    "pooled_hedge_per_1000": (
        "Pooled declared hedge-lexicon count per 1000 raw alphabetic tokens",
        "Raw alphabetic tokens in eligible source-distinct complete-extraction issues",
    ),
    "pooled_modal_per_1000": (
        "Pooled declared modal-lexicon count per 1000 raw alphabetic tokens",
        "Raw alphabetic tokens in eligible source-distinct complete-extraction issues",
    ),
    "issue_mean_window_ttr": (
        "Equal-weight mean of per-issue mean complete-window TTR",
        "Eligible source-distinct complete-extraction issues with complete token windows",
    ),
}


@dataclass(frozen=True, slots=True)
class IssueMeasure:
    """A whole issue contributes one numerator/denominator pair per selected metric."""

    numerator: float
    denominator: float


def percentile(values: tuple[float, ...], probability: float) -> float | None:
    """Use linear interpolation between ordered finite observations."""
    if not 0 <= probability <= 1 or any(not math.isfinite(value) for value in values):
        message = "percentile inputs must be finite with probability in [0, 1]"
        raise ValueError(message)
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(values: tuple[float | None, ...], identity: tuple[str, str]) -> Distribution:
    """Describe observed units; unavailable values remain a separate denominator."""
    observed = tuple(value for value in values if value is not None)
    if any(not math.isfinite(value) for value in observed):
        message = "nonfinite descriptive measurement refused"
        raise ValueError(message)
    return Distribution(
        measure=identity[0],
        unit=identity[1],
        observed_units=len(observed),
        missing_units=len(values) - len(observed),
        minimum=min(observed) if observed else None,
        q25=percentile(observed, 0.25),
        median=percentile(observed, 0.5),
        q75=percentile(observed, 0.75),
        maximum=max(observed) if observed else None,
        mean=math.fsum(observed) / len(observed) if observed else None,
    )


def _measure(issue: IssueStatistic, measure: Measure) -> IssueMeasure | None:
    match measure:
        case "pooled_hedge_per_1000":
            return (
                IssueMeasure(1000.0 * issue.hedge_tokens, float(issue.raw_tokens))
                if issue.raw_tokens
                else None
            )
        case "pooled_modal_per_1000":
            return (
                IssueMeasure(1000.0 * issue.modal_tokens, float(issue.raw_tokens))
                if issue.raw_tokens
                else None
            )
        case "issue_mean_window_ttr":
            return (
                IssueMeasure(issue.mean_window_ttr, 1.0)
                if issue.mean_window_ttr is not None
                else None
            )
        case _:
            assert_never(measure)


def _ratio(values: tuple[IssueMeasure, ...]) -> float:
    """All eligible issue denominators are strictly positive."""
    result = math.fsum(value.numerator for value in values) / math.fsum(
        value.denominator for value in values
    )
    if not math.isfinite(result):
        message = "nonfinite issue-cluster estimate refused"
        raise ValueError(message)
    return result


def principal_issue(issue: IssueStatistic) -> bool:
    """A known full page count is required; distinct PDFs do not prove independence."""
    return (
        issue.extraction_status == "complete"
        and issue.total_pdf_pages is not None
        and issue.pages == issue.total_pdf_pages
    )


def cluster_intervals(
    issues: tuple[IssueStatistic, ...], settings: BootstrapSettings
) -> tuple[BootstrapInterval, ...]:
    """Resample whole canonical issues; never resample pages or windows independently."""
    identifiers = tuple(issue.issue_id for issue in issues)
    hashes = tuple(issue.pdf_sha256 for issue in issues)
    if len(set(identifiers)) != len(identifiers) or len(set(hashes)) != len(hashes):
        message = "duplicate issue identities or PDFs cannot be distinct resampling source units"
        raise ValueError(message)
    ordered = tuple(
        sorted(
            (issue for issue in issues if principal_issue(issue)), key=lambda issue: issue.issue_id
        )
    )
    partial = sum(issue.extraction_status == "partial" for issue in issues)
    unknown_coverage = len(issues) - len(ordered) - partial
    measures: tuple[Measure, ...] = (
        "pooled_hedge_per_1000",
        "pooled_modal_per_1000",
        "issue_mean_window_ttr",
    )
    intervals: list[BootstrapInterval] = []
    for measure in measures:
        values = tuple(
            value for issue in ordered if (value := _measure(issue, measure)) is not None
        )
        estimate = _ratio(values) if values else None
        samples: tuple[float, ...] = ()
        if len(values) >= settings.minimum_issues:
            generator = random.Random(settings.seed)  # noqa: S311 -- Bootstrap sampling.
            samples = tuple(
                _ratio(tuple(values[generator.randrange(len(values))] for _ in values))
                for _ in range(settings.resamples)
            )
        status: Literal["available-diagnostic", "below-resampling-gate", "no-eligible-data"] = (
            "available-diagnostic"
            if samples
            else "below-resampling-gate"
            if values
            else "no-eligible-data"
        )
        estimand, denominator = DESCRIPTIONS[measure]
        intervals.append(
            BootstrapInterval(
                measure=measure,
                estimand=estimand,
                eligible_source_issue_units=len(values),
                excluded_issue_units=len(issues) - len(values),
                excluded_partial_issue_units=partial,
                excluded_unknown_coverage_issue_units=unknown_coverage,
                excluded_metric_unavailable_issue_units=len(ordered) - len(values),
                denominator=denominator,
                estimate=estimate,
                lower=percentile(samples, (1 - settings.confidence) / 2),
                upper=percentile(samples, (1 + settings.confidence) / 2),
                valid_resamples=len(samples),
                status=status,
                constant_issue_values=bool(values)
                and len({value.numerator / value.denominator for value in values}) == 1,
                diagnostic_interval_degenerate=bool(samples) and min(samples) == max(samples),
            )
        )
    return tuple(intervals)
