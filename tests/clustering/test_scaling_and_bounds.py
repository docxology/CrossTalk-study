"""Weighted quantile fallbacks and capacity refusals have explicit numerical meanings."""

from __future__ import annotations

import pytest

from crosstalk.study_cluster_fit import distance, distance_matrix
from crosstalk.study_cluster_records import ClusterBinding, FeatureDefinition
from crosstalk.study_clustering import cluster_pages
from crosstalk.study_language_records import StudyError

from .fixtures import frame, plan


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (((0.0, 0.0, 0.0, 100.0), (0.0, 0.0, 0.0, 0.0)), "range-fallback"),
        (((0.0, 1e-12), (2e-12, 3e-12)), "weighted-IQR-floored"),
        (((0.0, 0.0, 0.0, 1e-12), (0.0, 0.0, 0.0, 0.0)), "range-floored"),
    ],
)
def test_weighted_scale_fallbacks_are_declared(
    groups: tuple[tuple[float, ...], ...], expected: str
) -> None:
    run = cluster_pages(frame(groups), plan(requested_k=(1,), per_issue_training_cap=4))
    assert run.scales[0].basis == expected
    assert run.scales[0].scale >= run.plan.scale_floor


def test_log_transform_and_declared_feature_range_are_distinct_rules() -> None:
    source = frame(((-1.0,), (2.0,)))
    logarithm = FeatureDefinition(
        name="log", channel="appearance", unit="synthetic", transform="log1p"
    )
    with pytest.raises(StudyError, match="nonnegative"):
        _ = cluster_pages(source.model_copy(update={"definitions": (logarithm,)}), plan())
    bounded = FeatureDefinition(name="bounded", channel="appearance", unit="synthetic", minimum=0.0)
    with pytest.raises(StudyError, match="declared finite range"):
        _ = cluster_pages(source.model_copy(update={"definitions": (bounded,)}), plan())
    valid = cluster_pages(
        frame(((0.0,), (3.0,))).model_copy(update={"definitions": (logarithm,)}),
        plan(requested_k=(1,)),
    )
    assert valid.scales[0].minimum == 0.0
    assert valid.scales[0].maximum == pytest.approx(1.3862943611198906)


def test_all_holdouts_decline_fitting_without_imputing_training_statistics() -> None:
    source = frame()
    declared = plan(
        heldout_issue_ids=source.declared_issue_ids,
        heldout_declaration=ClusterBinding(path="synthetic/split.json", sha256="c" * 64),
    )
    run = cluster_pages(source, declared)
    assert run.scales == ()
    assert all(
        row.role == "algorithmic-heldout-issue" and row.selected_pages == 0
        for row in run.training_issues
    )
    assert all(model.status == "below-issue-gate" for model in run.models)


def test_unknown_holdout_and_training_capacity_refuse_without_selective_omission() -> None:
    declared = plan(
        heldout_issue_ids=("unknown",),
        heldout_declaration=ClusterBinding(path="synthetic/split.json", sha256="c" * 64),
    )
    with pytest.raises(StudyError, match="outside the declared frame"):
        _ = cluster_pages(frame(), declared)
    with pytest.raises(StudyError, match="pairwise capacity"):
        _ = cluster_pages(frame(), plan(maximum_training_pages=2))


def test_missing_physical_row_requires_an_explicit_subset_declaration() -> None:
    source = frame()
    partial = source.model_copy(update={"pages": source.pages[1:], "declared_total_pages": 3})
    with pytest.raises(StudyError, match="unavailable page row"):
        _ = cluster_pages(partial, plan())
    admitted = cluster_pages(
        partial.model_copy(update={"physical_scope": "declared-subset"}), plan(requested_k=(1,))
    )
    assert admitted.declared_pages == 3


def test_iteration_limit_is_retained_even_with_complete_assignments() -> None:
    run = cluster_pages(frame(), plan(maximum_iterations=1))
    assert run.models[-1].status == "iteration-limit"
    assert len(run.models[-1].assignments) == 4


@pytest.mark.parametrize(
    ("left", "right", "weights"),
    [
        ((0.0,), (0.0, 1.0), (1.0,)),
        ((0.0,), (1.0,), (-1.0,)),
        ((float("inf"),), (0.0,), (1.0,)),
        ((1e308,), (0.0,), (1.0,)),
    ],
)
def test_distance_boundary_refuses_invalid_dimensions_weights_or_arithmetic(
    left: tuple[float, ...],
    right: tuple[float, ...],
    weights: tuple[float, ...],
) -> None:
    with pytest.raises(StudyError):
        _ = distance(left, right, weights)


def test_distance_matrix_absolute_bound_precedes_quadratic_allocation() -> None:
    with pytest.raises(StudyError, match="absolute capacity"):
        _ = distance_matrix(((0.0,),) * 1025, (1.0,))
