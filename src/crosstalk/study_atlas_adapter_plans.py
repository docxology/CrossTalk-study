"""Explicit model, weighting and inspected-cover selections bridge the qualified pure APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from crosstalk.atlas_ghost_records import GhostMember, GhostPlan
from crosstalk.atlas_records import ArtifactBinding, CoverMosaicPlan, CoverSlot, PixelSettings
from crosstalk.cover_catalog import validate_cover_catalog
from crosstalk.cover_records import CoverDecision  # noqa: TC001 -- Pydantic field resolves at runtime.
from crosstalk.study_language_records import Record, StudyError

if TYPE_CHECKING:
    from crosstalk.study_atlas_adapter_records import AtlasInputFrame
    from crosstalk.study_cluster_records import ClusterRun


class GhostSelection(Record):
    """Prespecify k and work bounds while retaining all requested fit outcomes."""

    k: int = Field(default=4, ge=1, le=12)
    weighting: Literal["equal-page", "equal-issue"]
    clustering_receipt: ArtifactBinding
    upstream_frame_exclusions: ArtifactBinding
    aggregation_runtime: ArtifactBinding
    pixels: PixelSettings = PixelSettings(width=64, height=96)
    maximum_pixel_contributions: int = Field(default=60_000_000, ge=64, le=200_000_000)


def ghost_plans(
    frame: AtlasInputFrame, run: ClusterRun, selection: GhostSelection
) -> tuple[GhostPlan, ...]:
    """Use actual assignments and medoids; declined fits yield no invented clusters."""
    models = tuple(model for model in run.models if model.k == selection.k)
    if len(models) != 1:
        raise StudyError("ghost k must name exactly one actually retained cluster model")
    model = models[0]
    if not model.assignments:
        return ()
    if (
        run.source_frame_receipt.path != frame.receipt.path
        or run.source_frame_receipt.sha256 != frame.receipt.sha256
    ):
        raise StudyError("ghost clustering and physical frame receipts disagree")
    pages = {slot.page_key: slot for slot in frame.pages}
    result: list[GhostPlan] = []
    for cluster in sorted({row.cluster_id for row in model.assignments}):
        assigned = tuple(
            sorted(
                (row for row in model.assignments if row.cluster_id == cluster),
                key=lambda item: (item.distance, item.page_key),
            )
        )
        members: list[GhostMember] = []
        for row in assigned:
            slot = pages.get(row.page_key)
            if slot is None or slot.issue_id != row.issue_id or slot.appearance is None:
                raise StudyError(
                    "ghost assignment is outside its source-matched measured " + "descriptor frame"
                )
            image = slot.appearance.image
            members.append(
                GhostMember(
                    issue_id=row.issue_id,
                    pdf_sha256=row.pdf_sha256,
                    page_index=row.page_index,
                    assignment_role=row.role,
                    page=image,
                    unavailable_reason=slot.appearance.pixel_unavailable_reason,
                )
            )
        medoid = assigned[0].medoid_page_key
        representatives = (medoid, *(row.page_key for row in assigned if row.page_key != medoid))[
            :4
        ]
        result.append(
            GhostPlan(
                cluster_id=f"k{model.k:02d}-{cluster}",
                clustering_receipt=selection.clustering_receipt,
                source_frame=frame.receipt,
                upstream_frame_exclusions=selection.upstream_frame_exclusions,
                aggregation_runtime=selection.aggregation_runtime,
                clustering_method_note=(
                    f"Exploratory weighted k-medoids; k={model.k}; "
                    + f"fit status={model.status}; frame={run.frame_sha256}; "
                    + "all requested k outcomes retained separately."
                ),
                selection_note=(
                    f"Clustering declares {run.declared_pages} of {len(frame.pages)} "
                    + "source-frame physical slots. Actual assignment roles are retained. "
                    + "Upstream refused/unavailable pages remain in the bound exclusion frame "
                    + "and receive no fabricated cluster membership."
                ),
                members=tuple(members),
                representative_page_keys=representatives,
                representative_basis=(
                    "Actual source medoid first, then at most three nearest assigned "
                    + "physical pages by distance/page-key; missing pixels remain "
                    + "placeholders."
                ),
                weighting=selection.weighting,
                pixels=selection.pixels,
                maximum_pixel_contributions=selection.maximum_pixel_contributions,
            )
        )
    return tuple(result)


class CoverSelection(Record):
    """All declared slots and the authored source-inspection receipt remain visible."""

    decisions: tuple[CoverDecision, ...]
    annotation_receipt: ArtifactBinding
    aggregation_runtime: ArtifactBinding


def cover_plan(frame: AtlasInputFrame, selection: CoverSelection) -> CoverMosaicPlan:
    """Only explicit source-inspected cover/front-page selections may supply montage pixels."""
    expected = tuple(unit.unit_id for unit in frame.units)
    decisions = tuple(selection.decisions)
    _ = validate_cover_catalog(decisions, expected)
    source_units = {unit.issue_id: unit for unit in frame.units}
    if len({decision.unit.issue_id for decision in decisions}) != len(source_units) or {
        decision.unit.issue_id for decision in decisions
    } != set(source_units):
        raise StudyError("cover decisions repeat or omit a declared issue source")
    pages = {slot.page_key: slot for slot in frame.pages}
    slots: list[CoverSlot] = []
    for number, decision in enumerate(sorted(decisions, key=lambda item: item.unit.issue_id), 1):
        unit = source_units[decision.unit.issue_id]
        if (
            decision.unit.unit_id != unit.unit_id
            or decision.unit.pdf_sha256 != unit.pdf.sha256
            or decision.unit.physical_pages != unit.physical_pages
        ):
            raise StudyError(
                "cover catalog and independently declared physical source frame " + "disagree"
            )
        image = None
        if decision.selected_page_index is not None:
            slot = pages[f"{unit.pdf.sha256}:{decision.selected_page_index}"]
            image = slot.appearance.image if slot.appearance is not None else None
            selected = decision.selected_render
            if (
                image is None
                or selected is None
                or selected.image_basis != "thumbnail"
                or (
                    selected.image.path,
                    selected.image.sha256,
                    selected.render_identity,
                    selected.width,
                    selected.height,
                )
                != (
                    image.image.path,
                    image.image.sha256,
                    image.rendering_identity,
                    image.width,
                    image.height,
                )
            ):
                raise StudyError(
                    "inspected cover selection lacks matching admitted thumbnail evidence"
                )
        slots.append(
            CoverSlot(
                unit_id=unit.unit_id,
                source_family=unit.source_family,
                issue_id=unit.issue_id,
                pdf_sha256=unit.pdf.sha256,
                display_label=f"I{number:03d}",
                period_label=unit.issued_metadata,
                status=decision.status,
                selected_role=decision.selected_role,
                page=image,
                selection_evidence=selection.annotation_receipt,
                note=decision.note,
            )
        )
    return CoverMosaicPlan(
        source_frame=frame.receipt,
        annotation_receipt=selection.annotation_receipt,
        aggregation_runtime=selection.aggregation_runtime,
        order_basis=(
            "Issue-ID lexical order with I001… slot map; catalog dates "
            + "remain raw metadata, not verified publication chronology."
        ),
        declared_source_units=len(frame.units),
        slots=tuple(slots),
    )
