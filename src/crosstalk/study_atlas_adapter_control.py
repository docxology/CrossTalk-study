"""Require independently admitted API/runtime proofs before production."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- Pydantic resolves these fields at runtime.
from typing import Literal

from pydantic import Field

from crosstalk.atlas_records import ArtifactBinding  # noqa: TC001 -- Pydantic resolves these fields at runtime.
from crosstalk.study_cluster_records import ClusterPlan  # noqa: TC001 -- Pydantic resolves these fields at runtime.
from crosstalk.study_language_records import Digest, Record, StudyError


class ApiSourceProof(Record):
    """Bind actual gate evidence to its exact selected code closure."""

    receipt_path: Path
    receipt_sha256: Digest
    source_manifest_sha256: Digest
    implementation_sha256: Digest


class ApiProofs(Record):
    """Null means the public API has not yet earned production admission."""

    atlas: ApiSourceProof | None = None
    clustering: ApiSourceProof | None = None
    cover_catalog: ApiSourceProof | None = None
    article_api: ApiSourceProof | None = None
    adapter: ApiSourceProof | None = None
    language_structure: ApiSourceProof | None = None


class AggregationRuntime(Record):
    """Bind the interpreter, native package files and loaded dependencies separately."""

    receipt: ArtifactBinding
    interpreter_runtime_manifest: ArtifactBinding
    pillow_record_manifest: ArtifactBinding
    pymupdf_record_manifest: ArtifactBinding
    loaded_dependency_manifest: ArtifactBinding
    aggregate_sha256: Digest


class AtlasProductionControl(Record):
    """Freeze source/settings while the governed caller owns live admission checks."""

    schema_version: Literal[1] = 1
    phase: Literal["pilot-64", "full-frame"]
    appearance_projection: ArtifactBinding
    layout_reconciliation_path: Path
    layout_reconciliation_sha256: Digest
    rendering_identity: Digest
    expected_source_units: int = Field(ge=1)
    expected_physical_pages: int = Field(ge=1)
    expected_measured_appearance: int = Field(ge=0)
    expected_policy_refused: int = Field(ge=0)
    proofs: ApiProofs = ApiProofs()
    aggregation_runtime: AggregationRuntime | None = None
    cluster_plan: ClusterPlan
    ghosts_k: int = Field(default=4, ge=1, le=12)
    ghost_canvas: tuple[int, int] = (64, 96)
    ghost_maximum_pixel_contributions: int = Field(default=60_000_000, ge=64, le=200_000_000)
    cover_policy: Literal["source-inspected-only; all declared slots retained"] = (
        "source-inspected-only; all declared slots retained"
    )
    include_quantitative_expression_retrieval: bool = False


def require_production_proofs(control: AtlasProductionControl) -> tuple[ApiSourceProof, ...]:
    """No pure source packet, fake success flag or version string enables actual production."""
    required = (
        control.proofs.atlas,
        control.proofs.clustering,
        control.proofs.cover_catalog,
        control.proofs.article_api,
        control.proofs.adapter,
    )
    if any(item is None for item in required) or control.aggregation_runtime is None:
        raise StudyError("real qualified API/source/runtime proofs are required before production")
    if (
        control.include_quantitative_expression_retrieval
        and control.proofs.language_structure is None
    ):
        raise StudyError(
            "quantitative retrieval requires its separately qualified " + "language-structure proof"
        )
    return tuple(item for item in required if item is not None)
