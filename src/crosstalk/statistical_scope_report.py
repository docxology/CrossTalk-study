"""Explicit separate text/pixel denominators for analytical HTML and dossier prose."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.statistical_records import StatisticalRun


def native_visual_scope_text(run: StatisticalRun) -> str:
    """An old mixed receipt cannot establish new text-only or pixel-coverage denominators."""
    if run.method_version != "3":
        return "Historical mixed cohort; independent native-text and visual coverage unavailable."
    unknown_entries = sum(issue.unknown_native_inventory_pages or 0 for issue in run.issues)
    return (
        f"Accepted native-text source issues: {run.native_text_issue_units}; "
        + f"issues with measured pixels: {run.pixel_measured_issue_units}; "
        + f"complete declared raster scope: {run.visual_complete_scope_issue_units}; "
        + f"partial visual scope: {run.visual_partial_issue_units}; "
        + f"unavailable visual scope: {run.visual_unavailable_issue_units}. "
        + f"Native inventory entry counts are unavailable on {unknown_entries} physical pages. "
        + "Known entries may include degenerate metadata placeholders; they are not semantic "
        + "image or figure totals. Visual missingness preserves independently accepted native text."
    )


def native_visual_scope_markup(run: StatisticalRun) -> str:
    """Expose per-issue scope as escaped evidence, without turning missing counts into zero."""
    rows = "".join(
        "<tr><th>"
        + html.escape(issue.issue_id)
        + "</th><td>"
        + html.escape(issue.visual_status)
        + "</td><td>"
        + (
            str(issue.measured_distinct_assets)
            if issue.measured_distinct_assets is not None
            else "Not available"
        )
        + "</td><td>"
        + str(issue.saved_distinct_assets)
        + "</td><td>"
        + (
            str(issue.native_inventory_entries)
            if issue.native_inventory_entries is not None
            else "Not available"
        )
        + "</td><td>"
        + (
            str(issue.unavailable_reference_pages)
            if issue.unavailable_reference_pages is not None
            else "Not available"
        )
        + "</td></tr>"
        for issue in run.issues
    )
    return (
        "<section><h2>Separate native and visual scope</h2><p>"
        + html.escape(native_visual_scope_text(run))
        + '</p><div class="table"><table id="native-visual-scope"><thead><tr>'
        + "<th>Issue</th><th>Visual status</th><th>Measured assets</th>"
        + "<th>Recorded saved assets</th><th>Native inventory entries</th>"
        + "<th>Reference-unavailable pages</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></div><p>Unavailable assets remain explicit in the independently bound "
        + '<a href="analysis.html">baseline analysis report</a>. Pixel distributions concern known '
        + "recorded saved candidates; unavailable reference frames can contain "
        + "unknown additional entries.</p></section>"
    )
