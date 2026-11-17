"""Explicit frame admission, balanced selection and training-only weighted robust scaling."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from fractions import Fraction

from crosstalk.study_cluster_records import (
    ClusterPlan,
    ExcludedPage,
    FeatureDefinition,
    FeatureFrame,
    FeatureScale,
    PageFeatureInput,
    TrainingIssue,
)
from crosstalk.study_language_records import StudyError


def page_order(page: PageFeatureInput) -> tuple[str, int, str]:
    """Use physical source identity, independent of caller order and printed folios."""
    return page.pdf_sha256, page.page_index, page.issue_id


def admit(frame: FeatureFrame) -> tuple[tuple[PageFeatureInput, ...], tuple[ExcludedPage, ...]]:
    """Check complete declared identity/coverage and preserve missing operational states."""
    if (
        frame.declared_total_pages != len(frame.pages)
        or len(frame.declared_issue_ids) != len(set(frame.declared_issue_ids))
        or set(frame.declared_issue_ids) != {page.issue_id for page in frame.pages}
        or len({row.name for row in frame.definitions}) != len(frame.definitions)
    ):
        raise StudyError("cluster declared frame/schema membership disagrees")
    issues: dict[str, tuple[str, int]] = {}
    pdfs: dict[str, str] = {}
    indices: dict[str, set[int]] = defaultdict(set)
    eligible: list[PageFeatureInput] = []
    excluded: list[ExcludedPage] = []
    for page in sorted(frame.pages, key=page_order):
        identity = page.pdf_sha256, page.total_pdf_pages
        if (
            issues.setdefault(page.issue_id, identity) != identity
            or pdfs.setdefault(page.pdf_sha256, page.issue_id) != page.issue_id
        ):
            raise StudyError("cluster issue/PDF identity requires reconciliation")
        if page.page_index in indices[page.issue_id]:
            raise StudyError("cluster received a duplicate physical page")
        indices[page.issue_id].add(page.page_index)
        if len(page.values) != len(frame.definitions):
            raise StudyError("cluster page vector does not match declared feature schema")
        for definition, value in zip(frame.definitions, page.values, strict=True):
            if value is not None:
                _ = transform(value, definition)
        reason = page.exclusion_reason or page.reason
        status = (
            "explicitly-excluded"
            if page.exclusion_reason
            else page.status
            if page.status != "measured"
            else "missing-features"
            if any(value is None for value in page.values)
            else None
        )
        if status is None:
            eligible.append(page)
        else:
            excluded.append(
                ExcludedPage(
                    page_key=page.page_key,
                    issue_id=page.issue_id,
                    pdf_sha256=page.pdf_sha256,
                    page_index=page.page_index,
                    status=status,
                    reason=reason,
                    source_bindings=page.source_bindings,
                )
            )
    if frame.physical_scope == "all-physical-pages" and any(
        indices[issue] != set(range(total)) for issue, (_, total) in issues.items()
    ):
        raise StudyError("cluster all-physical-page frame has an unavailable page row")
    return tuple(eligible), tuple(excluded)


def transform(value: float, definition: FeatureDefinition) -> float:
    """No imputation, clipping or automatic feature discovery occurs at this boundary."""
    if (
        not math.isfinite(value)
        or abs(value) > 1_000_000_000
        or not math.isfinite(definition.weight)
        or not 0 < definition.weight <= 1000
        or (definition.minimum is not None and value < definition.minimum)
        or (definition.maximum is not None and value > definition.maximum)
    ):
        raise StudyError("cluster value or feature weight is outside its declared finite range")
    if definition.transform == "log1p":
        if value < 0:
            raise StudyError("cluster log1p feature requires nonnegative measurements")
        return math.log1p(value)
    return value


def select_training(
    frame: FeatureFrame,
    plan: ClusterPlan,
    eligible: tuple[PageFeatureInput, ...],
) -> tuple[tuple[PageFeatureInput, ...], tuple[TrainingIssue, ...]]:
    """Retain every eligible issue, or refuse capacity; never silently drop issues."""
    if not set(plan.heldout_issue_ids) <= set(frame.declared_issue_ids):
        raise StudyError("algorithmic held-out issue is outside the declared frame")
    grouped: dict[str, list[PageFeatureInput]] = defaultdict(list)
    for page in eligible:
        grouped[page.issue_id].append(page)
    selected: list[PageFeatureInput] = []
    issues: list[TrainingIssue] = []
    for issue in sorted(frame.declared_issue_ids):
        pages = grouped[issue]
        heldout = issue in plan.heldout_issue_ids
        count = 0 if heldout else min(len(pages), plan.per_issue_training_cap)
        ranked = sorted(
            pages,
            key=lambda page: (
                hashlib.sha256(
                    json.dumps(
                        (plan.seed, frame.feature_epoch_sha256, page.pdf_sha256, page.page_index),
                        separators=(",", ":"),
                    ).encode()
                ).digest(),
                page_order(page),
            ),
        )
        selected.extend(ranked[:count])
        issues.append(
            TrainingIssue(
                issue_id=issue,
                eligible_pages=len(pages),
                selected_pages=count,
                role="algorithmic-heldout-issue" if heldout else "fit-issue",
                page_weight_numerator=int(count > 0),
                page_weight_denominator=count or 1,
            )
        )
    count = len(selected)
    if (
        count > plan.maximum_training_pages
        or count * (count - 1) // 2 > plan.maximum_pair_distances
    ):
        raise StudyError(
            "balanced cluster fit exceeds explicit pairwise capacity; change the declared plan"
        )
    if len(eligible) * len(plan.requested_k) > plan.maximum_assignment_rows:
        raise StudyError("cluster full assignment output exceeds declared capacity")
    return tuple(sorted(selected, key=page_order)), tuple(issues)


def _quantile(rows: tuple[tuple[float, str, Fraction], ...], fraction: Fraction) -> float:
    """Inverse weighted empirical CDF: first value reaching the exact rational threshold."""
    total = sum((weight for _, _, weight in rows), Fraction())
    cumulative = Fraction()
    for value, _, weight in sorted(rows):
        cumulative += weight
        if cumulative >= fraction * total:
            return value
    raise StudyError("weighted cluster quantile has no admitted positive-weight observations")


def scales_for(
    frame: FeatureFrame,
    plan: ClusterPlan,
    training: tuple[PageFeatureInput, ...],
) -> tuple[FeatureScale, ...]:
    """Fit every transform using selected non-heldout training observations only."""
    counts: dict[str, int] = defaultdict(int)
    for page in training:
        counts[page.issue_id] += 1
    result: list[FeatureScale] = []
    for index, definition in enumerate(frame.definitions):
        rows: list[tuple[float, str, Fraction]] = []
        for page in training:
            value = page.values[index]
            if value is None:
                raise StudyError("cluster scaling encountered an unavailable training feature")
            rows.append(
                (transform(value, definition), page.page_key, Fraction(1, counts[page.issue_id]))
            )
        values = tuple(rows)
        median = _quantile(values, Fraction(1, 2))
        q25, q75 = (_quantile(values, q) for q in (Fraction(1, 4), Fraction(3, 4)))
        low, high = min(row[0] for row in values), max(row[0] for row in values)
        spread = q75 - q25
        if low == high:
            scale, basis = 1.0, "constant-zero"
        elif spread:
            scale = max(spread, plan.scale_floor)
            basis = "weighted-IQR" if spread >= plan.scale_floor else "weighted-IQR-floored"
        else:
            scale = max(high - low, plan.scale_floor)
            basis = "range-fallback" if high - low >= plan.scale_floor else "range-floored"
        result.append(
            FeatureScale(
                feature=definition.name,
                median=median,
                q25=q25,
                q75=q75,
                minimum=low,
                maximum=high,
                scale=scale,
                basis=basis,
                constant=low == high,
            )
        )
    return tuple(result)


def vector(
    page: PageFeatureInput,
    definitions: tuple[FeatureDefinition, ...],
    scales: tuple[FeatureScale, ...],
) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Keep out-of-training-range features explicit; no clipping changes a projection."""
    values: list[float] = []
    outside: list[str] = []
    for value, definition, scale in zip(page.values, definitions, scales, strict=True):
        if value is None:
            raise StudyError("cluster projection cannot impute an unavailable measurement")
        transformed = transform(value, definition)
        if not scale.minimum <= transformed <= scale.maximum:
            outside.append(definition.name)
        values.append((transformed - scale.median) / scale.scale)
    return tuple(values), tuple(outside)
