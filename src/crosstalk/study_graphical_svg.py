"""Bounded escaped vector primitives; visible missingness never becomes a measured zero."""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from crosstalk.study_graphical_labels import arrow as draw_arrow
from crosstalk.study_graphical_labels import paragraph, text, width
from crosstalk.study_language_records import StudyError

__all__ = (
    "CORAL",
    "IVORY",
    "NAVY",
    "TEAL",
    "Box",
    "Drawing",
    "arrow",
    "canvas",
    "coverage",
    "histogram",
    "panel",
    "paragraph",
    "stat",
    "text",
    "width",
    "years",
)

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractHistogram, CatalogYear, DescriptorCoverage

type Box = tuple[float, float, float, float]
NAVY = "#111111"
TEAL = "#111111"
CORAL = "#b00020"
IVORY = "#ffffff"


@dataclass(frozen=True, slots=True)
class Drawing:
    """A complete authored page with fixed width and an explicit native-placement height."""

    title: str
    body: str
    height: int


def panel(box: Box, title: str) -> str:
    """Provide an editorial panel whose title is complete and conservatively bounded."""
    x, y, w, h = box
    return (
        '<rect x="'
        + f"{x}"
        + '" y="'
        + f"{y}"
        + '" width="'
        + f"{w}"
        + '" height="'
        + f"{h}"
        + '" rx="14" fill="white" stroke="#aaaaaa"/>'
    ) + paragraph((x + 18, y + 10, w - 36, 70), title, 20)


def stat(box: Box, value: int | None, label: str) -> str:
    """Fit an exact count/unknown label; no rounding or fabricated complete denominator."""
    x, y, w, h = box
    shown = "Unknown" if value is None else f"{value:,}"
    size = next(
        (candidate for candidate in (44, 38, 32, 26) if width(shown, candidate) <= w - 36), None
    )
    if size is None:
        raise StudyError("graphical exact count exceeds its bounded area")
    return (
        (
            '<rect x="'
            + f"{x}"
            + '" y="'
            + f"{y}"
            + '" width="'
            + f"{w}"
            + '" height="'
            + f"{h}"
            + '" rx="12" fill="#eeeeee"/>'
        )
        + text((x + 18, y + size + 12), shown, size)
        + paragraph((x + 18, y + size + 25, w - 36, h - size - 30), label, 20)
    )


def arrow(start: tuple[float, float], end: tuple[float, float]) -> str:
    """Draw a directional evidence transition without implying numerical equality of units."""
    return draw_arrow(start, end, TEAL)


def histogram(box: Box, observed: AbstractHistogram, color: str = TEAL) -> str:
    """Draw every supplied bin/count with explicit eligible and unavailable unit denominators."""
    x, y, w, h = box
    body = panel(box, observed.title)
    body += paragraph(
        (x + 18, y + 76, w - 36, 50),
        (
            "N="
            + f"{observed.eligible_units:,}"
            + " / "
            + f"{observed.total_units:,}"
            + " "
            + f"{observed.unit}"
            + "; unavailable "
            + f"{observed.unavailable_units:,}"
        ),
        18,
    )
    stride = min(28.0, (h - 140) / len(observed.bins))
    if stride < 22:
        raise StudyError("graphical histogram cannot retain every supplied bin legibly")
    maximum = max((row.count for row in observed.bins), default=0) or 1
    label_width = min(150.0, w * 0.37)
    numeric_width = 72.0
    bar_width = w - label_width - numeric_width - 46
    for index, row in enumerate(observed.bins):
        baseline = y + 140 + index * stride
        body += paragraph((x + 18, baseline - 19, label_width - 8, stride), row.label, 18)
        body += (
            '<rect x="'
            + f"{x + label_width + 18}"
            + '" y="'
            + f"{baseline - 16}"
            + '" width="'
            + f"{bar_width * row.count / maximum:.2f}"
            + '" height="18" fill="'
            + f"{color}"
            + '"/>'
        )
        body += text((x + w - numeric_width, baseline), f"{row.count:,}", 18)
    return body


