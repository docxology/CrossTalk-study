"""Pure holdings CSV, inert SVG and escaped HTML exports with explicit unknown coverage."""

from __future__ import annotations

import csv
import io
from html import escape
from itertools import chain
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crosstalk.holdings_records import ArticleIndexEntry, HoldingsRun, YearCoverage

LIMITS: Final = (
    "Independent listings describe captured evidence, not every historically published issue. "
    + "A title-period candidate is not a reviewed publication identity. Unlisted years remain "
    + "unknown; no monthly schedule is assumed. Listed-unmatched means absent from the compared "
    + "catalog, not proof that a PDF is irretrievable. Annual indexes include columns and notices; "
    + "their entries are not a reviewed article census. Tool text is not original HTTP bytes."
)


def _csv(header: tuple[str, ...], rows: Iterable[tuple[str, ...]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(chain((header,), rows))
    return stream.getvalue()


def coverage_csv(run: HoldingsRun) -> str:
    """Export exact annual observation counts, with unknown independent-listing coverage."""
    header = (
        "year",
        "assertion_observations",
        "distinct_period_candidates",
        "reviewed_matches",
        "title_period_candidates",
        "listed_unmatched",
        "ambiguous",
        "date_conflicts",
        "catalog_only_unreconciled",
        "independent_listing_coverage",
    )
    return _csv(
        header,
        (
            (
                str(row.year),
                str(row.assertion_observations),
                str(row.distinct_period_candidates),
                *(str(value) for value in _counts(row)),
                row.independent_listing_coverage,
            )
            for row in run.years
        ),
    )


def issues_csv(run: HoldingsRun) -> str:
    """Keep every source assertion and all candidate/reviewed catalog associations."""
    assertions = {row.assertion_id: row for row in run.assertions}
    return _csv(
        (
            "assertion_id",
            "source_id",
            "source_lines",
            "raw_label",
            "year",
            "months",
            "theme",
            "status",
            "candidate_issue_ids",
            "reviewed_issue_ids",
            "flags",
        ),
        (
            (
                row.assertion_id,
                assertions[row.assertion_id].source_id,
                ";".join(map(str, assertions[row.assertion_id].source_lines)),
                assertions[row.assertion_id].raw_label,
                str(row.year),
                ";".join(map(str, assertions[row.assertion_id].period.months)),
                assertions[row.assertion_id].theme or "",
                row.status,
                ";".join(row.candidate_issue_ids),
                ";".join(row.reviewed_issue_ids),
                ";".join(row.flags),
            )
            for row in run.matches
        ),
    )


def article_index_csv(entries: tuple[ArticleIndexEntry, ...]) -> str:
    """Export attributed publisher metadata without invented genres, pages or boundaries."""
    return _csv(
        (
            "entry_id",
            "source_url",
            "tool_lines",
            "publisher_section",
            "title",
            "byline",
            "issued_label",
            "printed_page",
            "genre",
            "boundary_status",
        ),
        (
            (
                row.entry_id,
                row.source_url,
                ";".join(map(str, row.source_lines)),
                row.category,
                row.title,
                row.byline,
                row.issued_label,
                row.printed_page or "",
                "unknown",
                row.boundary_status,
            )
            for row in entries
        ),
    )


def _counts(row: YearCoverage) -> tuple[int, ...]:
    return (
        row.reviewed_matches,
        row.title_period_candidates,
        row.listed_unmatched,
        row.ambiguous,
        row.date_conflicts,
        row.catalog_only_unreconciled,
    )


def coverage_svg(run: HoldingsRun) -> str:
    """Year by evidence-state heatmap; grey NA means unknown, not a zero or missing issue."""
    height = 155 + 25 * len(run.years)
    labels = ("Reviewed", "Candidate", "Listed unmatched", "Ambiguous", "Date conflict", "NPS only")
    colors = ("#26734d", "#386aa6", "#b76d10", "#7954a1", "#a83030", "#477e86")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" '
        + f'viewBox="0 0 1000 {height}">',
        "<title>Historical holdings: evidence states</title>",
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="20" y="28" font-size="22">Historical holdings: evidence states</text>',
        '<text x="20" y="51" font-size="13">Counts are source observations; '
        + "NA = no independent listing observed. No monthly expected grid.</text>",
    ]
    for index, label in enumerate(labels):
        svg.append(f'<text x="{145 + 139 * index}" y="82" font-size="13">{label}</text>')
    for index, row in enumerate(run.years):
        y = 96 + index * 25
        svg.append(f'<text x="25" y="{y + 17}" font-size="14">{row.year}</text>')
        for column, count in enumerate(_counts(row)):
            unknown = column < 5 and row.independent_listing_coverage == "unknown"
            fill = "#e6e6e6" if unknown else colors[column] if count else "#f4f7f9"
            label = "NA" if unknown else str(count)
            color = "white" if count and not unknown else "#263442"
            x = 130 + column * 139
            svg.extend(
                (
                    f'<rect x="{x}" y="{y}" width="130" height="22" fill="{fill}"/>',
                    f'<text x="{x + 61}" y="{y + 16}" text-anchor="middle" '
                    + f'font-size="13" fill="{color}">{label}</text>',
                )
            )
    svg.append(
        f'<text x="20" y="{height - 20}" font-size="12">'
        + "Unmatched/ambiguous/date-conflict observations stay separate; "
        + "no historical completeness percentage is estimated.</text></svg>"
    )
    return "".join(svg)


def holdings_html(run: HoldingsRun) -> str:
    """Escape every source-controlled field and keep coverage limitations visible."""
    assertions = {row.assertion_id: row for row in run.assertions}
    body = "".join(
        "<tr><td>"
        + escape(assertions[row.assertion_id].raw_label)
        + "</td><td>"
        + escape(assertions[row.assertion_id].theme or "")
        + "</td><td>"
        + row.status
        + "</td><td>"
        + escape(", ".join(row.candidate_issue_ids))
        + "</td></tr>"
        for row in run.matches
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Historical holdings</title>'
        + "<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto}td,th{"
        + "padding:.5rem;border-bottom:1px solid #ccc;text-align:left}img{max-width:100%}</style>"
        + "<h1>Historical holdings reconciliation</h1><p>"
        + escape(LIMITS)
        + "</p><p>Historical expected issue total: unknown. Assertions: "
        + str(len(run.assertions))
        + ". Catalog-only unreconciled records: "
        + str(len(run.catalog_only))
        + '.</p><img src="coverage.svg" alt="Annual evidence states">'
        + '<p><a href="coverage.csv">Year accounting CSV</a> | '
        + '<a href="issues.csv">All assertions CSV</a> | '
        + '<a href="article-index.csv">Publisher article-index entries</a></p>'
        + "<table><thead><tr><th>Source label</th><th>Theme</th><th>Match state</th>"
        + "<th>Catalog candidates</th></tr></thead><tbody>"
        + body
        + "</tbody></table></html>"
    )
