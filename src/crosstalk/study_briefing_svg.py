"""Dense monochrome briefing primitives; red names an explicit focus, never an inferred alarm."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from crosstalk.study_graphical_svg import paragraph, text, width

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractHistogram, CatalogYear, DescriptorCoverage

type Box = tuple[float, float, float, float]
BLACK = "#000000"
GRAY = "#777777"
LIGHT = "#dddddd"
RED = "#b00020"


@dataclass(frozen=True, slots=True)
class BriefingPage:
    """A complete research page, not a classification or agency document."""

    title: str
    focus: str
    body: str
    height: int


def number(position: tuple[float, float], value: int | None, size: float = 44) -> str:
    """Expose exact counts in a compact tabular face; unknown remains explicit."""
    shown = "UNKNOWN" if value is None else f"{value:,}"
    return (
        (
            '<text x="'
            + f"{position[0]}"
            + '" y="'
            + f"{position[1]}"
            + '" font-family="Courier New,Courier,monospace'
            + '" '
        )
        + f'font-size="{size}">'
        + escape(shown)
        + "</text>"
    )


def line(bounds: tuple[float, float, float, float], shade: str = BLACK) -> str:
    """Use thin editorial rules rather than boxes or false institutional insignia."""
    x0, y0, x1, y1 = bounds
    return (
        '<line x1="'
        + f"{x0}"
        + '" y1="'
        + f"{y0}"
        + '" x2="'
        + f"{x1}"
        + '" y2="'
        + f"{y1}"
        + '" stroke="'
        + f"{shade}"
        + '" stroke-width="1"/>'
    )


def metric(box: Box, value: int | None, label: str) -> str:
    """Place a count, its explicit unit and a baseline without a decorative card."""
    x, y, w, h = box
    return (
        number((x, y + 53), value, 52)
        + paragraph((x, y + 68, w, h - 75), label, 22)
        + line((x, y + h, x + w, y + h), GRAY)
    )


def section(position: tuple[float, float], title: str) -> str:
    """Separate analytical sections with concise direct labels."""
    return text(position, title.upper(), 23)


def histogram(box: Box, observed: AbstractHistogram) -> str:
    """Keep every bin, its count, eligible N and exclusions in the graphic itself."""
    x, y, w, h = box
    body = paragraph((x, y, w, 62), observed.title.upper(), 22) + line((x, y + 72, x + w, y + 72))
    body += paragraph(
        (x, y + 82, w, 55),
        (
            "ELIGIBLE "
            + f"{observed.eligible_units:,}"
            + "/"
            + f"{observed.total_units:,}"
            + " "
            + f"{observed.unit}"
            + "; EXCLUDED "
            + f"{observed.unavailable_units:,}"
        ),
        18,
    )
    stride = min(31.0, (h - 156) / len(observed.bins))
    maximum = max((row.count for row in observed.bins), default=0) or 1
    label_width, numeric_width = min(w * 0.35, 150.0), 78.0
    plot_width = w - label_width - numeric_width - 20
    for index, row in enumerate(observed.bins):
        baseline = y + 157 + index * stride
        body += paragraph((x, baseline - 20, label_width - 8, stride), row.label, 18)
        body += (
            '<rect x="'
            + f"{x + label_width}"
            + '" y="'
            + f"{baseline - 17}"
            + '" width="'
            + f"{plot_width * row.count / maximum:.2f}"
            + '" height="19" fill="'
            + f"{GRAY}"
            + '"/>'
        )
        body += number((x + w - numeric_width, baseline), row.count, 19)
    return body


def coverage(box: Box, observed: DescriptorCoverage, title: str) -> str:
    """Patterns and direct labels preserve all four operational states in grayscale."""
    x, y, w, _ = box
    rows = (
        ("MEASURED", observed.measured_pages, BLACK),
        ("REFUSED", observed.refused_pages, "url(#brief-refused)"),
        ("FAILED", observed.failed_pages, "url(#brief-failed)"),
        ("UNATTEMPTED", observed.unattempted_pages, "url(#brief-unseen)"),
    )
    body = section((x, y + 23), title) + line((x, y + 35, x + w, y + 35))
    cursor = x
    for _, count, fill in rows:
        span = w * count / observed.total_pages if observed.total_pages else 0.0
        body += (
            '<rect x="'
            + f"{cursor:.2f}"
            + '" y="'
            + f"{y + 52}"
            + '" width="'
            + f"{span:.2f}"
            + '" height="22" fill="'
            + f"{fill}"
            + '" stroke="'
            + f"{BLACK}"
            + '" stroke-width="0.6"/>'
        )
        cursor += span
    for index, (label, count, fill) in enumerate(rows):
        left, baseline = x + (index % 2) * w / 2, y + 110 + (index // 2) * 33
        body += (
            '<rect x="'
            + f"{left}"
            + '" y="'
            + f"{baseline - 16}"
            + '" width="16" height="16" fill="'
            + f"{fill}"
            + '" stroke="'
            + f"{BLACK}"
            + '" stroke-width="0.6"/>'
        )
        body += text((left + 25, baseline), f"{label} {count:,}", 19)
    return body


def years(box: Box, values: tuple[CatalogYear, ...], undated: int) -> str:
    """Direct-label captured-year counts; gaps never imply an expected monthly issue run."""
    x, y, w, h = box
    body = section((x, y + 23), f"CATALOG-ISSUED YEARS / UNDATED {undated:,}")
    body += line((x, y + 35, x + w, y + 35))
    if not values:
        return body + paragraph((x, y + 55, w, h - 60), "No dated captured rows supplied.", 22)
    low, high = values[0].year, values[-1].year
    counts = {row.year: row.rows for row in values}
    maximum = max(counts.values(), default=0) or 1
    stride = (w - 30) / (high - low + 1)
    base = y + h - 35
    for year in range(low, high + 1):
        left = x + 15 + (year - low) * stride
        count = counts.get(year, 0)
        height = (h - 95) * count / maximum
        body += (
            '<rect x="'
            + f"{left:.2f}"
            + '" y="'
            + f"{base - height:.2f}"
            + '" width="'
            + f"{max(0.4, stride - 2):.2f}"
            + '" height="'
            + f"{height:.2f}"
            + '" fill="'
            + f"{GRAY}"
            + '"/>'
        )
        if count and stride >= 28:
            body += number((left + 2, base - height - 5), count, 18)
    last = -1e9
    for year in range(low, high + 1):
        center = x + 15 + (year - low + 0.5) * stride
        endpoint = x + 15 + (high - low + 0.5) * stride
        if year not in {low, high} and (year % 5 or center - last < 80 or endpoint - center < 80):
            continue
        if year == high and year != low and center - last < 64:
            continue
        body += text((center - width(str(year), 22) / 2, y + h - 7), str(year), 22)
        last = center
    return body


def canvas(page: BriefingPage, metadata: str) -> str:
    """Place a research focus within small margins without classification stamps."""
    patterns = (
        (
            '<defs><pattern id="brief-refused" width="6" '
            + 'height="6" patternUnits="userSpaceOnUse">'
        )
        + (
            '<rect width="6" height="6" fill="#ffffff"/><'
            + 'path d="M-1,1 L1,-1 M0,6 L6,0 M5,7 L7,5" str'
            + 'oke="#777777" stroke-width="1"/></pattern>'
        )
        + (
            '<pattern id="brief-failed" width="7" height='
            + '"7" patternUnits="userSpaceOnUse"><rect widt'
            + 'h="7" height="7" fill="#dddddd"/>'
        )
        + ('<path d="M0,0 L7,7 M0,7 L7,0" stroke="#77777' + '7" stroke-width="0.8"/></pattern>')
        + (
            '<pattern id="brief-unseen" width="7" height='
            + '"7" patternUnits="userSpaceOnUse"><rect widt'
            + 'h="7" height="7" fill="#ffffff"/>'
        )
        + '<circle cx="3.5" cy="3.5" r="1" fill="#777777"/></pattern></defs>'
    )
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
        + patterns
        + (
            '<rect width="1200" height="'
            + f"{page.height}"
            + '" fill="#ffffff"/><g font-family="Helvetica,'
            + 'Arial,sans-serif" fill="'
            + f"{BLACK}"
            + '">'
        )
        + (
            '<text x="20" y="23" font-family="Courier New'
            + ',Courier,monospace" font-size="18">CROSSTALK'
            + " / RESEARCH BRIEF</text>"
        )
        + (
            '<text x="20" y="65" font-family="Courier New'
            + ',Courier,monospace" font-size="34">'
            + f"{escape(page.title)}"
            + "</text>"
        )
        + f'<g fill="{RED}">'
        + paragraph((790, 30, 390, 50), "FOCUS: " + page.focus, 18)
        + "</g>"
        + line((20, 85, 1180, 85))
        + page.body
        + "</g></svg>"
    )
