"""Coverage-aware weighted page stacks preserve original layout without registration or cropping."""

from __future__ import annotations

import hashlib
import math
import sys
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import __version__ as pillow_version

from crosstalk.atlas_ghost_records import GhostAggregate, GhostIssueWeight, GhostMaps, GhostPlan
from crosstalk.atlas_lineage import implementation_digest
from crosstalk.atlas_pixels import NormalizedPage, normalize_page
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from crosstalk.atlas_records import PageImage, PageTransform


@dataclass(frozen=True, slots=True)
class _Accumulator:
    """Finite working arrays are never accepted as a published scientific record."""

    support: list[float]
    edge_support: list[float]
    page_count: list[int]
    edge_page_count: list[int]
    mean: list[float]
    m2: list[float]
    dark: list[float]
    edge: list[float]


def _empty(count: int) -> _Accumulator:
    return _Accumulator(
        [0.0] * count,
        [0.0] * count,
        [0] * count,
        [0] * count,
        [0.0] * count,
        [0.0] * count,
        [0.0] * count,
        [0.0] * count,
    )


def _add(state: _Accumulator, page: NormalizedPage, weight: float, plan: GhostPlan) -> None:
    """Weighted Welford moments and threshold fractions exclude letterbox padding exactly."""
    left, top, right, bottom = page.transform.placed_box
    width = plan.pixels.width
    for y in range(top, bottom):
        for x in range(left, right):
            index = y * width + x
            value = page.gray[index]
            total = state.support[index] + weight
            delta = value - state.mean[index]
            state.mean[index] += delta * weight / total
            state.m2[index] += weight * delta * (value - state.mean[index])
            state.support[index] = total
            state.page_count[index] += 1
            if value < plan.dark_threshold:
                state.dark[index] += weight
            if x + 1 < right and y + 1 < bottom:
                gradient = max(
                    abs(page.gray[index + 1] - value), abs(page.gray[index + width] - value)
                )
                state.edge_support[index] += weight
                state.edge_page_count[index] += 1
                if gradient >= plan.edge_threshold:
                    state.edge[index] += weight


def _maps(state: _Accumulator, width: int, height: int) -> GhostMaps:
    means: list[float | None] = []
    variances: list[float | None] = []
    dark: list[float | None] = []
    edge: list[float | None] = []
    for index, weight in enumerate(state.support):
        variance = state.m2[index] / weight if weight else None
        if variance is not None and variance < -1e-8:
            raise StudyError("weighted ghost variance is numerically invalid")
        means.append(state.mean[index] if weight else None)
        variances.append(max(0.0, variance) if variance is not None else None)
        dark.append(state.dark[index] / weight if weight else None)
        edge.append(
            state.edge[index] / state.edge_support[index] if state.edge_support[index] else None
        )
    return GhostMaps(
        width=width,
        height=height,
        mean_gray=tuple(means),
        population_variance=tuple(variances),
        dark_fraction=tuple(dark),
        edge_fraction=tuple(edge),
        support_weight=tuple(state.support),
        edge_support_weight=tuple(state.edge_support),
        page_support=tuple(state.page_count),
        edge_page_support=tuple(state.edge_page_count),
    )


def ghost_cluster(plan: GhostPlan, resolve: Callable[[PageImage], bytes]) -> GhostAggregate:
    """Describe a supplied cluster in deterministic source-page order.

    Equal-page gives every eligible page weight1. Equal-issue gives each issue with eligible
    pixels total weight1 across that issue's eligible pages. Per-pixel averages divide by
    the weight of actual viewport contributors at that pixel, not padding or missing pages.
    """
    method = implementation_digest()
    assigned = Counter(member.issue_id for member in plan.members)
    eligible = tuple(
        sorted(
            (member for member in plan.members if member.page is not None), key=lambda m: m.page_key
        )
    )
    counts = Counter(member.issue_id for member in eligible)
    issue_weights = tuple(
        GhostIssueWeight(
            issue_id=issue,
            assigned_pages=assigned[issue],
            eligible_pages=counts[issue],
            per_page_weight=(1.0 if plan.weighting == "equal-page" else 1.0 / counts[issue])
            if counts[issue]
            else None,
        )
        for issue in sorted(assigned)
    )
    weights = {row.issue_id: row.per_page_weight for row in issue_weights}
    state = _empty(plan.pixels.width * plan.pixels.height)
    transforms: list[PageTransform] = []
    total_weights: list[float] = []
    for member in eligible:
        page, weight = member.page, weights[member.issue_id]
        if page is None or weight is None:
            raise StudyError("eligible ghost source lost its explicit pixel/weight declaration")
        normalized = normalize_page(resolve(page), page, plan.pixels)
        try:
            _add(state, normalized, weight, plan)
            transforms.append(normalized.transform)
            total_weights.append(weight)
        finally:
            normalized.rgb.close()
    result = GhostAggregate(
        implementation_sha256=method,
        input_plan_sha256=hashlib.sha256(plan.model_dump_json().encode()).hexdigest(),
        plan=plan,
        eligible_source_pages=len(eligible),
        eligible_issues=len(counts),
        unavailable_page_keys=tuple(
            sorted(member.page_key for member in plan.members if member.page is None)
        ),
        total_source_weight=math.fsum(total_weights),
        issue_weights=issue_weights,
        transforms=tuple(transforms),
        maps=_maps(state, plan.pixels.width, plan.pixels.height),
        pillow_version=pillow_version,
        python_version=sys.version,
    )
    if implementation_digest() != method:
        raise StudyError("atlas producer changed during ghost aggregation")
    return result
