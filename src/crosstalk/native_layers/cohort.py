"""Conditional native-layer diagnostics keep whole sources and weighting explicit."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Literal, assert_never

from crosstalk.models import AcquisitionError
from crosstalk.native_layers.cohort_records import (
    CohortLayers,
    CohortSettings,
    LayerInterval,
    LexicalMeasure,
    PeriodAvailability,
    ViewName,
    Weighting,
)
from crosstalk.statistical_bootstrap import percentile
from crosstalk.statistical_source import metadata_date

if TYPE_CHECKING:
    from crosstalk.native_layers.records import IssueLayers, LayerView
    from crosstalk.statistical_records import BootstrapSettings

__all__ = ["CohortSettings", "selected_view", "summarize_layers"]


def selected_view(issue: IssueLayers, view: ViewName) -> LayerView:
    """Use an explicit derivative name rather than silently replacing the raw baseline."""
    match view:
        case "raw-native":
            return issue.raw
        case "native-minus-matched-repository-wrapper":
            return issue.wrapper_excluded
        case _:
            assert_never(view)


def _pair(view: LayerView, measure: LexicalMeasure, weighting: Weighting) -> tuple[float, float]:
    match measure:
        case "hedge-lexicon-per-1000":
            count = view.text.hedge_tokens
        case "modal-lexicon-per-1000":
            count = view.text.modal_tokens
        case _:
            assert_never(measure)
    match weighting:
        case "token-weighted":
            return float(1000 * count), float(view.text.tokens)
        case "equal-issue-weighted":
            return 1000 * count / view.text.tokens, 1.0
        case _:
            assert_never(weighting)


def _ratio(pairs: tuple[tuple[float, float], ...]) -> float:
    """Every admitted source has a positive token or equal-issue denominator."""
    return math.fsum(pair[0] for pair in pairs) / math.fsum(pair[1] for pair in pairs)


def _intervals(
    eligible: tuple[IssueLayers, ...], view: ViewName, settings: BootstrapSettings
) -> tuple[LayerInterval, ...]:
    intervals: list[LayerInterval] = []
    measures: tuple[LexicalMeasure, ...] = ("hedge-lexicon-per-1000", "modal-lexicon-per-1000")
    weights: tuple[Weighting, ...] = ("token-weighted", "equal-issue-weighted")
    for measure in measures:
        for weighting in weights:
            pairs = tuple(
                _pair(selected_view(issue, view), measure, weighting) for issue in eligible
            )
            samples: tuple[float, ...] = ()
            if len(pairs) >= settings.minimum_issues:
                generator = random.Random(settings.seed)  # noqa: S311 -- Conditional resampling.
                samples = tuple(
                    _ratio(tuple(pairs[generator.randrange(len(pairs))] for _ in pairs))
                    for _ in range(settings.resamples)
                )
            intervals.append(
                LayerInterval(
                    measure=measure,
                    weighting=weighting,
                    eligible_issue_ids=tuple(issue.identity.issue_id for issue in eligible),
                    estimate=_ratio(pairs) if pairs else None,
                    lower=percentile(samples, (1 - settings.confidence) / 2),
                    upper=percentile(samples, (1 + settings.confidence) / 2),
                    valid_resamples=len(samples),
                    status="available-diagnostic"
                    if samples
                    else "below-resampling-gate"
                    if pairs
                    else "no-eligible-data",
                    constant_issue_values=bool(pairs) and len({a / b for a, b in pairs}) == 1,
                )
            )
    return tuple(intervals)


def _period_record(
    issues: tuple[IssueLayers, ...],
    view: ViewName,
    period: tuple[Literal["metadata-year", "metadata-decade"], int],
) -> PeriodAvailability:
    """Keep extraction coverage and remaining native text as separate period denominators."""
    views = tuple(selected_view(issue, view) for issue in issues)
    return PeriodAvailability(
        unit=period[0],
        period_start=period[1],
        observed_issue_units=len(issues),
        complete_extraction_issue_units=sum(
            issue.identity.extraction_status == "complete" for issue in issues
        ),
        partial_extraction_issue_units=sum(
            issue.identity.extraction_status == "partial" for issue in issues
        ),
        zero_native_token_issue_units=sum(row.text.tokens == 0 for row in views),
        physical_pdf_pages=sum(issue.identity.total_pdf_pages for issue in issues),
        selected_native_pages=sum(len(row.included_page_indexes) for row in views),
        native_tokens=sum(row.text.tokens for row in views),
    )


def _periods(
    issues: tuple[IssueLayers, ...], view: ViewName
) -> tuple[tuple[PeriodAvailability, ...], tuple[str, ...]]:
    """Exclude conflicting/unknown dates from both temporal groupings without discarding text."""
    years: dict[int, list[IssueLayers]] = {}
    decades: dict[int, list[IssueLayers]] = {}
    unknown: list[str] = []
    for issue in issues:
        _, _, year = metadata_date(issue.identity.issued, issue.identity.title)
        if year is None:
            unknown.append(issue.identity.issue_id)
        else:
            years.setdefault(year, []).append(issue)
            decades.setdefault(year // 10 * 10, []).append(issue)
    return (
        *tuple(
            _period_record(tuple(values), view, ("metadata-year", year))
            for year, values in sorted(years.items())
        ),
        *tuple(
            _period_record(tuple(values), view, ("metadata-decade", decade))
            for decade, values in sorted(decades.items())
        ),
    ), tuple(unknown)


def summarize_layers(
    issues: tuple[IssueLayers, ...], configuration: CohortSettings
) -> CohortLayers:
    """Resample source-distinct complete positive-denominator issues after layer selection."""
    view, settings, native_rich = (
        configuration.view,
        configuration.bootstrap,
        configuration.native_rich,
    )
    if (
        len(issues) > settings.max_issues
        or len({row.identity.issue_id for row in issues}) != len(issues)
        or (
            len({row.identity.pdf_sha256 for row in issues}) != len(issues)
            or len({row.identity.source_kind for row in issues}) > 1
            or len({row.settings.model_dump_json() for row in issues}) > 1
        )
    ):
        raise AcquisitionError(
            "native cohort is oversized, source-duplicated or mixes settings/kinds"
        )
    ordered = tuple(sorted(issues, key=lambda issue: issue.identity.issue_id))
    workflow = tuple(
        issue
        for issue in ordered
        if not native_rich or selected_view(issue, view).exploratory_native_rich
    )
    eligible = tuple(
        issue
        for issue in workflow
        if issue.identity.extraction_status == "complete"
        and selected_view(issue, view).text.tokens > 0
    )
    views = tuple(selected_view(issue, view) for issue in workflow)
    pages = sum(len(row.included_page_indexes) for row in views)
    periods, unknown = _periods(workflow, view)
    return CohortLayers(
        view=view,
        native_rich_restriction=native_rich,
        settings=settings,
        observed_issue_ids=tuple(issue.identity.issue_id for issue in ordered),
        workflow_selected_issue_ids=tuple(issue.identity.issue_id for issue in workflow),
        eligible_complete_nonzero_issue_ids=tuple(issue.identity.issue_id for issue in eligible),
        partial_issue_ids=tuple(
            issue.identity.issue_id
            for issue in workflow
            if issue.identity.extraction_status == "partial"
        ),
        zero_native_token_issue_ids=tuple(
            issue.identity.issue_id
            for issue in workflow
            if selected_view(issue, view).text.tokens == 0
        ),
        observed_physical_pages=pages,
        excluded_wrapper_pages=sum(len(row.excluded_page_indexes) for row in views),
        observed_native_characters=sum(row.native_characters for row in views),
        observed_native_tokens=sum(row.text.tokens for row in views),
        observed_low_text_pages=sum(row.low_text_pages for row in views),
        observed_low_text_fraction=sum(row.low_text_pages for row in views) / pages
        if pages
        else None,
        unknown_or_conflicting_date_issue_ids=unknown,
        metadata_periods=periods,
        intervals=_intervals(eligible, view, settings),
    )
