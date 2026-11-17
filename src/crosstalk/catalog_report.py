"""Browsable local catalog atlas, with discovery and acquisition kept distinct."""

from __future__ import annotations

import html
import tempfile
from collections import Counter
from pathlib import Path

from crosstalk.catalog import CatalogIssue
from crosstalk.models import safe_directory


def build_catalog_atlas(root: Path) -> Path:
    """Read the normalized catalog and render its local metadata atlas."""
    rows = tuple(
        CatalogIssue.model_validate_json(line)
        for line in (root / "data/manifest/catalog.jsonl").read_text().splitlines()
    )
    return write_catalog_atlas(root, rows)


def write_catalog_atlas(root: Path, rows: tuple[CatalogIssue, ...]) -> Path:
    """Render metadata only; no inferred issue topics or full-archive claim."""
    years = Counter(
        row.issued_metadata[:4] for row in rows if row.issued_metadata and not row.flags
    )
    maximum = max(years.values(), default=1)
    bars = "".join(
        f'<div class="bar"><span>{year}</span><meter min="0" max="{maximum}" value="{count}"></meter><b>{count}</b></div>'
        for year, count in sorted(years.items())
    )
    items = "".join(
        "<tr><td>"
        + html.escape(row.issued_metadata or "Unknown")
        + '</td><td><a rel="noreferrer" href="'
        + html.escape(row.landing_url, quote=True)
        + '">'
        + html.escape(row.title)
        + "</a></td><td>"
        + html.escape(", ".join(row.flags) or "PDF locator pending review")
        + "</td></tr>"
        for row in sorted(rows, key=lambda item: (item.issued_metadata or "", item.issue_id))
    )
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CrossTalk archive atlas</title><style>
body{{font:17px system-ui;background:#f4f1e8;color:#142b38;max-width:1100px;margin:auto;padding:32px}}
h1{{font-size:44px}}p{{line-height:1.6}}.years{{columns:3;gap:25px}}
.bar{{display:flex;gap:12px;margin:9px 0;break-inside:avoid}}meter{{width:140px}}
input{{width:90%;padding:14px;font:inherit;margin:20px 0;border:1px solid #719099}}
table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}
a{{color:#00647c}}small{{color:#526675}}@media(max-width:700px){{.years{{columns:1}}body{{padding:18px}}}}
</style><h1>CrossTalk archive atlas</h1>
<p>{len(rows)} distinct catalog records captured from the official series listing on November 5, 2026.
This is catalog discovery, not a count of downloaded, analyzed, or all historically published issues.</p>
<p>Displayed issue dates need review. Conflicting or unavailable dates are excluded from the year bars.
Combined issues count as one catalog record. Categories require analysis of source PDFs.</p>
<h2>Records by displayed year</h2><div class="years">{bars}</div>
<h2>Explore the inventory</h2><label for="query">Filter title, date or review flag</label>
<input id="query" type="search" placeholder="Try 1993, special, July-August or conflict">
<small id="count">{len(rows)} records</small>
<table><thead><tr><th>Displayed date</th><th>Official issue record</th><th>Review state</th></tr></thead>
<tbody>{items}</tbody></table><script>
const input=document.getElementById('query');
input.addEventListener('input',()=>{{
 let shown=0; const q=input.value.toLowerCase();
 document.querySelectorAll('tbody tr').forEach(row=>{{
  row.hidden=!row.textContent.toLowerCase().includes(q); if(!row.hidden) shown++;
 }}); document.getElementById('count').textContent=shown+' records';
}});
</script></html>"""
    directory = safe_directory(root, "output/reports")
    target = directory / "catalog.html"
    if target.is_symlink():
        message = "catalog report target is a symlink"
        raise ValueError(message)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        _ = stream.write(document)
    temporary.chmod(mode)
    _ = temporary.replace(target)
    return target
