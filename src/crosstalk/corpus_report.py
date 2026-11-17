"""Searchable acquisition and extraction inventory from a current corpus index."""

from __future__ import annotations

import hashlib
import html
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from crosstalk.index_read import current_corpus_index
from crosstalk.index_records import CorpusIndexSummary
from crosstalk.models import AcquisitionError, safe_directory

if TYPE_CHECKING:
    from crosstalk.index_records import CorpusIndexRow


def _row(row: CorpusIndexRow) -> str:
    """Escape every source value and keep distinct observations in separate cells."""
    source = '<a rel="noreferrer" href="' + html.escape(row.landing_url, quote=True) + '">'
    source += html.escape(row.title) + "</a>"
    locator = (
        '<a rel="noreferrer" href="' + html.escape(row.pdf_url, quote=True) + '">PDF locator</a>'
        if row.pdf_url
        else "unresolved"
    )
    extraction = row.extraction.status
    if row.extraction.extracted_pages is not None:
        extraction += (
            f" ({row.extraction.extracted_pages}/{row.extraction.total_pages or '?'} pages)"
        )
    flags = ", ".join(row.flags)
    if row.duplicate_of_issue_id:
        flags += "; exact-byte duplicate of " + row.duplicate_of_issue_id
    if row.last_acquisition is not None:
        flags += "; last attempt: " + row.last_acquisition.status
    errors = "; ".join(value for value in (row.pdf.error, row.extraction.error) if value)
    return (
        "<tr>"
        + "".join(
            "<td>" + value + "</td>"
            for value in (
                html.escape(row.issued_metadata or "unknown"),
                source,
                locator,
                html.escape(row.pdf.integrity),
                html.escape(extraction),
                html.escape(flags.strip("; ") or "none"),
                html.escape(errors or "none"),
                "<code>" + html.escape(row.pdf.actual_sha256 or "unavailable") + "</code>",
            )
        )
        + "</tr>"
    )


def write_corpus_report(root: Path) -> Path:
    """Publish a dated snapshot while holding the same real acquisition/index lock."""
    with current_corpus_index(root) as rows:
        summary = CorpusIndexSummary.model_validate_json(
            (root / "data/processed/index/index-summary.jsonl").read_bytes()
        )
        body = "".join(_row(row) for row in rows)
        document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CrossTalk corpus acquisition index</title><style>
body{{font:16px system-ui;background:#f7f5ed;color:#142938;margin:auto;max-width:1500px;padding:30px}}
h1{{font-size:38px}}p{{line-height:1.6}}.metrics{{display:flex;gap:30px;flex-wrap:wrap;background:white;padding:20px}}
.metrics strong{{display:block;font-size:28px;color:#006e6d}}input{{font:inherit;padding:12px;width:90%;margin:18px 0}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #d8dfda}}
code{{font-size:11px;overflow-wrap:anywhere}}a{{color:#006e6d}}.scroll{{overflow-x:auto}}
</style><h1>CrossTalk corpus acquisition index</h1>
<p>Observed {html.escape(summary.observed_at)}. This source-bound snapshot retains every captured catalog identity.
An independent historical publication denominator is unknown; archive completeness remains unverified.
Rebuild after source changes. Full-text search covers only source-verified extracted pages.</p>
<div class="metrics"><div><strong>{summary.catalog_records}</strong>catalog records</div>
<div><strong>{summary.unresolved_locators}</strong>unresolved PDF locators</div>
<div><strong>{summary.verified_pdfs}</strong>verified local PDFs</div>
<div><strong>{summary.current_extractions}</strong>current extractions</div>
<div><strong>{summary.unavailable_pdfs}</strong>unavailable or invalid PDFs</div></div>
<p>Captured count matches the listing's own reported total: {summary.catalog_capture_matches_reported}.
Publication identities, duplicate PDF bytes, acquisition attempts and extraction scope are separate observations.
Corrupt or unavailable data are never counted as zero-byte success.</p>
<label for="filter">Filter title, metadata date, integrity, extraction or review flags</label>
<input id="filter" type="search"><p id="visible">{len(rows)} records</p>
<div class="scroll"><table><thead><tr><th>Date metadata</th><th>Official record</th><th>Locator</th>
<th>Local PDF integrity</th><th>Extraction scope</th><th>Flags / history</th><th>Errors</th><th>PDF SHA-256</th></tr></thead>
<tbody>{body}</tbody></table></div>
<p>Normalized index SHA-256: <code>{summary.content_sha256}</code>.
SQLite, JSONL, source bindings, missing-input observations and failure details are retained in
<code>data/processed/index/</code>. This report never authorizes a download or publication.</p>
<script>document.getElementById('filter').addEventListener('input',event=>{{
const query=event.target.value.toLowerCase();let visible=0;
document.querySelectorAll('tbody tr').forEach(row=>{{row.hidden=!row.textContent.toLowerCase().includes(query);if(!row.hidden)visible++;}});
document.getElementById('visible').textContent=visible+' records';}});</script></html>"""
        target = safe_directory(root, "output/reports") / "corpus-index.html"
        if target.is_symlink():
            raise AcquisitionError("corpus report path is a symlink")
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        payload = document.encode()
        if (
            target.is_file()
            and hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(payload).digest()
        ):
            return target
        descriptor, temporary = tempfile.mkstemp(prefix=".corpus-report-", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        _ = Path(temporary).replace(target)
        return target
