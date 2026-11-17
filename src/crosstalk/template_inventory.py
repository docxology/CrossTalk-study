"""Compact source-unit tables retain every row and the original machine-readable CSV."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from crosstalk.template_io import digest
from crosstalk.template_records import ProjectionError

INVENTORY_HEADER: Final = (
    "source_family",
    "issue_id",
    "title",
    "issued",
    "pages",
    "status",
    "source_url",
    "pdf_sha256",
)
_TEX: Final = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex(value: str) -> str:
    """Render source-owned plain text as text, never as executable TeX."""
    return "".join(_TEX.get(char, char) for char in value)


@dataclass(frozen=True, slots=True)
class InventoryRow:
    """A declared PDF-source unit, never an automatically inferred article boundary."""

    family: str
    issue_id: str
    title: str
    issued: str
    pages: str
    status: str
    source_url: str
    pdf_sha256: str


def parse_inventory(raw: bytes) -> tuple[InventoryRow, ...]:
    """Keep missing page/date/digest observations missing, and refuse duplicate unit identities."""
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(next(reader, ())) != INVENTORY_HEADER:
        raise ProjectionError("unsupported source inventory CSV header")
    rows: list[InventoryRow] = []
    seen: set[tuple[str, str]] = set()
    for index, fields in enumerate(reader, 1):
        if index > 25000 or len(fields) != len(INVENTORY_HEADER):
            raise ProjectionError("source inventory exceeds bounds or has malformed rows")
        if any(len(value) > 2000 or any(ord(char) < 32 for char in value) for value in fields):
            raise ProjectionError(
                "source inventory field is oversized or contains control characters"
            )
        row = InventoryRow(*fields)
        identity = row.family, row.issue_id
        if not all((row.family, row.issue_id, row.title, row.status)) or identity in seen:
            raise ProjectionError("source inventory has missing or duplicate source-unit identity")
        seen.add(identity)
        if row.pages and re.fullmatch(r"0|[1-9][0-9]{0,5}", row.pages) is None:
            raise ProjectionError("page observations must be nonnegative integers or missing")
        if row.pdf_sha256:
            _ = digest(row.pdf_sha256)
        if row.source_url:
            url = urlsplit(row.source_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.netloc
                or url.username
                or url.password
            ):
                raise ProjectionError(
                    "source locator must be a public HTTP(S) URL without credentials"
                )
        rows.append(row)
    return tuple(rows)


def _short(value: str, width: int) -> str:
    """Short display aids are explicit; complete values remain in the exact retained CSV."""
    return latex(value if len(value) <= width else value[:width] + "…")


def inventory_table(rows: tuple[InventoryRow, ...], csv_path: str) -> str:
    """Typeset every source row in an eight-column 7.5-point appendix."""
    lines = [
        r"\begingroup",
        r"\fontsize{7.5}{9}\selectfont",
        r"\setlength{\tabcolsep}{2pt}",
        r"\renewcommand{\arraystretch}{0.93}",
        r"\begin{longtable}{@{}p{.065\linewidth}p{.10\linewidth}p{.35\linewidth}"
        + r"p{.095\linewidth}p{.04\linewidth}p{.095\linewidth}p{.05\linewidth}p{.12\linewidth}@{}}",
        r"\caption{Declared acquired-source inventory. IDs and SHA prefixes are display aids; "
        + r"the retained CSV contains complete identities, locators and digests.}\\",
        r"\toprule Family & Source ID & Issue title & Date & pp. & Status & Link & PDF SHA\\",
        r"\midrule\endfirsthead",
        r"\toprule Family & Source ID & Issue title & Date & pp. & Status & Link & PDF SHA\\",
        r"\midrule\endhead",
        r"\midrule\multicolumn{8}{r}{Continued on the next page}\\\endfoot",
        r"\bottomrule\endlastfoot",
    ]
    for row in rows:
        url = latex(row.source_url)
        link = rf"\href{{{url}}}{{URL}}" if row.source_url else "NA"
        lines.append(
            " & ".join(
                (
                    _short(row.family, 6),
                    _short(row.issue_id, 10),
                    latex(row.title),
                    latex(row.issued or "NA"),
                    row.pages or "NA",
                    latex(row.status),
                    link,
                    r"\texttt{" + (row.pdf_sha256[:12] if row.pdf_sha256 else "NA") + "}",
                )
            )
            + r" \\"
        )
    lines.extend(
        (
            r"\end{longtable}",
            r"\endgroup",
            "",
            "Full CSV: `"
            + csv_path
            + "`. This table describes the declared acquired frame; "
            + "it does not establish a complete historical publication census or an article count.",
        )
    )
    return "\n".join(lines)
