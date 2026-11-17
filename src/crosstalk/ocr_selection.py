"""Deterministic issue round-robin selection, using only verified prior outcomes."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, assert_never

from crosstalk.ocr_records import OcrError, SourceKind

if TYPE_CHECKING:
    from crosstalk.ocr_records import Task
    from crosstalk.ocr_resume import VerifiedPrior


Identity = tuple[SourceKind, str, str, str, int]


def _history(history: tuple[VerifiedPrior, ...]) -> tuple[Counter[Identity], set[Identity]]:
    """Completed outcomes exclude exact native-page versions; failures remain retryable."""
    attempts: Counter[Identity] = Counter()
    accepted: set[Identity] = set()
    for previous in history:
        source = previous.result.source
        key = (
            source.source_kind,
            source.pdf_sha256,
            source.native_artifact_sha256,
            source.native_page_sha256,
            source.page_index,
        )
        attempts[key] += 1
        match previous.result.status:
            case "ocr-produced" | "ocr-empty":
                accepted.add(key)
            case "engine-error" | "bound-refused":
                pass
            case _:
                assert_never(previous.result.status)
    return attempts, accepted


def select_tasks(
    candidates: tuple[Task, ...], history: tuple[VerifiedPrior, ...], maximum: int
) -> tuple[Task, ...]:
    """Reuse excludes completed pages; failed/limited pages retry after unattempted issue pages."""
    if not 1 <= maximum <= 500:
        raise OcrError("OCR page selection bound must be in [1, 500]")
    identity = tuple((row.pdf.sha256, row.page_index) for row in candidates)
    if len(set(identity)) != len(identity):
        raise OcrError("duplicate source pages cannot enter the OCR discovery queue")
    attempts, accepted = _history(history)
    groups: defaultdict[str, list[Task]] = defaultdict(list)
    for row in candidates:
        if (
            row.source_kind,
            row.pdf.sha256,
            row.native.sha256,
            row.native_page_sha256,
            row.page_index,
        ) not in accepted:
            groups[row.issue_id].append(row)
    for group in groups.values():
        group.sort(
            key=lambda row: (
                attempts[
                    row.source_kind,
                    row.pdf.sha256,
                    row.native.sha256,
                    row.native_page_sha256,
                    row.page_index,
                ],
                row.page_index,
            )
        )
    selected: list[Task] = []
    while len(selected) < maximum and groups:
        for issue_id in sorted(groups):
            selected.append(groups[issue_id].pop(0))
            if not groups[issue_id]:
                del groups[issue_id]
            if len(selected) == maximum:
                break
    return tuple(selected)
