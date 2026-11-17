"""Issue-level association between phrase placement and front-page geometry."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Final

DRAWS: Final = 1999
SEED: Final = 180713
MINIMUM_STRATUM: Final = 5


@dataclass(frozen=True, slots=True)
class CrossModalIssue:
    """One exact issue with common visual and literal-phrase measurements."""

    pdf: str
    year: int
    role: str
    front_contrast: float
    topic_rates: tuple[float, ...]

    @property
    def stratum(self) -> tuple[int, str]:
        """Block the association by decade and reviewed front role."""
        return self.year // 10 * 10, self.role


@dataclass(frozen=True, slots=True)
class CrossModalAssociation:
    """Pooled and blocked Pearson correlations on identical PDFs."""

    pooled: float | None
    within_strata: float | None
    max_statistic_exceedance: float | None


@dataclass(frozen=True, slots=True)
class CrossModalStudy:
    """Association estimates, including eligibility and multiplicity accounting."""

    matched_pdfs: int
    analyzed_pdfs: int
    stratum_sizes: dict[str, int]
    below_gate_strata: dict[str, int]
    associations: dict[str, CrossModalAssociation]


def _unit(values: tuple[float, ...]) -> tuple[float, ...] | None:
    if not values or min(values) == max(values):
        return None
    mean = fmean(values)
    centered = tuple(value - mean for value in values)
    norm = math.sqrt(math.fsum(value * value for value in centered))
    return tuple(value / norm for value in centered) if norm else None


def _within(
    values: tuple[float, ...], groups: tuple[tuple[int, ...], ...]
) -> tuple[float, ...] | None:
    residual = list(values)
    for group in groups:
        block = tuple(values[index] for index in group)
        mean = block[0] if min(block) == max(block) else fmean(block)
        for index in group:
            residual[index] -= mean
    return _unit(tuple(residual))


def _correlation(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> float | None:
    if a is None or b is None:
        return None
    return max(-1.0, min(1.0, math.fsum(x * y for x, y in zip(a, b, strict=True))))


def _null_maxima(
    front: tuple[float, ...],
    text: tuple[tuple[float, ...], ...],
    groups: tuple[tuple[int, ...], ...],
) -> tuple[float, ...]:
    generator = random.Random(SEED)  # noqa: S311 -- Reproducible statistical randomization.
    maxima: list[float] = []
    for _ in range(DRAWS):
        shuffled = list(front)
        for group in groups:
            sample = [front[index] for index in group]
            generator.shuffle(sample)
            for index, value in zip(group, sample, strict=True):
                shuffled[index] = value
        maxima.append(
            max(abs(math.fsum(x * y for x, y in zip(shuffled, row, strict=True))) for row in text)
        )
    return tuple(maxima)


def cross_modal_associations(
    issues: tuple[CrossModalIssue, ...], families: tuple[str, ...]
) -> CrossModalStudy:
    """Residualize within calendar-role cells and replay joint within-cell permutations."""
    if len(set(families)) != len(families) or not families:
        raise ValueError("topic families must be nonempty and unique")
    identities = {row.pdf for row in issues}
    if len(identities) != len(issues):
        raise ValueError("duplicate issue PDF")
    cells: defaultdict[tuple[int, str], list[CrossModalIssue]] = defaultdict(list)
    for row in sorted(issues, key=lambda issue: issue.pdf):
        if (
            not math.isfinite(row.front_contrast)
            or len(row.topic_rates) != len(families)
            or any(not 0.0 <= value <= 1.0 for value in row.topic_rates)
        ):
            raise ValueError("invalid cross-modal measurements")
        cells[row.stratum].append(row)
    included: list[CrossModalIssue] = []
    groups: list[tuple[int, ...]] = []
    sizes: dict[str, int] = {}
    below: dict[str, int] = {}
    for (decade, role), rows in sorted(cells.items()):
        label = f"{decade}s {role}"
        if len(rows) < MINIMUM_STRATUM:
            below[label] = len(rows)
        else:
            groups.append(tuple(range(len(included), len(included) + len(rows))))
            included.extend(rows)
            sizes[label] = len(rows)
    group_indices = tuple(groups)
    front = tuple(row.front_contrast for row in included)
    topics = tuple(
        tuple(row.topic_rates[index] for row in included) for index in range(len(families))
    )
    front_unit = _unit(front)
    front_within = _within(front, group_indices)
    within = tuple(_within(topic, group_indices) for topic in topics)
    valid = tuple(row for row in within if row is not None)
    maxima = _null_maxima(front_within, valid, group_indices) if front_within and valid else ()
    associations: dict[str, CrossModalAssociation] = {}
    for name, topic, residual in zip(families, topics, within, strict=True):
        adjusted = _correlation(front_within, residual)
        exceedance = (
            (1 + sum(value + 1e-12 >= abs(adjusted) for value in maxima)) / (1 + len(maxima))
            if adjusted is not None and maxima
            else None
        )
        associations[name] = CrossModalAssociation(
            _correlation(front_unit, _unit(topic)), adjusted, exceedance
        )
    return CrossModalStudy(len(issues), len(included), sizes, below, associations)
