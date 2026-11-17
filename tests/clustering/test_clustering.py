"""Frame admission, training-only preprocessing and explicit complete projection controls."""

from __future__ import annotations

import pytest

from crosstalk.study_cluster_records import ClusterBinding
from crosstalk.study_clustering import cluster_pages
from crosstalk.study_language_records import StudyError

from .fixtures import frame, plan


def test_separated_numeric_control_has_known_objective_and_full_assignments() -> None:
    run = cluster_pages(frame(), plan())
    one, two = run.models
    assert one.training_page_mean_silhouette is None
    assert two.status == "converged"
    assert two.training_objective == pytest.approx(1 / 18)
    assert len(two.medoids) == 2
    assert len(two.assignments) == run.eligible_pages == run.declared_pages == 4
    assert two.training_page_mean_silhouette == pytest.approx((17 / 19 + 15 / 17) / 2)
    assert two.training_equal_issue_mean_silhouette == two.training_page_mean_silhouette
    assert not run.semantic_genres_validated
    assert not run.unseen_issue_projection_supported
    assert all(
        after <= before + 1e-12
        for before, after in zip(two.objective_history, two.objective_history[1:], strict=False)
    )


def test_reordered_frame_replays_canonically() -> None:
    source = frame()
    changed = source.model_copy(
        update={
            "pages": tuple(reversed(source.pages)),
            "declared_issue_ids": tuple(reversed(source.declared_issue_ids)),
        }
    )
    assert cluster_pages(source, plan()) == cluster_pages(changed, plan())


def test_heldout_issues_never_fit_scale_or_medoids_and_extrapolation_is_literal() -> None:
    source = frame(((0.0, 1.0), (9.0, 10.0), (1_000_000.0,)))
    declared = plan(
        heldout_issue_ids=("synthetic-2",),
        heldout_declaration=ClusterBinding(path="synthetic/heldout.json", sha256="c" * 64),
    )
    run = cluster_pages(source, declared)
    assert run.scales[0].maximum == 10.0
    heldout = source.pages[-1].page_key
    for model in run.models:
        assert heldout not in model.medoids
        assert heldout not in model.training_page_keys
        row = next(item for item in model.assignments if item.page_key == heldout)
        assert row.role == "heldout-issue"
        assert row.outside_training_range_features == ("synthetic-density",)
        assert row.exceeds_observed_training_radius


def test_short_and_long_issues_each_have_one_quantile_and_objective_vote() -> None:
    source = frame(((100.0,), (0.0,) * 16, (0.0,) * 16))
    run = cluster_pages(source, plan(requested_k=(1,), per_issue_training_cap=16))
    assert run.scales[0].q25 == 0.0
    assert run.scales[0].median == 0.0
    assert run.scales[0].q75 == 100.0
    assert [(row.selected_pages, row.page_weight_denominator) for row in run.training_issues] == [
        (1, 1),
        (16, 16),
        (16, 16),
    ]


def test_training_cap_preserves_remaining_page_projections() -> None:
    run = cluster_pages(
        frame(((0.0, 1.0, 2.0, 3.0), (9.0,))), plan(requested_k=(1,), per_issue_training_cap=1)
    )
    model = run.models[0]
    assert len(model.training_page_keys) == 2
    assert len(model.assignments) == 5
    assert sum(row.role == "projected-fit-issue" for row in model.assignments) == 3


@pytest.mark.parametrize(
    "defect", ["duplicate", "pdf-alias", "issue-alias", "missing-row", "vector-length", "nonfinite"]
)
def test_invalid_source_frame_refuses_before_fitting(defect: str) -> None:
    source = frame()
    first, second, third, fourth = source.pages
    variants = {
        "duplicate": (first, first, third, fourth),
        "pdf-alias": (first, second.model_copy(update={"pdf_sha256": "d" * 64}), third, fourth),
        "issue-alias": (
            first,
            second,
            third.model_copy(update={"issue_id": "synthetic-0"}),
            fourth,
        ),
        "missing-row": (first, third, fourth),
        "vector-length": (first.model_copy(update={"values": (0.0, 1.0)}), second, third, fourth),
        "nonfinite": (first.model_copy(update={"values": (float("nan"),)}), second, third, fourth),
    }
    changed = source.model_copy(update={"pages": variants[defect]})
    with pytest.raises(ValueError, match=r"cluster|validation error"):
        _ = cluster_pages(changed, plan())


@pytest.mark.parametrize("status", ["missing", "refused", "failed", "unattempted"])
def test_unavailable_pages_are_retained_without_zero_imputation(status: str) -> None:
    source = frame(((0.0, 1.0), (9.0, 10.0), (100.0,)))
    unavailable = source.pages[-1].model_copy(update={"status": status, "values": (None,)})
    changed = source.model_copy(update={"pages": (*source.pages[:-1], unavailable)})
    run = cluster_pages(changed, plan())
    assert run.declared_pages == 5
    assert run.eligible_pages == 4
    assert run.excluded_pages[0].status == status
    assert all(len(model.assignments) == 4 for model in run.models)


def test_partial_measurement_and_explicit_wrapper_exclusion_remain_distinct() -> None:
    source = frame(((0.0, 1.0), (9.0, 10.0), (100.0, 200.0)))
    missing = source.pages[-2].model_copy(update={"values": (None,)})
    wrapper = source.pages[-1].model_copy(
        update={"exclusion_reason": "Bound wrapper classification; synthetic control"}
    )
    run = cluster_pages(
        source.model_copy(update={"pages": (*source.pages[:-2], missing, wrapper)}), plan()
    )
    assert {row.status for row in run.excluded_pages} == {"missing-features", "explicitly-excluded"}


def test_constant_dimensions_do_not_manufacture_multiple_groups() -> None:
    run = cluster_pages(frame(((5.0,), (5.0,))), plan())
    assert run.scales[0].constant
    assert run.models[0].training_objective == 0.0
    assert run.models[1].status == "insufficient-distinct-training-vectors"
    assert not run.models[1].assignments


def test_below_issue_gate_is_a_declined_model_not_empty_success() -> None:
    run = cluster_pages(frame(), plan(minimum_training_issues=3))
    assert all(model.status == "below-issue-gate" and not model.assignments for model in run.models)


def test_pairwise_capacity_refuses_instead_of_dropping_issues() -> None:
    with pytest.raises(StudyError, match="pairwise capacity"):
        _ = cluster_pages(frame(), plan(maximum_pair_distances=1))


def test_assignment_capacity_refuses_instead_of_dropping_projection_rows() -> None:
    with pytest.raises(StudyError, match="assignment output"):
        _ = cluster_pages(frame(), plan(maximum_assignment_rows=2))
