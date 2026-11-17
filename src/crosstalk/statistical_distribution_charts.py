"""Descriptive coverage, physical-page and issue/asset-pair distributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.statistical_svg import (
    CORAL,
    MUTED,
    NAVY,
    TEAL,
    Box,
    FigureDraft,
    LabelStyle,
    SVGCanvas,
    number,
)

if TYPE_CHECKING:
    from crosstalk.statistical_records import StatisticalRun
    from crosstalk.statistical_visual_records import CoverageObservation


@dataclass(frozen=True, slots=True)
class HistogramSeries:
    """Counts, never density estimates; flags partition the same observed units."""

    values: tuple[float, ...]
    flagged: tuple[bool, ...] = ()
    axis_maximum: float = 0.0


def histogram(canvas: SVGCanvas, series: HistogramSeries, frame: Box) -> None:
    """Draw twelve bins with explicit zero/constant/empty handling."""
    x, y, width, height = frame
    if not series.values:
        canvas.text(
            (x + width / 2, y + height / 2), "No observed units", LabelStyle(16, MUTED, "middle")
        )
        return
    if any(value < 0 for value in series.values) or (
        series.flagged and len(series.flagged) != len(series.values)
    ):
        message = "histogram values/quality flags are invalid for nonnegative measurements"
        raise ValueError(message)
    maximum = max(*series.values, series.axis_maximum, 1.0)
    counts, flagged = [0] * 12, [0] * 12
    for index, value in enumerate(series.values):
        cell = min(int(value / maximum * 12), 11)
        counts[cell] += 1
        if series.flagged and series.flagged[index]:
            flagged[cell] += 1
    count_max = max(counts)
    for index, count in enumerate(counts):
        left = x + width * index / 12 + 1
        bar_width = max(width / 12 - 2, 0)
        bar_height = count / count_max * height
        alert_height = flagged[index] / count_max * height
        canvas.rectangle((left, y + height - bar_height, bar_width, bar_height), TEAL)
        canvas.rectangle((left, y + height - alert_height, bar_width, alert_height), CORAL)
    canvas.horizontal_axis((0, maximum), (x, y + height, width, 0))
    canvas.count_axis(count_max, frame)
    if min(series.values) == max(series.values):
        canvas.text(
            (x, y - 12),
            "Constant observed value: " + number(series.values[0]),
            LabelStyle(11, MUTED),
        )


def coverage_chart(run: StatisticalRun, coverage: CoverageObservation) -> FigureDraft:
    """Keep current catalog-bound states separate from unknown historical coverage."""
    title, unit = (
        "Coverage is a sequence of observations",
        "Units: catalog identities and accepted source issues; historical denominator unknown",
    )
    canvas = SVGCanvas(title, unit)
    caption = (
        "Catalog, locator, integrity and extraction states are different. "
        + "Historical archive completeness is not established. "
        + "Descriptive statistics retain any accepted partial extractions. "
        + "Status bars count accepted issue PDFs; principal diagnostics require known, "
        + "complete PDF-page coverage."
    )
    maximum = max(coverage.catalog_records or 0, len(run.issues), 1)
    if not coverage.available:
        canvas.text(
            (450, 155), "Catalog/acquisition coverage unavailable", LabelStyle(18, MUTED, "middle")
        )
        canvas.text(
            (450, 191),
            f"Accepted statistical issues: {len(run.issues)}",
            LabelStyle(15, NAVY, "middle"),
        )
        canvas.text(
            (450, 230),
            "Rebuild the current corpus index; unknown is not zero.",
            LabelStyle(14, MUTED, "middle"),
        )
    else:
        rows = (
            ("Captured catalog identities", coverage.catalog_records),
            ("Resolved official locators", coverage.resolved_locators),
            ("Verified local catalog PDFs", coverage.verified_pdfs),
            ("Current catalog extractions", coverage.current_extractions),
            ("Catalog issues in statistics", coverage.accepted_indexed_issues),
        )
        for index, (label, value) in enumerate(rows):
            top = 91 + index * 32
            canvas.text((24, top + 15), label, LabelStyle(13))
            if value is None:
                canvas.text((320, top + 15), "Unavailable", LabelStyle(13, MUTED))
            else:
                width = value / maximum * 470
                canvas.rectangle((310, top, width, 18), TEAL)
                canvas.text((320 + width, top + 16), str(value), LabelStyle(13))
        canvas.horizontal_axis((0, float(maximum)), (310, 263, 470, 0))
        report = (
            str(coverage.catalog_reported_total)
            if coverage.catalog_reported_total is not None
            else "unavailable"
        )
        state = (
            "matches captured rows"
            if coverage.capture_matches_reported
            else "partial/unverified capture"
        )
        canvas.text(
            (24, 302),
            f"Listing reported {report}: {state}. "
            + f"Uncataloged accepted issues: {coverage.uncataloged_accepted_issues}.",
            LabelStyle(12, MUTED),
        )
    if not coverage.available:
        canvas.horizontal_axis((0, float(maximum)), (310, 263, 470, 0))
        canvas.text(
            (24, 302),
            "Status bars below count only accepted source issues; catalog coverage is unknown.",
            LabelStyle(12, MUTED),
        )
    for index, (label, count, color) in enumerate(
        (
            ("Complete-status extractions", run.complete_extraction_issue_units, TEAL),
            ("Partial-status extractions", run.partial_extraction_issue_units, CORAL),
        )
    ):
        top = 318 + index * 30
        width = count / maximum * 470
        canvas.text((24, top + 13), label, LabelStyle(13))
        canvas.rectangle((310, top, width, 15), color)
        canvas.text((320 + width, top + 13), str(count), LabelStyle(13))
    canvas.text(
        (24, 391),
        f"Principal eligible: {run.principal_diagnostic_issue_units} | "
        + f"Unknown PDF-page coverage: {run.unknown_page_coverage_issue_units} | "
        + f"Extracted pages: {len(run.pages)}",
        LabelStyle(12, MUTED),
    )
    canvas.text(
        (24, 416),
        f"Statistical selection: {run.selected_issue_units} of {run.extraction_issue_units} "
        + f"extraction outcomes; deferred {len(run.deferred_issue_ids)}.",
        LabelStyle(12, MUTED),
    )
    return FigureDraft("coverage", title, unit, coverage.catalog_records, caption, canvas)


def page_chart(run: StatisticalRun) -> FigureDraft:
    """Count words on physical pages while showing low-text review flags."""
    title, unit = (
        "Physical-page word distribution",
        "Unit: physical PDF pages; counts include actual zero-token pages",
    )
    canvas = SVGCanvas(title, unit)
    histogram(
        canvas,
        HistogramSeries(
            tuple(float(page.normalized_tokens) for page in run.pages),
            tuple(page.low_text for page in run.pages),
        ),
        (75, 105, 755, 205),
    )
    canvas.text(
        (450, 366), "Normalized alphabetic tokens per physical page", LabelStyle(13, NAVY, "middle")
    )
    low = sum(page.low_text for page in run.pages)
    canvas.text(
        (75, 397),
        f"n={len(run.pages)} pages | teal: other pages | coral: {low} low-text review flags",
        LabelStyle(12, MUTED),
    )
    caption = (
        "Twelve count bins summarize physical pages in the accepted issue subset. "
        + "Low-text flags indicate review needs, not measured OCR errors. "
        + "Pages from partial extractions remain descriptive units; missing pages are absent. "
        + "Pages are not the resampling units."
    )
    return FigureDraft("page-words", title, unit, len(run.pages), caption, canvas)


def image_chart(run: StatisticalRun) -> FigureDraft:
    """Show raster descriptors without treating color/entropy as image semantics."""
    title, unit = (
        "Saved raster measurements",
        "Unit: issue / distinct saved-asset pairs, not image occurrences or all figures",
    )
    canvas = SVGCanvas(title, unit)
    histogram(
        canvas, HistogramSeries(tuple(row.aspect_ratio for row in run.images)), (65, 115, 345, 195)
    )
    histogram(
        canvas,
        HistogramSeries(tuple(row.grayscale_entropy_bits for row in run.images), axis_maximum=8.0),
        (515, 115, 345, 195),
    )
    canvas.text((238, 367), "Width / height", LabelStyle(13, NAVY, "middle"))
    canvas.text((688, 367), "Grayscale entropy (bits)", LabelStyle(13, NAVY, "middle"))
    occurrences = sum(row.occurrence_count for row in run.images)
    canvas.text(
        (24, 405),
        f"{len(run.images)} issue/asset pairs | {run.unique_saved_assets} globally distinct bytes "
        + f"| {occurrences} saved occurrences",
        LabelStyle(12, MUTED),
    )
    caption = (
        "Each histogram counts issue/asset pairs. A repeated asset may contribute once per issue "
        + "and have many placements. Vector diagrams, masks and unavailable raster objects "
        + "are not fully represented. Partial extractions supply only observed assets. "
        + "Entropy does not establish semantic complexity."
    )
    return FigureDraft("image-distributions", title, unit, len(run.images), caption, canvas)
