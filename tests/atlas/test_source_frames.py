"""Explicit alias, missingness and contradictory-map controls protect scientific denominators."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from crosstalk.atlas_ghost import ghost_cluster
from crosstalk.atlas_ghost_records import GhostMaps, GhostMember, GhostPlan
from crosstalk.atlas_records import CoverMosaicPlan, CoverSlot, PageImage, PixelSettings

if TYPE_CHECKING:
    from pathlib import Path

from .fixtures import binding, member, page, plan, resolve


def test_page_scope_and_normalization_capacity(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    for change in ({"page_index": source.total_pdf_pages}, {"pdf_sha256": "f" * 64}):
        with pytest.raises(ValidationError, match="declared exact PDF"):
            _ = PageImage.model_validate({**source.model_dump(), **change})
    with pytest.raises(ValidationError, match="canvas"):
        _ = PixelSettings(width=512, height=768)


def test_cover_slot_identity_and_role_refusals(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    values = {
        "unit_id": "A",
        "source_family": "generated",
        "issue_id": source.issue_id,
        "pdf_sha256": source.pdf_sha256,
        "display_label": "001",
        "status": "verified-cover",
        "selected_role": "front-cover",
        "page": source,
        "selection_evidence": binding(),
        "note": "Generated control.",
    }
    for change in ({"issue_id": "different"}, {"pdf_sha256": "f" * 64}):
        with pytest.raises(ValidationError, match="crosses"):
            _ = CoverSlot.model_validate({**values, **change})
    with pytest.raises(ValidationError, match="role requires"):
        _ = CoverSlot.model_validate({**values, "status": "candidate-first-retained-page"})


def test_cover_plan_keeps_unique_sources_and_display_ids() -> None:
    first = CoverSlot(
        unit_id="A",
        source_family="generated",
        issue_id="fixture-a",
        pdf_sha256="a" * 64,
        display_label="001",
        status="unavailable",
        page=None,
        selection_evidence=binding(),
        note="Unavailable generated source.",
    )
    second = CoverSlot(
        unit_id="B",
        source_family="generated",
        issue_id="fixture-b",
        pdf_sha256="b" * 64,
        display_label="002",
        status="unavailable",
        page=None,
        selection_evidence=binding(),
        note="Unavailable generated source.",
    )
    values = {
        "source_frame": binding(),
        "annotation_receipt": binding(),
        "aggregation_runtime": binding("runtime"),
        "order_basis": "Generated order",
        "declared_source_units": 2,
    }
    for changed, phrase in (
        (second.model_copy(update={"unit_id": "A"}), "incomplete or repeated"),
        (second.model_copy(update={"display_label": "001"}), "display labels"),
        (second.model_copy(update={"issue_id": "fixture-a"}), "repeats an issue"),
        (second.model_copy(update={"pdf_sha256": "a" * 64}), "PDF aliases"),
    ):
        with pytest.raises(ValidationError, match=phrase):
            _ = CoverMosaicPlan.model_validate({**values, "slots": (first, changed)})


def test_ghost_plan_refuses_duplicate_or_foreign_representatives(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    request = plan((source,))
    with pytest.raises(ValidationError, match="repeats"):
        _ = GhostPlan.model_validate(
            {**request.model_dump(), "members": (member(source), member(source))}
        )
    for representatives in (("unknown:99",), (source.page_key, source.page_key)):
        with pytest.raises(ValidationError, match="representatives"):
            _ = GhostPlan.model_validate(
                {**request.model_dump(), "representative_page_keys": representatives}
            )


def test_ghost_member_keeps_missingness_and_identity_consistent(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    original = member(source)
    with pytest.raises(ValidationError, match="present and unavailable"):
        _ = GhostMember.model_validate({**original.model_dump(), "page": None})
    with pytest.raises(ValidationError, match="present and unavailable"):
        _ = GhostMember.model_validate(
            {**original.model_dump(), "unavailable_reason": "Conflicting state"}
        )
    with pytest.raises(ValidationError, match="crosses"):
        _ = GhostMember.model_validate({**original.model_dump(), "page_index": 1})


def test_ghost_plan_refuses_pdf_aliases_and_mixed_rendering_epochs(tmp_path: Path) -> None:
    first = page(tmp_path, "fixture-a", 0, 0)
    second = page(tmp_path, "fixture-b", 1, 0)
    request = plan((first, second))
    missing = GhostMember(
        issue_id=first.issue_id,
        pdf_sha256="f" * 64,
        page_index=9,
        assignment_role="train",
        page=None,
        unavailable_reason="Generated conflicting physical PDF.",
    )
    with pytest.raises(ValidationError, match="conflicting physical PDFs"):
        _ = GhostPlan.model_validate({**request.model_dump(), "members": (member(first), missing)})
    alias = GhostMember(
        issue_id="fixture-alias",
        pdf_sha256=first.pdf_sha256,
        page_index=9,
        assignment_role="train",
        page=None,
        unavailable_reason="Generated alias.",
    )
    with pytest.raises(ValidationError, match="PDF aliases"):
        _ = GhostPlan.model_validate({**request.model_dump(), "members": (member(first), alias)})
    for change in (
        {"rendering_identity": "f" * 64},
        {"image_basis": "accepted-appearance-thumbnail"},
    ):
        changed = second.model_copy(update=change)
        with pytest.raises(ValidationError, match="mix image bases or rendering epochs"):
            _ = GhostPlan.model_validate(
                {**request.model_dump(), "members": (member(first), member(changed))}
            )


def test_ghost_map_rejects_missingness_and_scale_contradictions(tmp_path: Path) -> None:
    first = page(tmp_path, "fixture-a", 0, 0)
    result = ghost_cluster(plan((first,)), lambda p: resolve(tmp_path, p))
    rows = result.maps.model_dump()
    changes = (
        ("mean_gray", ()),
        ("support_weight", (-1.0, *result.maps.support_weight[1:])),
        ("mean_gray", (None, *result.maps.mean_gray[1:])),
        ("mean_gray", (256.0, *result.maps.mean_gray[1:])),
        ("edge_fraction", (None, *result.maps.edge_fraction[1:])),
        ("edge_fraction", (1.1, *result.maps.edge_fraction[1:])),
        ("edge_support_weight", (2.0, *result.maps.edge_support_weight[1:])),
    )
    for key, changed in changes:
        with pytest.raises(ValidationError):
            _ = GhostMaps.model_validate({**rows, key: changed})


def test_nonfinite_map_values_are_not_serialized_as_research_data(tmp_path: Path) -> None:
    first = page(tmp_path, "fixture-a", 0, 0)
    result = ghost_cluster(plan((first,)), lambda p: resolve(tmp_path, p))
    with pytest.raises(ValueError, match="finite"):
        _ = GhostMaps.model_validate(
            {**result.maps.model_dump(), "mean_gray": (float("nan"), *result.maps.mean_gray[1:])}
        )
