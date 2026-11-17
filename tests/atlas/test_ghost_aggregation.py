"""Known generated pixel populations distinguish weighting, padding, missingness and edges."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING, TypedDict

import pytest
from PIL import Image
from pydantic import JsonValue, TypeAdapter, ValidationError

from crosstalk.atlas_ghost import ghost_cluster
from crosstalk.atlas_ghost_figures import ghost_map_pngs, ghost_overview, ghost_representatives
from crosstalk.atlas_ghost_records import GhostAggregate, GhostMember, GhostPlan
from crosstalk.atlas_records import ArtifactBinding
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from pathlib import Path

from .fixtures import member, page, plan, resolve


class RepresentativesManifest(TypedDict):
    records: list[dict[str, JsonValue]]


REPRESENTATIVES_MANIFEST = TypeAdapter(RepresentativesManifest)


def test_black_white_population_has_known_mean_variance_and_occupancy(tmp_path: Path) -> None:
    black = page(tmp_path, "fixture-a", 0, (0, 0, 0))
    white = page(tmp_path, "fixture-b", 0, (255, 255, 255))
    result = ghost_cluster(plan((black, white)), lambda p: resolve(tmp_path, p))
    assert result.eligible_source_pages == result.eligible_issues == 2
    assert result.maps.mean_gray == (127.5,) * 64
    assert result.maps.population_variance == (16256.25,) * 64
    assert result.maps.dark_fraction == (0.5,) * 64
    assert result.maps.page_support == (2,) * 64
    assert result.maps.edge_fraction[0] == 0
    assert result.maps.edge_fraction[7] is None
    assert result.maps.edge_support_weight[7] == 0
    assert not result.independent_sample_inference


def test_equal_issue_weights_differ_from_equal_page_weights(tmp_path: Path) -> None:
    first = page(tmp_path, "fixture-a", 0, (0, 0, 0))
    second = page(tmp_path, "fixture-a", 1, (0, 0, 0))
    third = page(tmp_path, "fixture-b", 0, (255, 255, 255))
    pages = first, second, third
    per_page = ghost_cluster(plan(pages), lambda p: resolve(tmp_path, p))
    per_issue = ghost_cluster(plan(pages, "equal-issue"), lambda p: resolve(tmp_path, p))
    assert per_page.maps.mean_gray[0] == pytest.approx(85)
    assert per_page.maps.dark_fraction[0] == pytest.approx(2 / 3)
    assert per_issue.maps.mean_gray[0] == pytest.approx(127.5)
    assert per_issue.maps.dark_fraction[0] == pytest.approx(0.5)
    assert [r.per_page_weight for r in per_issue.issue_weights] == [0.5, 1.0]
    assert per_issue.total_source_weight == 2


def test_white_letterbox_is_not_an_observed_white_page(tmp_path: Path) -> None:
    portrait = page(tmp_path, "fixture-a", 0, (0, 0, 0), (4, 8))
    landscape = page(tmp_path, "fixture-b", 0, (255, 255, 255), (8, 4))
    result = ghost_cluster(plan((portrait, landscape)), lambda p: resolve(tmp_path, p))
    assert result.maps.mean_gray[0] is None
    assert result.maps.page_support[0] == 0
    assert result.maps.mean_gray[2] == 0
    assert result.maps.dark_fraction[2] == 1
    assert result.maps.page_support[2] == 1
    assert result.maps.mean_gray[2 * 8 + 2] == 127.5
    assert result.maps.page_support[2 * 8 + 2] == 2
    assert result.maps.edge_fraction[5] is None


def test_actual_pixel_boundary_produces_edges_without_letterbox_edges(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    with Image.new("RGB", (8, 8), "white") as image:
        for y in range(8):
            for x in range(4):
                image.putpixel((x, y), (0, 0, 0))
        with io.BytesIO() as buffer:
            image.save(buffer, format="PNG")
            raw = buffer.getvalue()
    _ = (tmp_path / source.image.path).write_bytes(raw)
    source = source.model_copy(
        update={
            "image": ArtifactBinding(path=source.image.path, sha256=hashlib.sha256(raw).hexdigest())
        }
    )
    result = ghost_cluster(plan((source,)), lambda p: resolve(tmp_path, p))
    assert result.maps.edge_fraction[3] == 1
    assert result.maps.edge_fraction[2] == 0
    assert result.maps.edge_fraction[7] is None


def test_explicit_unavailable_assignment_does_not_become_zero_pixels(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, (0, 0, 0))
    request = plan((source,))
    missing = GhostMember(
        issue_id="fixture-missing",
        pdf_sha256="f" * 64,
        page_index=0,
        assignment_role="heldout-issue",
        page=None,
        unavailable_reason="Declared unavailable generated control.",
    )
    request = GhostPlan.model_validate(
        {
            **request.model_dump(),
            "members": (member(source), missing),
            "representative_page_keys": (source.page_key, missing.page_key),
        }
    )
    result = ghost_cluster(request, lambda p: resolve(tmp_path, p))
    assert result.eligible_source_pages == 1
    assert result.maps.mean_gray == (0.0,) * 64
    assert result.unavailable_page_keys == (missing.page_key,)
    figure = ghost_representatives(result, lambda p: resolve(tmp_path, p))
    records = REPRESENTATIVES_MANIFEST.validate_json(figure.manifest)["records"]
    assert records[1]["transform"] is None
    assert "Missing representatives" in figure.caption


def test_all_unavailable_is_null_and_not_a_blank_measured_page(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, (0, 0, 0))
    original = plan((source,))
    missing = GhostMember(
        issue_id=source.issue_id,
        pdf_sha256=source.pdf_sha256,
        page_index=0,
        assignment_role="train",
        page=None,
        unavailable_reason="No eligible PNG in generated control.",
    )
    request = GhostPlan.model_validate({**original.model_dump(), "members": (missing,)})
    result = ghost_cluster(request, lambda p: resolve(tmp_path, p))
    assert result.eligible_source_pages == result.eligible_issues == 0
    assert result.total_source_weight == 0
    assert result.maps.mean_gray == result.maps.population_variance == (None,) * 64
    assert result.maps.dark_fraction == result.maps.edge_fraction == (None,) * 64
    assert len(ghost_map_pngs(result)) == 6
    assert "0 eligible physical-page" in ghost_overview(result).caption


def test_maps_are_input_order_invariant_and_exact_replay_is_identical(tmp_path: Path) -> None:
    first = page(tmp_path, "fixture-a", 0, (0, 0, 0))
    second = page(tmp_path, "fixture-b", 0, (255, 255, 255))
    request = plan((first, second))
    direct = ghost_cluster(request, lambda p: resolve(tmp_path, p))
    again = ghost_cluster(request, lambda p: resolve(tmp_path, p))
    reversed_request = GhostPlan.model_validate(
        {**request.model_dump(), "members": tuple(reversed(request.members))}
    )
    reversed_result = ghost_cluster(reversed_request, lambda p: resolve(tmp_path, p))
    assert direct == again
    assert direct.maps == reversed_result.maps
    assert direct.transforms == reversed_result.transforms
    assert ghost_overview(direct) == ghost_overview(again)
    assert ghost_representatives(direct, lambda p: resolve(tmp_path, p)) == ghost_representatives(
        again, lambda p: resolve(tmp_path, p)
    )
    pngs = ghost_map_pngs(direct)
    assert len(pngs) == 6
    with Image.open(io.BytesIO(pngs[0])) as image:
        assert image.getpixel((0, 0)) == 128


def test_changed_available_payload_stops_instead_of_silent_eligibility_loss(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    _ = (tmp_path / source.image.path).write_bytes(b"changed")
    with pytest.raises(StudyError, match="digest/byte"):
        _ = ghost_cluster(plan((source,)), lambda p: resolve(tmp_path, p))


def test_result_scalar_edits_cannot_change_its_declared_denominator(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    result = ghost_cluster(plan((source,)), lambda p: resolve(tmp_path, p))
    for change in (
        {"eligible_source_pages": 2},
        {"unavailable_page_keys": (source.page_key,)},
        {"total_source_weight": 2.0},
        {"transforms": ()},
        {"issue_weights": ()},
    ):
        with pytest.raises(ValidationError):
            _ = GhostAggregate.model_validate({**result.model_dump(), **change})
