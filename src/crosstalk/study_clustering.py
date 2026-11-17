"""Exploratory source-bound page grouping with complete eligibility and projection accounting."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from crosstalk.study_cluster_fit import distance, distance_matrix, fit, silhouettes
from crosstalk.study_cluster_records import (
    ClusterAssignment,
    ClusterModel,
    ClusterPlan,
    ClusterRun,
    FeatureFrame,
    FeatureScale,
    PageFeatureInput,
    TrainingIssue,
)
from crosstalk.study_cluster_scaling import admit, page_order, scales_for, select_training, vector
from crosstalk.study_language_records import StudyError

METHOD_FILES: Final = (
    "study_clustering.py",
    "study_cluster_records.py",
    "study_cluster_bindings.py",
    "study_cluster_scaling.py",
    "study_cluster_fit.py",
    "study_cluster_diagnostics.py",
    "study_cluster_language.py",
    "study_language_records.py",
)


@dataclass(frozen=True, slots=True)
class ModelInputs:
    """One admitted sample and its preprocessing, separated from declared fit settings."""

    eligible: tuple[PageFeatureInput, ...]
    training: tuple[PageFeatureInput, ...]
    scales: tuple[FeatureScale, ...]
    training_issues: tuple[TrainingIssue, ...]


def implementation_digest() -> str:
    """New producer identity is separate from the retained seven measurement modules."""
    root = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((root / name).read_bytes()).hexdigest()) for name in METHOD_FILES
    )
    return hashlib.sha256(
        json.dumps(
            (members, sys.version, sys.implementation.name, tuple(sys.float_info)),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _canonical(frame: FeatureFrame) -> FeatureFrame:
    """Revalidate copied/constructed models, then normalize only nonsemantic source ordering."""
    value = FeatureFrame.model_validate(frame.model_dump(mode="python"), strict=True)
    pages = tuple(
        page.model_copy(
            update={
                "source_bindings": tuple(
                    sorted(
                        page.source_bindings,
                        key=lambda item: (item.path, item.sha256),
                    )
                )
            }
        )
        for page in sorted(value.pages, key=page_order)
    )
    return value.model_copy(
        update={"pages": pages, "declared_issue_ids": tuple(sorted(value.declared_issue_ids))}
    )


def _unfitted(
    frame_sha: str,
    k: int,
    status: Literal["below-issue-gate", "insufficient-distinct-training-vectors"],
    training: tuple[PageFeatureInput, ...],
) -> ClusterModel:
    """A declined fit remains a named outcome, never empty successful clustering."""
    return ClusterModel(
        frame_sha256=frame_sha,
        k=k,
        status=status,
        iterations=0,
        medoids=(),
        training_page_keys=tuple(page.page_key for page in training),
        training_objective=None,
        objective_history=(),
        training_page_mean_silhouette=None,
        training_equal_issue_mean_silhouette=None,
        assignments=(),
    )


def _models(
    frame: FeatureFrame,
    plan: ClusterPlan,
    frame_sha: str,
    inputs: ModelInputs,
) -> tuple[ClusterModel, ...]:
    """Every declared k gets its own fitted or explicit declined outcome."""
    eligible, training, scales = inputs.eligible, inputs.training, inputs.scales
    training_issues = inputs.training_issues
    if sum(issue.selected_pages > 0 for issue in training_issues) < plan.minimum_training_issues:
        return tuple(
            _unfitted(frame_sha, k, "below-issue-gate", training) for k in plan.requested_k
        )
    coordinates = tuple(vector(page, frame.definitions, scales)[0] for page in training)
    feature_weights = tuple(item.weight for item in frame.definitions)
    matrix = distance_matrix(coordinates, feature_weights)
    issue_sizes = {row.issue_id: row.selected_pages for row in training_issues}
    fit_weights = tuple(1.0 / issue_sizes[page.issue_id] for page in training)
    results: list[ClusterModel] = []
    for k in plan.requested_k:
        if k > len(set(coordinates)):
            results.append(
                _unfitted(frame_sha, k, "insufficient-distinct-training-vectors", training)
            )
            continue
        result = fit(matrix, fit_weights, k, plan.maximum_iterations)
        silhouette = silhouettes(matrix, result.assigned_medoids)
        by_issue: dict[str, list[float]] = defaultdict(list)
        if silhouette is not None:
            for page, value in zip(training, silhouette, strict=True):
                by_issue[page.issue_id].append(value)
        radii = {
            medoid: max(
                matrix[index][medoid]
                for index, group in enumerate(result.assigned_medoids)
                if group == medoid
            )
            for medoid in result.medoids
        }
        labels = {medoid: f"cluster-{index:02d}" for index, medoid in enumerate(result.medoids, 1)}
        selected_keys = {page.page_key for page in training}
        assignments: list[ClusterAssignment] = []
        for page in eligible:
            point, outside = vector(page, frame.definitions, scales)
            ranked = sorted(
                (distance(point, coordinates[medoid], feature_weights), medoid)
                for medoid in result.medoids
            )
            closest, medoid = ranked[0]
            role: Literal["train", "heldout-issue", "projected-fit-issue"] = (
                "train"
                if page.page_key in selected_keys
                else "heldout-issue"
                if page.issue_id in plan.heldout_issue_ids
                else "projected-fit-issue"
            )
            assignments.append(
                ClusterAssignment(
                    page_key=page.page_key,
                    issue_id=page.issue_id,
                    pdf_sha256=page.pdf_sha256,
                    page_index=page.page_index,
                    cluster_id=labels[medoid],
                    medoid_page_key=training[medoid].page_key,
                    role=role,
                    distance=closest,
                    second_distance=ranked[1][0] if len(ranked) > 1 else None,
                    nearest_tie_count=sum(value == closest for value, _ in ranked),
                    outside_training_range_features=outside,
                    exceeds_observed_training_radius=closest > radii[medoid],
                    source_bindings=page.source_bindings,
                )
            )
        results.append(
            ClusterModel(
                frame_sha256=frame_sha,
                k=k,
                status=result.status,
                iterations=result.iterations,
                medoids=tuple(training[index].page_key for index in result.medoids),
                training_page_keys=tuple(page.page_key for page in training),
                training_objective=result.objective_history[-1],
                objective_history=result.objective_history,
                training_page_mean_silhouette=math.fsum(silhouette) / len(silhouette)
                if silhouette is not None
                else None,
                training_equal_issue_mean_silhouette=math.fsum(
                    math.fsum(values) / len(values) for values in by_issue.values()
                )
                / len(by_issue)
                if by_issue
                else None,
                assignments=tuple(assignments),
            )
        )
    return tuple(results)


DEFAULT_PLAN: Final = ClusterPlan()


def cluster_pages(frame: FeatureFrame, plan: ClusterPlan = DEFAULT_PLAN) -> ClusterRun:
    """Fit and project one admitted frame; unknown new issues require a separately bound rerun.

    Canonical record checks establish internal consistency, not independent source custody,
    OCR accuracy, date reconciliation, genre validation or a complete historical corpus.
    """
    method = implementation_digest()
    frame = _canonical(frame)
    plan = ClusterPlan.model_validate(plan.model_dump(mode="python"), strict=True)
    plan = plan.model_copy(update={"heldout_issue_ids": tuple(sorted(plan.heldout_issue_ids))})
    eligible, excluded = admit(frame)
    training, issues = select_training(frame, plan, eligible)
    scales = scales_for(frame, plan, training) if training else ()
    frame_sha = hashlib.sha256(frame.model_dump_json().encode()).hexdigest()
    models = _models(frame, plan, frame_sha, ModelInputs(eligible, training, scales, issues))
    if implementation_digest() != method:
        raise StudyError("cluster producer changed during the source-bound fit")
    return ClusterRun(
        implementation_sha256=method,
        frame_sha256=frame_sha,
        plan=plan,
        definitions=frame.definitions,
        source_frame_receipt=frame.source_frame_receipt,
        feature_epoch_sha256=frame.feature_epoch_sha256,
        scales=scales,
        training_issues=issues,
        excluded_pages=excluded,
        models=models,
        declared_pages=len(frame.pages),
        eligible_pages=len(eligible),
    )