def coverage(box: Box, observed: DescriptorCoverage, title: str) -> str:
    """Keep all four operational states in the physical-page denominator."""
    x, y, w, _ = box
    values = (
        ("Measured", observed.measured_pages, TEAL),
        ("Refused", observed.refused_pages, CORAL),
        ("Failed", observed.failed_pages, "#777777"),
        ("Unattempted", observed.unattempted_pages, "#dddddd"),
    )
    body = panel(box, title)
    at = x + 18
    for _, count, color in values:
        span = (w - 36) * count / observed.total_pages if observed.total_pages else 0.0
        body += (
            '<rect x="'
            + f"{at:.2f}"
            + '" y="'
            + f"{y + 85}"
            + '" width="'
            + f"{span:.2f}"
            + '" height="26" fill="'
            + f"{color}"
            + '"/>'
        )
        at += span
    for index, (label, count, color) in enumerate(values):
        left = x + 18 + (index % 2) * (w - 36) / 2
        baseline = y + 145 + (index // 2) * 31
        body += f'<circle cx="{left + 5}" cy="{baseline - 7}" r="5" fill="{color}"/>'
        body += text((left + 17, baseline), f"{label} {count:,}", 20)
    return body


def years(box: Box, values: tuple[CatalogYear, ...], undated: int) -> str:
    """Preserve empty captured-year bins without interpreting them as historical missing issues."""
    x, y, w, h = box
    if not values:
        return paragraph(
            box,
            (
                "No catalog-issued year distribution supplied"
                + "; undated rows "
                + f"{undated:,}"
                + "."
            ),
        )
    low, high = values[0].year, values[-1].year
    counts = {row.year: row.rows for row in values}
    maximum = max(counts.values(), default=0) or 1
    stride = (w - 60) / (high - low + 1)
    body = text((x, y + 22), f"Catalog-issued year labels; undated {undated:,}", 22)
    body += text(
        (x, y + 55), f"Peak captured year bin: {max(counts.values(), default=0):,} rows", 22
    )
    for year in range(low, high + 1):
        height = (h - 110) * counts.get(year, 0) / maximum
        left = x + 30 + (year - low) * stride
        body += (
            '<rect x="'
            + f"{left:.2f}"
            + '" y="'
            + f"{y + h - 42 - height:.2f}"
            + '" width="'
            + f"{max(0.4, stride - 2):.2f}"
            + '" height="'
            + f"{height:.2f}"
            + '" fill="'
            + f"{TEAL}"
            + '"/>'
        )
    candidates = tuple(
        year for year in range(low, high + 1) if year in {low, high} or year % 5 == 0
    )
    last_x = -math.inf
    for year in candidates:
        left = x + 30 + (year - low + 0.5) * stride
        last = x + 30 + (high - low + 0.5) * stride
        if year not in {low, high} and (left - last_x < 80 or last - left < 80):
            continue
        if year == high and high != low and left - last_x < 64:
            continue
        body += text((left - width(str(year), 24) / 2, y + h - 12), str(year), 24)
        last_x = left
    return body


def canvas(page: Drawing, metadata: str) -> str:
    """Create a self-contained vector page with complete escaped scientific metadata."""
    return (
        (
            '<svg xmlns="http://www.w3.org/2000/svg" widt'
            + 'h="1200" height="'
            + f"{page.height}"
            + '" viewBox="0 0 1200 '
            + f"{page.height}"
            + '">'
        )
        + "<metadata>"
        + escape(metadata)
        + "</metadata>"
        + f'<rect width="1200" height="{page.height}" fill="{IVORY}"/>'
        + f'<g font-family="Helvetica,Arial,sans-serif" fill="{NAVY}">'
        + paragraph((38, 17, 1124, 65), page.title, 32)
        + page.body
        + "</g></svg>"
    )
