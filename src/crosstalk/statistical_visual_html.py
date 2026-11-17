"""Escaped, self-contained statistical dashboard with portable SVG and CSV links."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.statistical_scope_report import native_visual_scope_markup

if TYPE_CHECKING:
    from crosstalk.index_records import IndexBinding
    from crosstalk.statistical_records import StatisticalRun
    from crosstalk.statistical_visual_records import (
        CoverageObservation,
        VisualFigure,
        VisualMetadata,
    )


@dataclass(frozen=True, slots=True)
class RenderedFigure:
    """Already escaped vector content and its content-addressed figure identity."""

    figure: VisualFigure
    svg: str


@dataclass(frozen=True, slots=True)
class DashboardInput:
    """A complete scientific report view, after current-source admission."""

    run: StatisticalRun
    metadata: VisualMetadata
    coverage: CoverageObservation
    figures: tuple[RenderedFigure, ...]
    bindings: tuple[IndexBinding, ...]
    missing: tuple[str, ...]


def _value(value: float | None) -> str:
    """A missing measurement is distinct from an observed zero."""
    return "Not available" if value is None else f"{value:.6g}"


def statistical_dashboard(document: DashboardInput) -> str:
    """Build a portable analytical report without external assets or active scripting."""
    run, proof = document.run, document.metadata
    cards = "".join(
        '<figure id="'
        + html.escape(row.figure.name)
        + '"><h2>'
        + html.escape(row.figure.title)
        + '</h2><div class="chart">'
        + row.svg
        + "</div><figcaption>"
        + html.escape(row.figure.caption)
        + '</figcaption><p class="small"><a href="../'
        + html.escape(row.figure.path.removeprefix("output/"))
        + '">Download vector SVG</a> · SHA-256 <code>'
        + row.figure.sha256
        + "</code></p></figure>"
        for row in document.figures
    )
    intervals = "".join(
        "<tr><th>"
        + html.escape(row.measure)
        + "</th><td>"
        + html.escape(row.status)
        + "</td><td>"
        + str(row.eligible_source_issue_units)
        + "</td><td>"
        + str(row.excluded_issue_units)
        + "</td><td>"
        + str(row.excluded_partial_issue_units)
        + "</td><td>"
        + str(row.excluded_unknown_coverage_issue_units)
        + "</td><td>"
        + str(row.excluded_metric_unavailable_issue_units)
        + "</td><td>"
        + _value(row.estimate)
        + "</td><td>"
        + _value(row.lower)
        + "</td><td>"
        + _value(row.upper)
        + "</td></tr>"
        for row in run.bootstrap
    )
    issue_coverage = "".join(
        '<tr data-issue-id="'
        + html.escape(row.issue_id, quote=True)
        + '" data-extracted-pages="'
        + str(row.pages)
        + '" data-total-pdf-pages="'
        + (str(row.total_pdf_pages) if row.total_pdf_pages is not None else "unknown")
        + '"><th>'
        + html.escape(row.issue_id)
        + "</th><td>"
        + html.escape(row.extraction_status)
        + "</td><td>"
        + str(row.pages)
        + "</td><td>"
        + (str(row.total_pdf_pages) if row.total_pdf_pages is not None else "Not available")
        + "</td><td>"
        + (
            f"{row.extracted_page_fraction:.1%}"
            if row.extracted_page_fraction is not None
            else "Not available"
        )
        + "</td></tr>"
        for row in run.issues
    )
    sources = "".join(
        "<tr><td>" + html.escape(row.path) + "</td><td><code>" + row.sha256 + "</code></td></tr>"
        for row in document.bindings
    )
    exports = "".join(
        '<li><a href="../data/'
        + html.escape(row.path.rsplit("/", 1)[-1])
        + '">'
        + html.escape(row.path.rsplit("/", 1)[-1])
        + "</a> <code>"
        + row.sha256
        + "</code></li>"
        for row in document.bindings
        if row.path.startswith("output/data/statistical_") and row.path.endswith(".csv")
    )
    notes = "".join("<li>" + html.escape(note) + "</li>" for note in run.limitations)
    missing = "".join(
        "<li><code>" + html.escape(path) + "</code></li>" for path in document.missing
    )
    coverage = (
        f"Captured catalog: {document.coverage.catalog_records}; "
        + f"listing reported {document.coverage.catalog_reported_total}. "
        + "Historical expected holdings remain unverified."
        if document.coverage.available
        else document.coverage.reason or "Catalog coverage unavailable."
    )
    return "\n".join(
        (
            '<!doctype html><html lang="en"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>CrossTalk · Statistical evidence</title><style>",
            "body{margin:0;background:#f6f4ef;color:#13293b;font:16px/1.6 system-ui,sans-serif}",
            "main{max-width:1120px;margin:auto;padding:36px 24px}",
            "h1{font-size:38px;line-height:1.2}",
            "h2{font-size:24px;color:#007574}header{border-top:6px solid #007574;padding-top:20px}",
            "figure,section{margin:32px 0;padding:24px;background:#fffdf8;"
            + "border:1px solid #d9e6e1}",
            ".chart,.table{overflow:auto}figcaption,.small{font-size:14px;color:#526168}",
            "table{border-collapse:collapse;width:100%}",
            "th,td{text-align:left;padding:10px;border-bottom:1px solid #d9e6e1}",
            "code{font-size:12px;overflow-wrap:anywhere}a{color:#006c6b}li{margin:8px 0}",
            ".status{background:#e6efeb;padding:18px}.status strong{color:#006c6b}",
            "@media print{figure,section{break-inside:avoid}"
            + ".chart svg{min-width:0!important;max-width:100%!important}}",
            "</style><main><header><p>CrossTalk / Captured-source statistical evidence</p>",
            "<h1>What the current corpus can support</h1>"
            + "<p>Descriptive observations and conditional issue-cluster diagnostics.</p>",
            '<p class="small">Observed ' + html.escape(run.observed_at) + "</p></header>",
            '<p class="status"><strong>'
            + str(len(run.issues))
            + " source-distinct accepted issues</strong> · "
            + str(len(run.pages))
            + " extracted physical pages · "
            + str(len(run.images))
            + " measured issue/raster-asset pairs. "
            + html.escape(coverage)
            + "</p>",
            "<p>All figures use the same full statistics receipt. "
            + "Page and image counts receive no sampling intervals. "
            + "Lexical intervals appear only when the declared eligible-issue gate is met; "
            + "this heuristic does not establish population validity.</p>",
            "<section><h2>Extraction scope and principal eligibility</h2><p>"
            + f"Complete-status issues: {run.complete_extraction_issue_units}; "
            + f"partial-status issues: {run.partial_extraction_issue_units}; "
            + f"unknown PDF-page coverage: {run.unknown_page_coverage_issue_units}. "
            + f"Principal eligible source issues: {run.principal_diagnostic_issue_units}. "
            + html.escape(run.principal_diagnostic_scope)
            + '</p><div class="table"><table id="issue-coverage"><thead><tr>'
            + "<th>Issue identity</th><th>Receipt status</th><th>Extracted pages</th>"
            + "<th>Total PDF pages</th><th>Extracted fraction</th></tr></thead><tbody>",
            issue_coverage,
            "</tbody></table></div><p>Descriptive charts retain partial extracted text and assets. "
            + "A complete receipt status alone does not establish known full-page coverage. "
            + "These fractions measure extracted PDF pages, not OCR accuracy or article "
            + "coverage.</p></section>",
            native_visual_scope_markup(run),
            cards,
            '<section><h2>Diagnostic eligibility and estimates</h2><div class="table"><table>',
            "<thead><tr><th>Estimand</th><th>Status</th><th>Eligible source issues</th>"
            + "<th>Excluded issues</th><th>Partial status excluded</th>"
            + "<th>Unknown coverage excluded</th><th>Unavailable metric excluded</th>"
            + "<th>Estimate</th><th>Lower</th>"
            + "<th>Upper</th></tr></thead><tbody>",
            intervals,
            "</tbody></table></div><p>Bounds are conditional percentile diagnostics, not p values. "
            + "A zero-width diagnostic can occur for constant observed values "
            + "and does not establish population certainty. Exclusion counts partition "
            + "all omitted issues: partial status first, then unknown full-page coverage, "
            + "then an unavailable metric among complete-coverage issues.</p></section>",
            '<section><h2>Machine-readable data</h2><p><a href="statistics.jsonl">'
            + "Full typed statistics JSONL</a> is the authoritative result. "
            + "CSV projections are linked with their observed content digests.</p><ul>",
            exports,
            "</ul></section><section><h2>Limitations and rival explanations</h2><ul>",
            notes,
            "</ul></section><section><h2>Reproducibility</h2>"
            + "<p>Regenerate after any source or configuration change. "
            + "This static document records an observation; it cannot monitor later edits.</p>",
            "<p>Statistics SHA-256 <code>" + proof.statistics_sha256 + "</code></p>",
            "<p>Statistical implementation <code>"
            + proof.statistical_implementation_sha256
            + "</code></p>",
            "<p>Rendering implementation <code>"
            + proof.rendering_implementation_sha256
            + "</code></p>",
            "<p>Input snapshot <code>" + proof.input_snapshot_sha256 + "</code></p>",
            "<details><summary>Declared diagnostic settings</summary><pre>"
            + html.escape(proof.settings.model_dump_json(indent=2))
            + "</pre></details>",
            '<details><summary>Exact current input files</summary><div class="table">'
            + "<table><thead><tr><th>Path</th><th>SHA-256</th></tr></thead><tbody>",
            sources,
            "</tbody></table></div></details><details>"
            + "<summary>Explicit absent inputs</summary><ul>",
            missing,
            "</ul></details></section></main></html>",
        )
    )
