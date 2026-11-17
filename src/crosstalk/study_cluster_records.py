"""Exploratory visual-feature groups retain source identity and every unavailable page."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from crosstalk import study_cluster_bindings
from crosstalk.study_language_records import Digest, Record, StudyError

ClusterBinding = study_cluster_bindings.ClusterBinding


class FeatureDefinition(Record):
    """Units, transforms and distance weights are declared before the group fit."""

    name: str = Field(min_length=1, max_length=80)
    channel: Literal["appearance", "native-layout"]
    unit: str = Field(min_length=1, max_length=120)
    transform: Literal["identity", "log1p"] = "identity"
    weight: float = Field(default=1.0, gt=0, le=1000)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def bounds(self) -> FeatureDefinition:
        """A declared admissible range cannot be reversed."""
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise StudyError("cluster feature bounds are reversed")
        return self


class PageFeatureInput(Record):
    """A physical page remains present even when its selected feature vector is unavailable."""

    issue_id: str = Field(min_length=1, max_length=240)
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    total_pdf_pages: int = Field(ge=1)
    values: tuple[float | None, ...] = Field(min_length=1, max_length=64)
    source_bindings: tuple[ClusterBinding, ...] = Field(min_length=1, max_length=8)
    status: Literal["measured", "missing", "refused", "failed", "unattempted"]
    reason: str = Field(min_length=1, max_length=500)
    exclusion_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def page_key(self) -> str:
        """PDF hash and physical index, never printed folio or a semantic genre label."""
        return f"{self.pdf_sha256}:{self.page_index}"

    @model_validator(mode="after")
    def page_scope(self) -> PageFeatureInput:
        """Preserve the original physical frame without a fixed maximum folio assumption."""
        if self.page_index >= self.total_pdf_pages:
            raise StudyError("cluster page lies outside its declared physical PDF")
        if any(value is not None and abs(value) > 1_000_000_000 for value in self.values):
            raise StudyError("cluster input exceeds the declared finite feature magnitude bound")
        return self


class FeatureFrame(Record):
    """One fixed feature schema/epoch; input admission and semantic accuracy remain external."""

    feature_epoch_sha256: Digest
    source_frame_receipt: ClusterBinding
    definitions: tuple[FeatureDefinition, ...] = Field(min_length=1, max_length=64)
    pages: tuple[PageFeatureInput, ...] = Field(min_length=1, max_length=30_000)
    declared_issue_ids: tuple[str, ...] = Field(min_length=1, max_length=2000)
    declared_total_pages: int = Field(ge=1, le=30_000)
    physical_scope: Literal["all-physical-pages", "declared-subset"]
    space_label: str = Field(min_length=1, max_length=160)
    semantic_genres_validated: Literal[False] = False


class ClusterPlan(Record):
    """Finite issue-balanced discovery and explicit out-of-fit issue projection."""

    requested_k: tuple[int, ...] = Field(default=(2, 4, 6, 8), min_length=1, max_length=8)
    per_issue_training_cap: int = Field(default=2, ge=1, le=16)
    heldout_issue_ids: tuple[str, ...] = ()
    heldout_declaration: ClusterBinding | None = None
    minimum_training_issues: int = Field(default=5, ge=2, le=2000)
    maximum_training_pages: int = Field(default=768, ge=2, le=1024)
    maximum_pair_distances: int = Field(default=294_528, ge=1, le=523_776)
    maximum_assignment_rows: int = Field(default=100_000, ge=1, le=240_000)
    maximum_iterations: int = Field(default=30, ge=1, le=100)
    scale_floor: float = Field(default=1e-8, gt=0, le=1)
    seed: int = Field(default=7301, ge=0)
    algorithm: Literal["deterministic-alternate-weighted-k-medoids-1"] = (
        "deterministic-alternate-weighted-k-medoids-1"
    )

    @model_validator(mode="after")
    def declared(self) -> ClusterPlan:
        """Reject hidden repeated model searches and unbound algorithmic holdouts."""
        if (
            self.requested_k != tuple(sorted(set(self.requested_k)))
            or min(self.requested_k) < 1
            or max(self.requested_k) > 12
            or len(self.heldout_issue_ids) != len(set(self.heldout_issue_ids))
            or bool(self.heldout_issue_ids) != (self.heldout_declaration is not None)
        ):
            raise StudyError("cluster k search or held-out declaration is inconsistent")
        return self


class FeatureScale(Record):
    """Training-only issue-balanced inverse empirical-CDF quantiles, with explicit fallbacks."""

    feature: str
    median: float
    q25: float
    q75: float
    minimum: float
    maximum: float
    scale: float = Field(gt=0)
    basis: Literal[
        "weighted-IQR", "weighted-IQR-floored", "range-fallback", "range-floored", "constant-zero"
    ]
    constant: bool


class TrainingIssue(Record):
    """Every eligible fit issue contributes one vote after deterministic capped selection."""

    issue_id: str
    eligible_pages: int
    selected_pages: int
    role: Literal["fit-issue", "algorithmic-heldout-issue"]
    page_weight_numerator: int
    page_weight_denominator: int


class ExcludedPage(Record):
    """Missing, refused, failed, unattempted and explicit exclusions never become zero vectors."""

    page_key: str
    issue_id: str
    pdf_sha256: Digest
    page_index: int
    status: Literal[
        "missing", "refused", "failed", "unattempted", "explicitly-excluded", "missing-features"
    ]
    reason: str
    source_bindings: tuple[ClusterBinding, ...]

    @model_validator(mode="after")
    def identity(self) -> ExcludedPage:
        """A declared page key cannot silently identify a different physical page."""
        if self.page_key != f"{self.pdf_sha256}:{self.page_index}" or self.page_index < 0:
            raise StudyError("cluster excluded-page source identity disagrees")
        return self


class ClusterAssignment(Record):
    """Projection distance and literal extrapolation flags are not confidence or accuracy."""

    page_key: str
    issue_id: str
    pdf_sha256: Digest
    page_index: int
    cluster_id: str
    medoid_page_key: str
    role: Literal["train", "projected-fit-issue", "heldout-issue"]
    distance: float = Field(ge=0)
    second_distance: float | None = Field(default=None, ge=0)
    nearest_tie_count: int = Field(ge=1)
    outside_training_range_features: tuple[str, ...]
    exceeds_observed_training_radius: bool
    source_bindings: tuple[ClusterBinding, ...]

    @model_validator(mode="after")
    def identity(self) -> ClusterAssignment:
        """Keep source identities, nearest distances and explicit feature flags consistent."""
        if (
            self.page_key != f"{self.pdf_sha256}:{self.page_index}"
            or self.page_index < 0
            or (self.second_distance is not None and self.distance > self.second_distance)
            or len(set(self.outside_training_range_features))
            != len(self.outside_training_range_features)
        ):
            raise StudyError("cluster assignment identity or distance order disagrees")
        return self


class ClusterModel(Record):
    """Every requested k is retained; labels denote medoid order, never document genres."""

    frame_sha256: Digest
    k: int = Field(ge=1, le=12)
    status: Literal[
        "converged",
        "iteration-limit",
        "cycle-detected",
        "below-issue-gate",
        "insufficient-distinct-training-vectors",
    ]
    iterations: int = Field(ge=0, le=100)
    medoids: tuple[str, ...]
    training_page_keys: tuple[str, ...]
    training_objective: float | None
    objective_history: tuple[float, ...]
    training_page_mean_silhouette: float | None
    training_equal_issue_mean_silhouette: float | None
    silhouette_scope: str = "Training-page silhouettes; singleton/coincident0; unavailable at k=1."
    assignments: tuple[ClusterAssignment, ...]

    @model_validator(mode="after")
    def coherent(self) -> ClusterModel:
        """Prevent duplicate assignments or invented medoid labels from passing record parsing."""
        fitted = self.status in {"converged", "iteration-limit", "cycle-detected"}
        if not fitted:
            if (
                self.medoids
                or self.assignments
                or self.training_objective is not None
                or self.objective_history
            ):
                raise StudyError("unfitted cluster model cannot contain successful fit output")
            return self
        labels = {key: f"cluster-{index:02d}" for index, key in enumerate(self.medoids, 1)}
        keys = {row.page_key for row in self.assignments}
        if (
            len(labels) != self.k
            or len(keys) != len(self.assignments)
            or len(set(self.training_page_keys)) != len(self.training_page_keys)
            or not set(self.medoids) <= set(self.training_page_keys) <= keys
            or not self.objective_history
            or self.training_objective != self.objective_history[-1]
        ):
            raise StudyError("cluster model medoid/training/output membership disagrees")
        if any(labels.get(row.medoid_page_key) != row.cluster_id for row in self.assignments):
            raise StudyError("cluster labels disagree with their declared source medoids")
        return self


class ClusterRun(Record):
    """A complete descriptive grouping/projection result, without corpus or semantic validation."""

    method_version: Literal["study-clustering-1"] = "study-clustering-1"
    implementation_sha256: Digest
    frame_sha256: Digest
    plan: ClusterPlan
    definitions: tuple[FeatureDefinition, ...]
    source_frame_receipt: ClusterBinding
    feature_epoch_sha256: Digest
    scales: tuple[FeatureScale, ...]
    training_issues: tuple[TrainingIssue, ...]
    excluded_pages: tuple[ExcludedPage, ...]
    models: tuple[ClusterModel, ...]
    declared_pages: int
    eligible_pages: int
    fit_weight_rule: str = (
        "Page weights1/selected issue pages; each eligible fit issue has one vote."
    )
    selection_rule: str = (
        "Within-issue seeded SHA256 rank; capped fit, remaining eligible pages project."
    )
    chronology: str = (
        "Post-inspection exploration; held-out issues do not imply untouched validation."
    )
    semantic_genres_validated: Literal[False] = False
    unseen_issue_projection_supported: Literal[False] = False

    @model_validator(mode="after")
    def accounted(self) -> ClusterRun:
        """The source frame cannot lose a missing page or a requested model outcome."""
        excluded = {row.page_key for row in self.excluded_pages}
        if (
            len(excluded) != len(self.excluded_pages)
            or self.declared_pages != self.eligible_pages + len(excluded)
            or tuple(row.k for row in self.models) != self.plan.requested_k
        ):
            raise StudyError("cluster run frame or requested-model accounting disagrees")
        for model in self.models:
            keys = {row.page_key for row in model.assignments}
            if model.frame_sha256 != self.frame_sha256 or keys & excluded:
                raise StudyError("cluster model source frame disagrees or includes excluded pages")
            if model.medoids and len(keys) != self.eligible_pages:
                raise StudyError("fitted cluster model omits eligible page projections")
        return self
