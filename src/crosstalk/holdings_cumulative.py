"""Retained cumulative-index entries and period supports, without duplicate-article claims."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from crosstalk.case_files import read_bytes
from crosstalk.holdings_parse import ToolLine
from crosstalk.holdings_reconcile import parse_issue_period
from crosstalk.holdings_records import (
    Digest,
    HoldingsError,
    HoldingsRecord,
    IssuePeriod,
)

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_ID: Final = "stsc-cumulative-1992-1994"
SOURCE_URL: Final = (
    "https://web.archive.org/web/19970708112229/"
    + "http://www.stsc.hill.af.mil/CrossTalk/1994/jun/xt94d06l.html"
)
NUMBERED: Final = re.compile(r"^L(\d+): (.*)$", re.MULTILINE)
LEADERS: Final = re.compile(r"\.{2,}")
ENDING: Final = re.compile(
    r"\b(?P<label>(?:April/May|June/July|January|February|March|April|May|June|July|"
    + r"August|September|October|November|December|Special)\s+(?:1992|1993|1994))\s*$"
)


class CumulativeEntry(HoldingsRecord):
    """One source-index observation; neither a linked article nor an adjudicated identity."""

    entry_id: str
    source_url: str = SOURCE_URL
    source_lines: tuple[int, ...] = Field(min_length=1, max_length=12)
    raw_lines: tuple[str, ...] = Field(min_length=1, max_length=12)
    category: str
    title: str
    byline: str
    issued_label: str
    period: IssuePeriod
    printed_page: None = None
    genre: None = None
    article_url: None = None
    web_tool_link_id: None = None
    normalization_notes: tuple[str, ...]
    boundary_status: Literal["publisher-listed-entry-unreviewed"] = (
        "publisher-listed-entry-unreviewed"
    )


class CumulativePeriodSupport(HoldingsRecord):
    """Dates explicitly printed on entry rows; not extra issues added to another inventory."""

    period: IssuePeriod
    supporting_entry_ids: tuple[str, ...]
    source_lines: tuple[int, ...]


class CumulativeIndex(HoldingsRecord):
    """Finite full tool-capture parsing, with historical and duplicate boundaries explicit."""

    source_id: Literal["stsc-cumulative-1992-1994"] = SOURCE_ID
    source_url: str = SOURCE_URL
    source_capture_sha256: Digest
    source_representation: Literal["web-tool-extracted-text"] = "web-tool-extracted-text"
    total_tool_lines: Literal[326] = 326
    history_source_lines: tuple[int, ...] = (26, 27, 28, 29)
    history_text_sha256: Digest
    entries: tuple[CumulativeEntry, ...]
    period_supports: tuple[CumulativePeriodSupport, ...]
    article_census_complete: Literal[False] = False
    unique_article_count: None = None
    historical_issue_total: None = None


def _entry(rows: tuple[ToolLine, ...], category: str) -> CumulativeEntry:
    if not rows:
        raise HoldingsError("cumulative entry requires at least one observed source line")
    first, last = rows[0], rows[-1]
    ending = ENDING.search(last.text)
    if ending is None:
        raise HoldingsError("cumulative entry lacks its explicit terminal date label")
    prefix = last.text[: ending.start()].strip()
    separators = tuple(LEADERS.finditer(prefix))
    notes = ["dot-leader-and-wrap-normalization-unreviewed"]
    if separators:
        separator = separators[-1]
        title_part, byline = prefix[: separator.start()], prefix[separator.end() :]
    elif last.line == 166 and prefix.startswith(".") and len(rows) > 1:
        title_part, byline = "", prefix[1:]
        notes.append("single-leading-dot-source-line-166")
    elif last.line == 317 and prefix.endswith(".Robert Bliss"):
        title_part, _separator, byline = prefix.rpartition(".")
        notes.append("single-dot-author-separator-source-line-317")
    else:
        raise HoldingsError("cumulative title/byline delimiter is unresolved")
    title_parts = [re.sub(r"\.{4,}$", "", row.text.strip()).strip() for row in rows[:-1]]
    title = " ".join((*title_parts, title_part.strip())).strip()
    label = " ".join(ending["label"].split())
    if label.startswith("Special "):
        period = IssuePeriod(year=int(label[-4:]), months=(), kind="special")
        notes.append("source-special-label-no-month")
    else:
        period = parse_issue_period(label)
    if not title or not byline.strip() or period is None:
        raise HoldingsError("cumulative entry lacks title, byline or a parseable explicit date")
    return CumulativeEntry(
        entry_id=f"{SOURCE_ID}-l{first.line}-{last.line}",
        source_lines=tuple(row.line for row in rows),
        raw_lines=tuple(row.text for row in rows),
        category=category,
        title=title,
        byline=byline.strip(),
        issued_label=label,
        period=period,
        normalization_notes=tuple(notes),
    )


def _listed_entries(lines: tuple[ToolLine, ...]) -> tuple[CumulativeEntry, ...]:
    """Preserve source sections and wraps while requiring every terminal date."""
    category = ""
    pending: list[ToolLine] = []
    entries: list[CumulativeEntry] = []
    for row in lines[30:325]:
        if not row.text.strip():
            continue
        if not row.text.startswith(" "):
            if pending:
                raise HoldingsError("cumulative section changed before an entry's terminal date")
            category = row.text.strip()
            continue
        pending.append(row)
        if ENDING.search(row.text):
            entries.append(_entry(tuple(pending), category))
            pending = []
    if pending or len(entries) != 194 or any(not row.category for row in entries):
        raise HoldingsError("cumulative rows do not account for the exact194 dated source entries")
    return tuple(entries)


def parse_cumulative_capture(raw: bytes, expected_sha256: str) -> CumulativeIndex:
    """Parse the retained 326-line observation, preserving all 194 publisher-listed rows."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise HoldingsError(
            "cumulative tool capture differs from the independently supplied digest"
        )
    text = raw.decode("utf-8")
    if SOURCE_URL not in text:
        raise HoldingsError("cumulative source observation lacks its exact attributed capture URL")
    lines = tuple(ToolLine(line=int(match[1]), text=match[2]) for match in NUMBERED.finditer(text))
    if tuple(row.line for row in lines) != tuple(range(326)):
        raise HoldingsError(
            "cumulative tool line coverage is duplicated, incomplete or out of order"
        )
    entries = _listed_entries(lines)
    by_period: dict[IssuePeriod, list[CumulativeEntry]] = {}
    for entry in entries:
        by_period.setdefault(entry.period, []).append(entry)
    supports = tuple(
        CumulativePeriodSupport(
            period=period,
            supporting_entry_ids=tuple(row.entry_id for row in rows),
            source_lines=tuple(line for row in rows for line in row.source_lines),
        )
        for period, rows in by_period.items()
    )
    history = "\n".join(lines[index].text for index in (26, 27, 28, 29))
    return CumulativeIndex(
        source_capture_sha256=digest,
        history_text_sha256=hashlib.sha256(history.encode()).hexdigest(),
        entries=tuple(entries),
        period_supports=supports,
    )


def read_cumulative_capture(path: Path, expected_sha256: str) -> CumulativeIndex:
    """Read only bounded ordinary single-link evidence; never follow a capture alias or pipe."""
    return parse_cumulative_capture(read_bytes(path, 1_000_000), expected_sha256)
