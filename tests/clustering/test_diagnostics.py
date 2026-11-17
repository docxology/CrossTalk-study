"""Hand-checkable distance and partition cases prevent polished but invalid diagnostics."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crosstalk.study_cluster_diagnostics import compare_partitions
from crosstalk.study_cluster_fit import silhouettes
from crosstalk.study_cluster_records import ClusterAssignment, ClusterModel
from crosstalk.study_clustering import cluster_pages
from crosstalk.study_language_records import StudyError

from .fixtures import frame, plan


def partition(labels: tuple[int, ...]) -> ClusterModel:
    """Explicit synthetic partitions support a known negative adjusted Rand result."""
    source = frame()
    groups = tuple(sorted(set(labels)))
    medoids = tuple(source.pages[labels.index(group)].page_key for group in groups)
    rows = tuple(
        ClusterAssignment(
            page_key=page.page_key,
            issue_id=page.issue_id,
            pdf_sha256=page.pdf_sha256,
            page_index=page.page_index,
            cluster_id=f"cluster-{groups.index(group) + 1:02d}",
            medoid_page_key=medoids[groups.index(group)],
            role="train",
            distance=0.0,
            second_distance=1.0 if len(groups) > 1 else None,
            nearest_tie_count=1,
            outside_training_range_features=(),
            exceeds_observed_training_radius=False,
            source_bindings=page.source_bindings,
        )
        for page, group in zip(source.pages, labels, strict=True)
    )
    return ClusterModel(
        frame_sha256="e" * 64,
        k=len(groups),
        status="converged",
        iterations=1,
        medoids=medoids,
        training_page_keys=tuple(page.page_key for page in source.pages),
        training_objective=0.0,
        objective_history=(0.0,),
        training_page_mean_silhouette=None,
        training_equal_issue_mean_silhouette=None,
        assignments=rows,
    )


def test_classical_silhouette_values_have_hand_computed_denominators() -> None:
    matrix = (
        (0.0, 1.0, 9.0, 10.0),
        (1.0, 0.0, 8.0, 9.0),
        (9.0, 8.0, 0.0, 1.0),
        (10.0, 9.0, 1.0, 0.0),
    )
    assert silhouettes(matrix, (0, 0, 2, 2)) == pytest.approx((17 / 19, 15 / 17, 15 / 17, 17 / 19))
    assert silhouettes(matrix, (0, 0, 0, 0)) is None


def test_singleton_and_all_zero_distances_do_not_imply_perfect_fit() -> None:
    zero = ((0.0, 0.0, 0.0),) * 3
    assert silhouettes(zero, (0, 1, 1)) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "matrix",
    [
        ((0.0, 1.0),),
        ((1.0,),),
        ((0.0, -1.0), (-1.0, 0.0)),
        ((0.0, 1.0), (2.0, 0.0)),
    ],
)
def test_invalid_distance_matrices_do_not_produce_silhouette_scores(
    matrix: tuple[tuple[float, ...], ...],
) -> None:
    with pytest.raises(StudyError):
        _ = silhouettes(matrix, tuple(range(len(matrix))))


def test_adjusted_rand_is_label_invariant_and_can_be_negative() -> None:
    original = partition((0, 0, 1, 1))
    renamed = partition((1, 1, 0, 0))
    crossed = partition((0, 1, 0, 1))
    assert compare_partitions(original, renamed).adjusted_rand_index == 1.0
    assert compare_partitions(original, crossed).adjusted_rand_index == -0.5
    assert (
        compare_partitions(partition((0, 0, 0, 0)), partition((1, 1, 1, 1))).adjusted_rand_index
        == 1.0
    )


def test_stability_refuses_changed_frames_partial_assignments_and_empty_scope() -> None:
    original = partition((0, 0, 1, 1))
    with pytest.raises(StudyError, match="one exact feature frame"):
        _ = compare_partitions(original, original.model_copy(update={"frame_sha256": "f" * 64}))
    with pytest.raises(ValueError, match=r"cluster|validation error"):
        _ = compare_partitions(
            original, original.model_copy(update={"assignments": original.assignments[:-1]})
        )
    with pytest.raises(StudyError, match="no matched pages"):
        _ = compare_partitions(original, original, "algorithmic-heldout-common")


def test_clustering_model_records_refuse_duplicate_assignments_and_wrong_labels() -> None:
    model = cluster_pages(frame(), plan()).models[-1]
    duplicate = model.model_copy(update={"assignments": (*model.assignments, model.assignments[0])})
    with pytest.raises(ValidationError, match="membership"):
        _ = ClusterModel.model_validate(duplicate.model_dump(mode="python"), strict=True)
    wrong = model.assignments[0].model_copy(update={"cluster_id": "semantic-genre-invented"})
    with pytest.raises(ValidationError, match="labels disagree"):
        _ = ClusterModel.model_validate(
            model.model_copy(update={"assignments": (wrong, *model.assignments[1:])}).model_dump(
                mode="python"
            ),
            strict=True,
        )
