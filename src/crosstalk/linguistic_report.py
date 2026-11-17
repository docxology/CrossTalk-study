"""Escaped HTML presentation of page-bounded linguistic diagnostics."""

from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.linguistic_records import LinguisticRun, NGramProfile


def _adjacencies(profile: NGramProfile) -> str:
    """Render counted adjacencies and their exact eligible-window denominator."""
    rows = "".join(
        "".join(
            (
                f"<tr><td>{html.escape(' '.join(item.tokens))}</td><td>{item.count}</td>",
                f"<td>{item.per_1000_opportunities:.2f}</td><td>",
                f"{', '.join(str(index + 1) for index in item.page_indexes)}</td></tr>",
            )
        )
        for item in profile.frequencies
    )
    return (
        f"<h3>{profile.size}-grams</h3><p>{profile.opportunities:,} eligible within-page "
        f"positions; {profile.distinct_ngrams:,} distinct sequences.</p>"
        "<table><tr><th>Sequence</th><th>Count</th><th>Per 1,000 positions</th>"
        f"<th>PDF pages</th></tr>{rows}</table>"
    )


def write_linguistic_report(root: Path, run: LinguisticRun) -> None:
    """Atomically publish a source-linked report without interpreting the measurements."""
    cards: list[str] = []
    for issue in run.issues:
        measures = issue.measures
        terms = "".join(
            "".join(
                (
                    f"<tr><td>{html.escape(item.token)}</td><td>{item.count}</td>",
                    f"<td>{item.per_1000_tokens:.2f}</td></tr>",
                )
            )
            for item in measures.frequencies
        )
        page_rows: list[str] = []
        for page in measures.pages:
            ratio = page.diversity.mean_type_token_ratio
            diversity = f"{ratio:.3f}" if ratio is not None else "Insufficient data"
            page_rows.append(
                "".join(
                    (
                        f"<tr><td>{page.page_index + 1}</td>",
                        f"<td>{html.escape(page.page_label)}</td>",
                        f"<td>{page.tokens}</td><td>{page.types}</td><td>",
                        f"{page.diversity.complete_windows}</td><td>{diversity}</td>",
                        f"<td>{page.diversity.tokens_discarded}</td>",
                        f"<td>{html.escape(', '.join(page.quality))}</td></tr>",
                    )
                )
            )
        pages = "".join(page_rows)
        repeated = "".join(
            "".join(
                (
                    f"<li>{html.escape(item.normalized_line)} — ",
                    f"{len(item.page_indexes)}/{len(measures.pages)} pages ",
                    f"({item.page_fraction:.0%}); PDF pages ",
                    f"{', '.join(str(index + 1) for index in item.page_indexes)}</li>",
                )
            )
            for item in measures.boilerplate_candidates
        )
        source = (
            f'<a href="{html.escape(issue.source_url, quote=True)}">Source record</a>'
            if issue.source_url
            else "Source metadata unavailable"
        )
        cards.append(
            "".join(
                (
                    f"<article><h2>{html.escape(issue.title)}</h2><p>{source}; ",
                    f"{html.escape(issue.extraction_status)} extraction. PDF SHA-256: ",
                    f"<code>{issue.source_sha256}</code></p><p>{measures.tokens:,} word tokens; ",
                    f"{measures.types:,} types; {measures.complete_windows} complete ",
                    f"{run.settings.window_size}-token windows.</p><h3>Normalized frequencies</h3>",
                    "<table><tr><th>Token</th><th>Count</th><th>Per 1,000 words</th></tr>",
                    f"{terms}</table>{_adjacencies(measures.bigrams)}",
                    _adjacencies(measures.trigrams),
                    "<h3>Page distributions and fixed-window diversity</h3><table><tr>",
                    "<th>PDF page</th><th>PDF label</th>",
                    "<th>Tokens</th><th>Types</th><th>Windows</th>",
                    "<th>Mean window TTR</th><th>Tail discarded</th><th>Quality flags</th>",
                    f"</tr>{pages}</table><h3>Repeated-line candidates</h3>",
                    f"<p>{len(measures.boilerplate_candidates)} of ",
                    f"{measures.boilerplate_candidates_total} candidates shown; ",
                    f"all remain included in counts.</p><ul>{repeated}</ul></article>",
                )
            )
        )
    unavailable = "".join(
        f"<li>{html.escape(item.issue_id)}: {html.escape(item.reason)}</li>"
        for item in run.unavailable
    )
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in run.limitations)
    document = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>CrossTalk linguistic diagnostics</title><style>"
        "body{font:16px system-ui;margin:32px auto;max-width:1180px;padding:20px}"
        "table{border-collapse:collapse;width:100%;margin:16px 0}"
        "td,th{text-align:left;padding:7px;border-bottom:1px solid #ddd}"
        "article{margin-top:40px}code{overflow-wrap:anywhere}</style>"
        "<h1>CrossTalk linguistic diagnostics</h1>"
        f"<p>{len(run.issues)} source-distinct issues accepted from "
        f"{run.selected_issues}/{run.inventory_issues} extraction observations. "
        f"{html.escape(run.observed_at)}</p><ul>{limits}</ul>"
        f"<p>{html.escape(run.normalization)}. {html.escape(run.sampling)}. "
        f"{html.escape(run.adjacency)}.</p><p>Duplicate PDFs excluded: "
        f"{html.escape(', '.join(run.duplicate_issue_ids) or 'none')}.</p>"
        f"<h2>Unavailable observations</h2><ul>{unavailable}</ul>{''.join(cards)}</html>"
    )
    target = root / "output/reports/linguistics.html"
    if target.is_symlink():
        message = "linguistic report path is a symlink"
        raise ValueError(message)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        _ = stream.write(document)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(mode)
    _ = temporary.replace(target)
