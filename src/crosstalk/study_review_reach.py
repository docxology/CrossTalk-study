"""Compare review reach with source-measured text and page geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, median, quantiles

GRID_CELLS = 16
MINIMUM_PAGES_PER_SIDE = 2
type InkGrid = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class InkPage:
    """One strict interior page with an already resolved reading flag."""

    reviewed: bool
    nonwhite: float
    grid: InkGrid


@dataclass(frozen=True, slots=True)
class IssueInkContrast:
    """Review-touched minus other strict interior pages from one PDF."""

    touched_pages: int
    other_pages: int
    nonwhite: float
    grid: InkGrid


def compare_issue(pages: tuple[InkPage, ...]) -> IssueInkContrast | None:
    """Compare equal-weight pages within each side of one retained PDF."""
    touched = tuple(row for row in pages if row.reviewed)
    other = tuple(row for row in pages if not row.reviewed)
    if any(
        len(row.grid) != GRID_CELLS
        or any(not math.isfinite(cell) or not 0 <= cell <= 1 for cell in (row.nonwhite, *row.grid))
        for row in pages
    ):
        raise ValueError("invalid strict appearance measurement")
    if min(len(touched), len(other)) < MINIMUM_PAGES_PER_SIDE:
        return None
    return IssueInkContrast(
        len(touched),
        len(other),
        fmean(row.nonwhite for row in touched) - fmean(row.nonwhite for row in other),
        tuple(
            fmean(r.grid[i] for r in touched) - fmean(r.grid[i] for r in other)
            for i in range(GRID_CELLS)
        ),
    )


def summarize_ink(issues: tuple[IssueInkContrast, ...]) -> dict[str, object]:
    """Describe the within-PDF contrasts with each eligible PDF weighted equally."""
    if len(issues) < 2:
        raise ValueError("at least two eligible PDFs are needed to summarize")
    values = [r.nonwhite for r in issues]
    return {
        "eligible_pdfs": len(issues),
        "touched_pages": sum(row.touched_pages for row in issues),
        "other_pages": sum(row.other_pages for row in issues),
        "mean_nonwhite_difference": fmean(values),
        "median_nonwhite_difference": median(values),
        "quartiles_nonwhite_difference": quantiles(values, n=4, method="inclusive"),
        "mean_grid_difference": [
            fmean(row.grid[index] for row in issues) for index in range(GRID_CELLS)
        ],
    }
