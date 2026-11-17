"""Observed issue points and conditional diagnostics without invented trend lines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from crosstalk.statistical_records import StatisticalRecord
from crosstalk.statistical_svg import (
    CORAL,
    MUTED,
    NAVY,
    TEAL,
    Dot,
    FigureDraft,
    LabelStyle,
    SVGCanvas,
    linear,
    number,
)

if TYPE_CHECKING:
    from crosstalk.statistical_records import BootstrapInterval, BootstrapSettings, StatisticalRun


class NumericInterval(StatisticalRecord):
    """Parse nullable statistical fields into the numeric SVG-band contract."""

    estimate: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class ScatterPoint:
    """One descriptive extracted-text observation with its receipt status."""

    identity: str
    value: float
    partial: bool


@dataclass(frozen=True, slots=True)
class ScatterRow:
    """One issue-level measure and its separately declared interval estimand."""

    label: str
    values: tuple[ScatterPoint, ...]
    interval: BootstrapInterval
    center_y: float
    domain: tuple[float, float]


def _interval(run: StatisticalRun, measure: str) -> BootstrapInterval:
    """Require one explicit diagnostic state for each requested estimand."""
    found = tuple(row for row in run.bootstrap if row.measure == measure)
    if len(found) != 1:
        message = "statistical bootstrap estimands are missing or duplicated"
        raise ValueError(message)
    return found[0]


def _row(canvas: SVGCanvas, row: ScatterRow, settings: BootstrapSettings) -> None:
    """Issue observations stay visible whether diagnostic inference is available or absent."""
    left, right = 160.0, 835.0
    canvas.text((24, row.center_y + 4), row.label, LabelStyle(14))
    for index, point in enumerate(row.values):
        x = linear(point.value, row.domain, (left, right))
        y = row.center_y + ((index % 9) - 4) * 2
        status = "partial" if point.partial else "complete"
        canvas.dot(
            Dot(
                (x, y),
                3.5,
                f"{point.identity} ({status} extraction): {number(point.value)}",
                CORAL if point.partial else TEAL,
            )
        )
    if row.interval.estimate is not None:
        x = linear(row.interval.estimate, row.domain, (left, right))
        canvas.dot(Dot((x, row.center_y), 5.0, row.interval.estimand, NAVY))
    match row.interval.status:
        case "available-diagnostic":
            bounds = NumericInterval.model_validate(
                {
                    "estimate": row.interval.estimate,
                    "lower": row.interval.lower,
                    "upper": row.interval.upper,
                }
            )
            lower = linear(bounds.lower, row.domain, (left, right))
            upper = linear(bounds.upper, row.domain, (left, right))
            canvas.interval((lower, row.center_y + 22), (upper, row.center_y + 22))
            canvas.line((lower, row.center_y + 17), (lower, row.center_y + 27), NAVY)
            canvas.line((upper, row.center_y + 17), (upper, row.center_y + 27), NAVY)
            suffix = (
                " | zero-width diagnostic" if row.interval.diagnostic_interval_degenerate else ""
            )
            state = (
                f"{settings.confidence:.0%} issue-cluster diagnostic; "
                + f"{row.interval.valid_resamples} valid resamples"
                + suffix
            )
        case "below-resampling-gate":
            state = (
                f"Below gate: {row.interval.eligible_source_issue_units} eligible source issues; "
                + f"minimum {settings.minimum_issues} (heuristic)."
            )
        case "no-eligible-data":
            state = "Interval not estimable: no eligible issue observations."
        case _:
            assert_never(row.interval.status)
    canvas.text((160, row.center_y + 48), state, LabelStyle(12, MUTED))


def rate_chart(run: StatisticalRun) -> FigureDraft:
    """Distinguish per-issue raw rates from the pooled diagnostic estimands."""
    title, unit = (
        "Extracted-text lexical proxies",
        "Unit: occurrences per 1000 raw alphabetic tokens; English lexical rules",
    )
    canvas = SVGCanvas(title, unit)
    hedge, modal = _interval(run, "pooled_hedge_per_1000"), _interval(run, "pooled_modal_per_1000")
    hedges = tuple(
        ScatterPoint(row.issue_id, row.hedge_per_1000, row.extraction_status == "partial")
        for row in run.issues
        if row.hedge_per_1000 is not None
    )
    modals = tuple(
        ScatterPoint(row.issue_id, row.modal_per_1000, row.extraction_status == "partial")
        for row in run.issues
        if row.modal_per_1000 is not None
    )
    values = tuple(point.value for point in (*hedges, *modals)) + tuple(
        value
        for row in (hedge, modal)
        for value in (row.lower, row.upper, row.estimate)
        if value is not None
    )
    domain = (min((0.0, *values)), max((1.0, *values)))
    _row(canvas, ScatterRow("Hedge lexicon", hedges, hedge, 132, domain), run.settings)
    _row(canvas, ScatterRow("Modal lexicon", modals, modal, 240, domain), run.settings)
    if values:
        canvas.horizontal_axis(domain, (160, 326, 675, 0))
    canvas.text(
        (24, 379),
        "Teal: complete status | Coral: partial status | Navy: principal estimate",
        LabelStyle(12, MUTED),
    )
    canvas.text(
        (24, 405),
        "Principal diagnostics require known, complete PDF-page coverage; jitter separates points.",
        LabelStyle(12, MUTED),
    )
    caption = (
        "Each colored point describes extracted text from one source-distinct issue. "
        + "Partial extractions are coral. Navy estimates and bounds use only complete "
        + "extractions with known full PDF-page coverage, pooling lexical counts over raw tokens. "
        + "Bounds appear only when the declared resampling gate is met. "
        + "Minimum sample count is a heuristic and does not establish independence, "
        + "representativeness or population certainty."
    )
    return FigureDraft("lexical-rates", title, unit, len(hedges) + len(modals), caption, canvas)


def diversity_chart(run: StatisticalRun) -> FigureDraft:
    """Fixed-window issue means use an equal-issue, not equal-page, estimand."""
    title, unit = (
        "Equal-length vocabulary windows",
        "Unit: per-issue mean type-token ratio in complete "
        + f"{run.settings.window_size}-token normalized windows",
    )
    canvas = SVGCanvas(title, unit)
    interval = _interval(run, "issue_mean_window_ttr")
    values = tuple(
        ScatterPoint(row.issue_id, row.mean_window_ttr, row.extraction_status == "partial")
        for row in run.issues
        if row.mean_window_ttr is not None
    )
    _row(canvas, ScatterRow("Window TTR", values, interval, 178, (0, 1)), run.settings)
    if values:
        canvas.horizontal_axis((0, 1), (160, 284, 675, 0))
    canvas.text(
        (24, 353),
        f"Descriptive issues: {len(values)} | Principal eligible: "
        + f"{interval.eligible_source_issue_units} | Excluded: {interval.excluded_issue_units}",
        LabelStyle(12, MUTED),
    )
    canvas.text(
        (24, 385),
        "Teal: complete status | Coral: partial status | Navy: complete-coverage issue mean",
        LabelStyle(12, MUTED),
    )
    caption = (
        "Windows are nonoverlapping and restart on each physical PDF page. "
        + "Descriptive points include partial extractions (coral). The principal diagnostic "
        + "averages only known complete-coverage issue means equally; it is not token-weighted. "
        + "Incomplete page tails are excluded. No bounds appear below the resampling gate."
    )
    return FigureDraft("window-diversity", title, unit, len(values), caption, canvas)


def decade_chart(run: StatisticalRun) -> FigureDraft:
    """Present metadata-decade descriptions with n labels and no fitted historical trend."""
    title, unit = (
        "Repository-metadata decade groups",
        "Unit: source-distinct issues grouped by unambiguous repository metadata dates",
    )
    width = max(900, 110 * len(run.decades) + 140)
    canvas = SVGCanvas(title, unit, width)
    if run.decades:
        maximum = max(row.mean_issue_pages for row in run.decades) or 1.0
        canvas.count_axis(maximum, (90, 105, width - 140, 200))
        for index, row in enumerate(run.decades):
            x = 90 + (index + 0.5) / len(run.decades) * (width - 140)
            y = linear(row.mean_issue_pages, (0, maximum), (305, 105))
            canvas.dot(
                Dot(
                    (x, y),
                    5,
                    f"{row.metadata_decade}s: {row.issues} issues; "
                    + f"mean extracted pages {row.mean_issue_pages:.4g}",
                )
            )
            canvas.text((x, y - 13), f"n={row.issues}", LabelStyle(13, TEAL, "middle"))
            canvas.text((x, 334), f"{row.metadata_decade}s", LabelStyle(13, NAVY, "middle"))
        canvas.text(
            (24, 385),
            "Vertical axis: mean extracted pages per accepted issue. "
            + "Points are not joined or fitted.",
            LabelStyle(12, MUTED),
        )
    else:
        canvas.text(
            (width / 2, 200),
            "No eligible metadata-decade observations",
            LabelStyle(17, MUTED, "middle"),
        )
    canvas.text(
        (24, 410),
        f"Date-excluded issues: {len(run.date_excluded_issue_ids)} "
        + f"| accepted issues: {len(run.issues)}",
        LabelStyle(12, MUTED),
    )
    caption = (
        "The points describe extracted page counts, including partial extractions. "
        + "They do not estimate complete issue length. Labels give the number "
        + "of issues in each metadata decade. Dates are not independently verified printed "
        + "publication dates. No fitted trend, p value or causal claim is produced, "
        + "including when n=1."
    )
    return FigureDraft("metadata-decades", title, unit, len(run.decades), caption, canvas)
