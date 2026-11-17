"""Malformed records must not turn missingness or an unfitted model into success."""

from __future__ import annotations

import pytest

from crosstalk.study_cluster_records import (
    ClusterBinding,
    ClusterPlan,
    ClusterRun,
    FeatureDefinition,
)
from crosstalk.study_clustering import cluster_pages

from .fixtures import frame, plan


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "/absolute/data.json",
        "../other.json",
        "a/../other.json",
        "a\\data.json",
        "a//data.json",
    ],
)
def test_artifact_paths_remain_local_canonical_and_nontraversing(path: str) -> None:
    with pytest.raises(ValueError, match=r"cluster|validation error"):
        _ = ClusterBinding(path=path, sha256="a" * 64)


def test_reversed_bounds_and_out_of_frame_page_numbers_refuse() -> None:
    with pytest.raises(ValueError, match="bounds are reversed"):
        _ = FeatureDefinition(
            name="bad", channel="appearance", unit="synthetic", minimum=2.0, maximum=1.0
        )
    page = frame().pages[0]
    with pytest.raises(ValueError, match="outside its declared physical PDF"):
        _ = type(page).model_validate(
            page.model_copy(update={"page_index": page.total_pdf_pages}).model_dump(mode="python"),
            strict=True,
        )
    with pytest.raises(ValueError, match="magnitude bound"):
        _ = type(page).model_validate(
            page.model_copy(update={"values": (1e10,)}).model_dump(mode="python"), strict=True
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_k": (2, 1)},
        {"requested_k": (1, 1)},
        {"requested_k": (0,)},
        {"heldout_issue_ids": ("synthetic-0",)},
    ],
)
def test_plan_rejects_hidden_search_duplicates_and_unbound_holdouts(
    changes: dict[str, tuple[int, ...] | tuple[str, ...]],
) -> None:
    with pytest.raises(ValueError, match=r"cluster|validation error"):
        _ = ClusterPlan.model_validate({**plan().model_dump(mode="python"), **changes}, strict=True)


def test_result_cannot_relabel_physical_sources_or_duplicate_extrapolation_flags() -> None:
    result = cluster_pages(frame(), plan())
    row = result.models[-1].assignments[0]
    for changes in (
        {"page_key": "wrong"},
        {"distance": 2.0, "second_distance": 1.0},
        {"outside_training_range_features": ("same", "same")},
    ):
        with pytest.raises(ValueError, match=r"cluster|validation error"):
            _ = type(row).model_validate(
                row.model_copy(update=changes).model_dump(mode="python"), strict=True
            )


def test_declined_fit_cannot_include_successful_assignments() -> None:
    result = cluster_pages(frame(), plan())
    model = result.models[-1]
    with pytest.raises(ValueError, match="unfitted cluster model"):
        _ = type(model).model_validate(
            model.model_copy(update={"status": "below-issue-gate"}).model_dump(mode="python"),
            strict=True,
        )


def test_run_cannot_lose_page_or_model_outcomes() -> None:
    result = cluster_pages(frame(), plan())
    for changes in ({"declared_pages": 100}, {"models": result.models[:-1]}):
        with pytest.raises(ValueError, match="accounting"):
            _ = ClusterRun.model_validate(
                result.model_copy(update=changes).model_dump(mode="python"), strict=True
            )


def test_declared_issue_membership_and_feature_names_must_match_the_frame() -> None:
    source = frame()
    for changes in (
        {"declared_issue_ids": ("synthetic-0", "synthetic-0")},
        {"declared_total_pages": 100},
        {"definitions": (source.definitions[0], source.definitions[0])},
    ):
        with pytest.raises(ValueError, match="membership"):
            _ = cluster_pages(source.model_copy(update=changes), plan())
