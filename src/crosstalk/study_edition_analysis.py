"""Paired topic profiles, front geometry, and count-register calibration."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Final

from crosstalk.statistical_bootstrap import percentile

RESAMPLES: Final = 2000
SEED: Final = 170912
MINIMUM_ISSUES: Final = 10


@dataclass(frozen=True, slots=True)
class PairedEstimate:
    """One contrast per eligible PDF, with conditional whole-PDF resampling."""

    issues: int
    mean: float | None
    lower: float | None
    upper: float | None


def paired_estimate(values: tuple[float, ...]) -> PairedEstimate:
    """Report the equal-PDF mean and, where eligible, its resampling range."""
    if any(not math.isfinite(value) for value in values):
        raise ValueError("nonfinite paired estimate")
    if not values:
        return PairedEstimate(0, None, None, None)
    if len(values) < MINIMUM_ISSUES:
        return PairedEstimate(len(values), fmean(values), None, None)
    generator = random.Random(SEED)  # noqa: S311 -- Deterministic descriptive resampling.
    draws = tuple(fmean(generator.choices(values, k=len(values))) for _ in range(RESAMPLES))
    return PairedEstimate(
        len(values), fmean(values), percentile(draws, 0.025), percentile(draws, 0.975)
    )


@dataclass(frozen=True, slots=True)
class CountAgreement:
    """Compare number of retrieval groups against an adjudicated denominator."""

    issues: int
    exact: int
    under: int
    over: int
    mean_absolute_count_difference: float
    maximum_absolute_count_difference: int


def count_agreement(counts: dict[str, tuple[int, int]]) -> CountAgreement:
    """Measure agreement, keeping count agreement distinct from title identity."""
    if not counts or any(actual < 0 or candidates < 0 for actual, candidates in counts.values()):
        raise ValueError("count comparisons need nonnegative verified and candidate totals")
    errors = tuple(candidate - actual for actual, candidate in counts.values())
    signs = Counter(0 if error == 0 else int(math.copysign(1, error)) for error in errors)
    return CountAgreement(
        len(errors),
        signs[0],
        signs[-1],
        signs[1],
        fmean(abs(error) for error in errors),
        max(abs(error) for error in errors),
    )


def partition_delta(admitted: tuple[int, int], interior: tuple[int, int]) -> float | None:
    """Compare interior rate with the disjoint complement of the admitted view."""
    all_hits, all_pages = admitted
    inner_hits, inner_pages = interior
    outer_hits, outer_pages = all_hits - inner_hits, all_pages - inner_pages
    if not 0 <= inner_hits <= inner_pages or not 0 <= outer_hits <= outer_pages:
        raise ValueError("topic profiles do not represent nested page partitions")
    if inner_pages == 0 or outer_pages == 0:
        return None
    return inner_hits / inner_pages - outer_hits / outer_pages


def contrast_by_group(rows: tuple[tuple[str, str, float], ...]) -> dict[str, PairedEstimate]:
    """Group one observation per exact PDF per analysis family or visual stratum."""
    groups: defaultdict[str, dict[str, float]] = defaultdict(dict)
    for group, pdf, value in rows:
        if pdf in groups[group]:
            raise ValueError("duplicate PDF within the same contrast group")
        groups[group][pdf] = value
    return {
        group: paired_estimate(tuple(values[pdf] for pdf in sorted(values)))
        for group, values in sorted(groups.items())
    }
