"""Describe coverage of distinct retained sources and page text layers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean, median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

FAMILY_SUPPORT = (2, 3, 5)


@dataclass(frozen=True, slots=True)
class IssueTopic:
    """Nine compatible family rates are compared on the same issue frame."""

    stratum: str
    counted: bool
    rates: tuple[float, ...]


def standardized_topic_gaps(rows: tuple[IssueTopic, ...], minimum: int) -> dict[str, object]:
    """Use one common stratum weighting for the counted and open PDFs."""
    if minimum < 1:
        raise ValueError("stratum support must be positive")
    groups: defaultdict[str, list[list[tuple[float, ...]]]] = defaultdict(lambda: [[], []])
    for row in rows:
        groups[row.stratum][int(row.counted)].append(row.rates)
    matched = {key: group for key, group in groups.items() if min(map(len, group)) >= minimum}
    excluded = sum(sum(map(len, group)) for key, group in groups.items() if key not in matched)
    if not matched:
        return {"groups": {}, "eligible_pdfs": 0, "outside_common_support": excluded, "gap": []}
    total = sum(sum(map(len, group)) for group in matched.values())
    differences: list[list[float]] = []
    for other, counted in matched.values():
        difference = [
            fmean(a) - fmean(b)
            for a, b in zip(zip(*counted, strict=True), zip(*other, strict=True), strict=True)
        ]
        differences.append([v * (len(other) + len(counted)) / total for v in difference])
    return {
        "groups": {
            key: {"uncounted": len(group[0]), "counted": len(group[1])}
            for key, group in sorted(matched.items())
        },
        "eligible_pdfs": total,
        "outside_common_support": excluded,
        "gap": [sum(parts) for parts in zip(*differences, strict=True)],
    }


def needle_gap(rows: Iterable[tuple[int, int, int, int]]) -> dict[str, object]:
    """Compare touched page rates within each PDF with both admitted layers."""
    sample = [(na, nr, oa, ore) for na, nr, oa, ore in rows if min(na, oa) >= 2]
    differences = [nr / na - ore / oa for na, nr, oa, ore in sample]
    return {
        "pdfs": len(sample),
        "native_pages": sum(na for na, _, _, _ in sample),
        "ocr_only_pages": sum(oa for _, _, oa, _ in sample),
        "mean_native_minus_ocr": fmean(differences) if differences else None,
        "median_native_minus_ocr": median(differences) if differences else None,
    }
