"""Escaped native availability and conditional layer diagnostics with explicit denominators."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.native_layer_records import NativeLayerRun, NativeLayerVariant


def _number(value: float | None) -> str:
    """Undefined rates and bounds remain visible as unavailable."""
    return "Not available" if value is None else f"{value:.6g}"


def _variant(variant: NativeLayerVariant) -> str:
    """Each view shows its own eligible frame; identical seeds do not imply identical samples."""
    cohort = variant.cohort
    intervals = "".join(
        "<tr><td>"
        + html.escape(interval.measure)
        + "</td><td>"
        + html.escape(interval.weighting)
        + f"</td><td>{len(interval.eligible_issue_ids)}</td><td>"
        + html.escape(interval.status)
        + "</td><td>"
        + _number(interval.estimate)
        + "</td><td>"
        + _number(interval.lower)
        + "</td><td>"
        + _number(interval.upper)
        + "</td></tr>"
        for interval in cohort.intervals
    )
    periods = "".join(
        f"<tr><td>{row.unit}</td><td>{row.period_start}</td>"
        + f"<td>{row.observed_issue_units}</td><td>{row.complete_extraction_issue_units}</td>"
        + f"<td>{row.partial_extraction_issue_units}</td>"
        + f"<td>{row.zero_native_token_issue_units}</td>"
        + f"<td>{row.physical_pdf_pages}</td><td>{row.selected_native_pages}</td>"
        + f"<td>{row.native_tokens}</td></tr>"
        for row in cohort.metadata_periods
    )
    return (
        "<section><h2>"
        + html.escape(variant.label)
        + "</h2><p>Observed source issues: "
        + str(len(cohort.observed_issue_ids))
        + "; workflow-selected issues: "
        + str(len(cohort.workflow_selected_issue_ids))
        + "; complete positive-token eligible issues: "
        + str(len(cohort.eligible_complete_nonzero_issue_ids))
        + f"; selected physical native pages: {cohort.observed_physical_pages}; "
        + f"native tokens: {cohort.observed_native_tokens}; "
        + f"zero-native-token issues: {len(cohort.zero_native_token_issue_ids)}.</p>"
        + "<p>"
        + html.escape(variant.interval_scope)
        + ". "
        + html.escape(variant.comparison_limit)
        + ". Resetting a seed pairs resamples only when eligible IDs are identical.</p>"
        + "<details><summary>Actual eligible issue IDs</summary><p>"
        + html.escape(", ".join(cohort.eligible_complete_nonzero_issue_ids) or "None")
        + "</p></details><table><thead><tr><th>Lexicon measure</th><th>Weighting</th>"
        + "<th>Eligible issues</th><th>Status</th><th>Estimate</th><th>Lower</th><th>Upper</th>"
        + "</tr></thead><tbody>"
        + intervals
        + "</tbody></table><h3>Native availability by repository metadata period</h3>"
        + "<p>Groups follow repository metadata dates and native eligibility. "
        + "Printed publication dates remain unverified. "
        + "Unknown/conflicting date issues excluded from temporal groups: "
        + str(len(cohort.unknown_or_conflicting_date_issue_ids))
        + ".</p><table><thead><tr><th>Metadata unit</th><th>Start</th><th>Issues</th>"
        + "<th>Complete</th><th>Partial</th><th>Native-zero</th><th>PDF pages</th>"
        + "<th>Selected native pages</th><th>Native tokens</th></tr></thead><tbody>"
        + periods
        + "</tbody></table></section>"
    )


def render_native_layers(run: NativeLayerRun) -> str:
    """Render source-bound observations without claiming wrapper or transcription accuracy."""
    issues = "".join(
        "<tr><th>"
        + html.escape(issue.issue_id)
        + "</th><td>"
        + html.escape(issue.title)
        + f"</td><td>{issue.raw_tokens}</td><td>{issue.wrapper_minus_tokens}</td>"
        + "<td>"
        + html.escape(
            ", ".join(str(index) for index in issue.matched_wrapper_page_indexes) or "None"
        )
        + '</td><td><a href="../../'
        + html.escape(issue.evidence_path, quote=True)
        + '">Exact rule/page/line evidence</a></td></tr>'
        for issue in run.issues
    )
    failures = "".join(
        "<li>" + html.escape(row.issue_id + ": " + row.reason) + "</li>" for row in run.unavailable
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        + "<title>CrossTalk native layers</title>"
        + "<style>body{font:16px/1.6 system-ui;max-width:1150px;margin:auto;padding:30px}"
        + "table{border-collapse:collapse;width:100%}"
        + "th,td{padding:8px;border-bottom:1px solid #ccd}"
        + "section{margin:35px 0}code{overflow-wrap:anywhere}</style>"
        + "<h1>Native text: raw and reversible sensitivity views</h1><p>"
        + html.escape(run.scope)
        + ". Source kind: "
        + html.escape(run.settings.source_kind)
        + f". Accepted source-distinct issues: {len(run.issues)}; "
        + f"selected: {len(run.selected_issue_ids)}; deferred: {len(run.deferred_issue_ids)}.</p>"
        + "<p>Raw lexical metrics remain. Only exact independently attributed wrapper matches "
        + "are excluded in the named derivative. Candidate pages remain included. Zero-body "
        + "denominators give unavailable rates. Workflow thresholds and bootstrap gates are "
        + "heuristics; template, OCR and transcription accuracy are unmeasured. No causal or "
        + "across-view difference "
        + "inference, p values or joint interval coverage is claimed.</p>"
        + "<table><thead><tr><th>Issue</th><th>Metadata title</th><th>Raw tokens</th>"
        + "<th>Wrapper-minus tokens</th><th>Excluded physical indexes</th><th>Evidence</th>"
        + "</tr></thead><tbody>"
        + issues
        + "</tbody></table>"
        + "".join(_variant(variant) for variant in run.variants)
        + "<section><h2>Unavailable observations</h2><ul>"
        + failures
        + "</ul></section></html>"
    )
