"""Pure parsing of retained publisher tool representations; no network or source writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from crosstalk.holdings_reconcile import parse_issue_period
from crosstalk.holdings_records import ArticleIndexEntry, HoldingsError, IssueAssertion

if TYPE_CHECKING:
    from crosstalk.holdings_records import SourceObservation

LINK = re.compile(r"\u3010(\d+)\u2020([^\u3011]+)\u3011")


@dataclass(frozen=True, slots=True)
class ToolLine:
    """One numbered line of a tool representation, not a raw HTTP source line."""

    line: int
    text: str


def clean_links(text: str) -> str:
    """Keep link labels while removing tool-specific link numbering."""
    return LINK.sub(lambda match: match[2], text).strip()


def _assertion(source: SourceObservation, rows: tuple[ToolLine, ...]) -> IssueAssertion:
    heading = rows[0]
    label = clean_links(heading.text).removeprefix("### ").removeprefix("## ").strip()
    period = parse_issue_period(label)
    if period is None:
        raise HoldingsError("explicit publisher issue heading has an unparsed period")
    link = LINK.search(heading.text)
    return IssueAssertion(
        assertion_id=f"{source.source_id}-l{heading.line}",
        source_id=source.source_id,
        source_lines=(heading.line,),
        raw_label=label,
        period=period,
        evidence_kind="current-issue" if source.format == "online-current" else "issue-listing",
        theme=next((clean_links(row.text) for row in rows[1:] if row.text.strip()), None),
        web_tool_link_id=int(link[1]) if link else None,
    )


def _stsc_assertions(
    source: SourceObservation, lines: tuple[ToolLine, ...]
) -> tuple[IssueAssertion, ...]:
    year = 0
    year_lines: tuple[int, ...] = ()
    result: list[IssueAssertion] = []
    for index, row in enumerate(lines):
        digits = lines[index : index + 4]
        if len(digits) == 4 and all(re.fullmatch(r"\d", value.text) for value in digits):
            year = int("".join(value.text for value in digits))
            year_lines = tuple(value.line for value in digits)
        if not year:
            continue
        for link in LINK.finditer(row.text):
            period = parse_issue_period(link[2] + " " + str(year))
            if period is not None:
                result.append(
                    IssueAssertion(
                        assertion_id=f"{source.source_id}-link{link[1]}",
                        source_id=source.source_id,
                        source_lines=(*year_lines, row.line),
                        raw_label=link[2],
                        period=period,
                        evidence_kind="issue-listing",
                        web_tool_link_id=int(link[1]),
                    )
                )
    return tuple(result)


def extract_assertions(
    source: SourceObservation, lines: tuple[ToolLine, ...]
) -> tuple[IssueAssertion, ...]:
    """Enumerate every explicit issue heading; no omitted month creates an assertion."""
    match source.format:
        case "stsc-back-issues":
            return _stsc_assertions(source, lines)
        case "online-back-issues" | "online-current":
            prefix = "### " if source.format == "online-back-issues" else "## "
            return tuple(
                _assertion(source, lines[index : index + 4])
                for index, row in enumerate(lines)
                if row.text.startswith(prefix)
                and parse_issue_period(clean_links(row.text.removeprefix(prefix))) is not None
            )
        case "article-index":
            return ()
        case _:
            assert_never(source.format)


def _entry(
    source: SourceObservation, rows: tuple[ToolLine, ...], category: str
) -> ArticleIndexEntry:
    cells = tuple(
        cell.strip() for cell in clean_links(" ".join(row.text for row in rows)).split("|")
    )
    link = LINK.search(rows[0].text)
    if link is None or len(cells) not in {3, 4}:
        raise HoldingsError("publisher article-index row has an unparsed column structure")
    issued = cells[2]
    year = re.search(r"/(199\d)/", source.original_url)
    period = parse_issue_period(
        issued if re.search(r"\d{4}", issued) else (issued + " " + year[1] if year else issued)
    )
    return ArticleIndexEntry(
        entry_id=f"{source.source_id}-link{link[1]}",
        source_id=source.source_id,
        source_url=source.capture_url,
        source_lines=tuple(row.line for row in rows),
        raw_lines=tuple(row.text for row in rows),
        category=category,
        title=link[2],
        byline=cells[1],
        issued_label=issued,
        period=period,
        printed_page=cells[3] if len(cells) == 4 else None,
        web_tool_link_id=int(link[1]),
    )


def extract_article_entries(
    source: SourceObservation, lines: tuple[ToolLine, ...]
) -> tuple[ArticleIndexEntry, ...]:
    """Retain all listed entries, including news, letters and recurring columns."""
    category = "unclassified publisher section"
    pending: list[ToolLine] = []
    result: list[ArticleIndexEntry] = []
    for row in lines[26:]:
        begins = LINK.search(row.text) is not None and "|" in row.text
        if pending and (
            begins
            or (
                "|" in pending[-1].text
                and len(clean_links(" ".join(value.text for value in pending)).split("|")) >= 3
            )
        ):
            result.append(_entry(source, tuple(pending), category))
            pending = []
        if begins or pending:
            pending.append(row)
        elif row.text and not row.text.startswith(("---", "*", "#")):
            category = clean_links(row.text)
    if pending:
        result.append(_entry(source, tuple(pending), category))
    return tuple(result)
