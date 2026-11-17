"""Escaped presentation of visual missingness, independently from accepted native text."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.analysis_records import AnalysisSummary, IssueAnalysis


def visual_description(issue: IssueAnalysis) -> str:
    """Historical tuples never acquire current empty-inventory coverage through rendering."""
    visual = issue.visual
    if visual is None:
        return "<p>Historical mixed measurement; explicit current visual coverage unavailable.</p>"
    entries = (
        str(visual.native_inventory_entries)
        if visual.native_inventory_entries is not None
        else f"unknown; known subtotal {visual.known_native_inventory_entry_sum}"
    )
    return (
        "<p>Visual status: "
        + html.escape(visual.status)
        + f". Measured saved raster assets: {visual.measured_assets}"
        + f"/{visual.saved_asset_candidates}. "
        + "Native inventory entries: "
        + entries
        + f"; {visual.unknown_native_inventory_pages} pages lack entry counts; "
        + f"{visual.unavailable_reference_pages} pages lack reference classification. "
        + "Inventory entries include possible metadata placeholders "
        + "and are not semantic figure totals.</p>"
    )


def visual_failures_markup(summary: AnalysisSummary) -> str:
    """Local asset failures remain visible alongside every independently accepted peer."""
    rows = "".join(
        "<tr><td>"
        + html.escape(issue.issue_id)
        + "</td><td>"
        + html.escape(failure.stage)
        + "</td><td><code>"
        + html.escape(failure.path or "unavailable")
        + "</code></td><td>"
        + html.escape(failure.reason)
        + (
            "; initial decoder error: " + html.escape(failure.initial_error)
            if failure.initial_error
            else ""
        )
        + "</td></tr>"
        for issue in summary.issues
        if issue.visual is not None
        for failure in issue.visual.failures
    )
    return (
        "<section><h2>Unavailable raster assets</h2><p>These asset observations do not exclude "
        + 'independently accepted native text.</p><table id="visual-asset-failures">'
        + "<thead><tr><th>Issue</th><th>Stage</th><th>Asset</th><th>Reason</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></section>"
    )
