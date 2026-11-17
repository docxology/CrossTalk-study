"""One physical-source admission rule for new source-linked lexical diagnostics."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crosstalk.study_language_records import SourceTextUnit


def source_units(units: Iterable[SourceTextUnit], maximum: int) -> tuple[SourceTextUnit, ...]:
    """Refuse ambiguous physical aliases and overlapping whole-page/region selection identities."""
    if maximum < 1:
        raise StudyError("diagnostic source-unit capacity must be positive")
    rows: list[SourceTextUnit] = []
    for row in units:
        if len(rows) >= maximum:
            raise StudyError("diagnostic source-unit capacity exceeded")
        rows.append(row)
    ordered = tuple(
        sorted(rows, key=lambda row: (row.layer, row.issue_id, row.page_index, row.unit_id))
    )
    if len({(row.layer, row.unit_id) for row in ordered}) != len(ordered):
        raise StudyError("duplicate diagnostic source unit")
    issue_pdf: dict[str, str] = {}
    pdf_issue: dict[str, str] = {}
    pages: dict[tuple[str, str, int], list[SourceTextUnit]] = defaultdict(list)
    for row in ordered:
        if issue_pdf.setdefault(row.issue_id, row.pdf_sha256) != row.pdf_sha256:
            raise StudyError("one diagnostic issue ID refers to multiple physical PDFs")
        if pdf_issue.setdefault(row.pdf_sha256, row.issue_id) != row.issue_id:
            raise StudyError("physical PDF aliases must be reconciled before diagnostics")
        pages[(row.layer, row.pdf_sha256, row.page_index)].append(row)
    for peers in pages.values():
        regions = {row.region_id for row in peers}
        if len(peers) > 1 and (None in regions or len(regions) != len(peers)):
            raise StudyError("whole-page/region duplication or repeated diagnostic region")
    return ordered


def unit_frame(rows: tuple[SourceTextUnit, ...]) -> str:
    """Match the existing LanguageRun framed sorted source serialization exactly."""
    digest = hashlib.sha256()
    for row in rows:
        raw = row.model_dump_json().encode()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()
