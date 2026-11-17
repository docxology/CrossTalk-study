"""Escaped HTML presentation of explicitly exploratory analysis."""

from __future__ import annotations

import html
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from crosstalk.visual_report import visual_description, visual_failures_markup

if TYPE_CHECKING:
    from crosstalk.analysis_records import AnalysisSummary, VisualMetrics


def _visual_card(image: VisualMetrics) -> str:
    """Render a bounded PNG while retaining the encoded source and physical page context."""
    preview = (
        '<img loading="lazy" src="../../'
        + html.escape(image.preview.path, quote=True)
        + '" alt="Derived embedded-image thumbnail; semantic content not reviewed">'
        if image.preview is not None
        else "<p>PNG preview unavailable for this historical measurement.</p>"
    )
    pages = ", ".join(str(index + 1) for index in image.page_indexes)
    return (
        "<figure>"
        + preview
        + "<figcaption>"
        + f"{image.width} &times; {image.height}; grayscale entropy "
        + f"{image.grayscale_entropy_bits:.2f} bits; {image.occurrence_count} occurrences; "
        + "physical PDF pages "
        + pages
        + '; <a href="../../'
        + html.escape(image.path, quote=True)
        + '">original encoded asset</a>. Base raster; masks are uncomposited.'
        + "</figcaption></figure>"
    )


def _source_diagnostics(summary: AnalysisSummary) -> str:
    """Expose decoder methods and exact source failures as escaped observational evidence."""
    failures = "".join(
        "<tr><td>"
        + html.escape(row.issue_id)
        + "</td><td>"
        + html.escape(row.stage)
        + "</td><td><code>"
        + html.escape(row.path or "unavailable")
        + "</code></td><td>"
        + html.escape(row.error_type or "source check")
        + "</td><td>"
        + html.escape(row.reason)
        + ("; initial Pillow error: " + html.escape(row.initial_error) if row.initial_error else "")
        + "</td></tr>"
        for row in summary.unavailable_details
    )
    decoders = "".join(
        "<tr><td>"
        + html.escape(issue.issue_id)
        + "</td><td><code>"
        + html.escape(image.path)
        + "</code></td><td>"
        + html.escape(image.pixel_decoder)
        + "</td><td>"
        + html.escape(image.pixel_decoder_version)
        + "</td><td><code>"
        + html.escape(image.pixel_source_sha256 or "not required by standalone decoder")
        + "</code></td><td>"
        + str(image.pixel_source_page_index)
        + "</td><td>"
        + str(image.pixel_source_xref)
        + "</td><td>"
        + html.escape(image.pixel_decoder_initial_error or "none")
        + "</td></tr>"
        for issue in summary.issues
        for image in issue.images
    )
    return (
        "<section><h2>Pixel decoder provenance</h2><p>RGB thumbnails and grayscale entropy "
        + "depend on the decoder and color space. Native JPX fallback uses the recorded PDF "
        + "page and xref only after original encoded-byte agreement. External masks remain "
        + 'uncomposited.</p><div style="overflow:auto"><table id="pixel-decoders">'
        + "<thead><tr><th>Issue</th><th>Asset</th><th>Decoder</th><th>Version</th>"
        + "<th>PDF SHA-256</th><th>Physical page index</th><th>Xref</th>"
        + "<th>Initial error</th></tr></thead><tbody>"
        + decoders
        + '</tbody></table></div><h2>Unavailable source details</h2><table id="source-failures">'
        + "<thead><tr><th>Issue</th><th>Stage</th><th>Path</th><th>Error type</th>"
        + "<th>Reason</th></tr></thead><tbody>"
        + failures
        + "</tbody></table></section>"
    )


def write_report(root: Path, summary: AnalysisSummary, contact: str | None) -> None:
    """Render escaped exploratory measurements without certifying corpus completeness."""
    cards: list[str] = []
    for issue in summary.issues:
        terms = ", ".join(
            f"{html.escape(term.term)} ({term.count})" for term in issue.text.terms[:20]
        )
        labels = "".join(
            f"<li>{html.escape(hit.category)}: {html.escape(', '.join(hit.evidence_terms))}; PDF pages {', '.join(str(index + 1) for index in hit.page_indexes)}</li>"
            for hit in issue.categories
        )
        source = (
            f'<a href="{html.escape(issue.source_url, quote=True)}" rel="noreferrer">NPS source record</a>'
            if issue.source_url and issue.source_url.startswith("https://")
            else "Source metadata unavailable"
        )
        visuals = "".join(_visual_card(image) for image in issue.images[:12])
        cards.append(
            f"<article><h2>{html.escape(issue.title)}</h2><p>{html.escape(issue.issued or 'Date unavailable')} · {source}</p><p>{issue.pages} extracted pages · {issue.text.tokens:,} tokens · {issue.low_text_pages} low-text pages · {len(issue.images)} measured raster assets</p>{visual_description(issue)}<p>Frequent content terms: {terms or 'Unavailable'}</p><details><summary>Provisional category evidence</summary><ul>{labels}</ul></details><div class='gallery'>{visuals}</div></article>"
        )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in summary.limitations)
    sheet = (
        '<img class="sheet" src="../figures/contact_sheet.png" alt="Contact sheet of the first selected PDF pages, with issue and physical page labels">'
        if contact
        else ""
    )
    document = f"<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>CrossTalk corpus observatory</title><style>body{{font:17px system-ui;max-width:1100px;margin:auto;padding:32px;background:#f4f1e8;color:#142b38}}h1{{font-size:42px}}article{{background:white;padding:24px;margin:24px 0;border-radius:10px}}p,li{{line-height:1.6}}.gallery{{display:flex;flex-wrap:wrap}}figure{{margin:12px;width:210px}}img{{max-width:100%;height:auto}}figcaption{{font-size:13px}}.sheet{{max-width:720px}}a{{color:#00647c}}</style><h1>CrossTalk corpus observatory</h1><p>Exploratory issue-level analysis of {len(summary.issues)} source-distinct downloaded issues and {summary.corpus_text.tokens:,} extracted tokens. Corpus acquisition and review remain in progress.</p><ul>{limitations}</ul><p>Duplicate PDFs excluded: {html.escape(', '.join(summary.duplicate_issues) or 'none')}. Unavailable: {html.escape(', '.join(summary.unavailable_issues) or 'none')}.</p>{sheet}{''.join(cards)}</html>"
    document = document.replace(
        "</html>", _source_diagnostics(summary) + visual_failures_markup(summary) + "</html>"
    )
    target = root / "output/reports/analysis.html"
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        _ = stream.write(document)
    temporary.chmod(mode)
    _ = temporary.replace(target)
