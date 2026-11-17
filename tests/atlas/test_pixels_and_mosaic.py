"""Source-byte, aspect, placeholder and pagination controls use real generated PNG files."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING, TypedDict

import pytest
from PIL import Image
from pydantic import TypeAdapter, ValidationError

from crosstalk.atlas_mosaic import cover_mosaic, cover_slot_label
from crosstalk.atlas_pixels import decode_png, grayscale_png, normalize_page
from crosstalk.atlas_records import (
    ArtifactBinding,
    CoverMosaicPlan,
    CoverSlot,
    MosaicSettings,
    PixelSettings,
)
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from pathlib import Path

from .fixtures import binding, page, resolve


class TileRecord(TypedDict):
    slot_index: int
    source_pixels_displayed: bool
    box: tuple[int, int, int, int]


class MosaicManifest(TypedDict):
    tiles: list[TileRecord]
    selected_role_counts: dict[str, int]
    png_sha256: str


MOSAIC_MANIFEST = TypeAdapter(MosaicManifest)


def test_whole_page_fit_preserves_aspect_and_marks_padding(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, (255, 0, 0), (4, 8))
    result = normalize_page(resolve(tmp_path, source), source, PixelSettings(width=8, height=8))
    try:
        assert result.transform.placed_box == (2, 0, 6, 8)
        assert result.transform.actual_scale_x == result.transform.actual_scale_y == 1
        assert result.rgb.getpixel((0, 0)) == (255, 255, 255)
        assert result.rgb.getpixel((3, 2)) == (255, 0, 0)
    finally:
        result.rgb.close()


def test_png_identity_and_geometry_must_match(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    raw = resolve(tmp_path, source)
    with pytest.raises(StudyError, match="digest/byte"):
        _ = decode_png(raw + b"changed", source, PixelSettings())
    with pytest.raises(StudyError, match="dimensions"):
        _ = decode_png(raw, source.model_copy(update={"width": 9}), PixelSettings())
    with pytest.raises(StudyError, match="dimensions"):
        _ = decode_png(raw, source, PixelSettings(maximum_source_pixels=63))


def test_alpha_source_is_not_silently_composited(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, (255, 0, 0, 128))
    with pytest.raises(StudyError, match="opaque"):
        _ = decode_png(resolve(tmp_path, source), source, PixelSettings())


def test_l_source_remains_opaque_and_display_values_are_bounded(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 128)
    with decode_png(resolve(tmp_path, source), source, PixelSettings()) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (128, 128, 128)
    with pytest.raises(StudyError, match="dimensions/range"):
        _ = grayscale_png((256,), 1, 1)
    with pytest.raises(StudyError, match="dimensions/range"):
        _ = grayscale_png((0,), 2, 1)


def test_mosaic_retains_missing_slots_without_reading_candidates(tmp_path: Path) -> None:
    cover = page(tmp_path, "fixture-a", 1, (255, 0, 0))
    candidate = page(tmp_path, "fixture-b", 0, (0, 0, 255))
    slots = (
        CoverSlot(
            unit_id="A",
            source_family="generated-fixture",
            issue_id=cover.issue_id,
            pdf_sha256=cover.pdf_sha256,
            display_label="001",
            status="verified-cover",
            selected_role="front-cover",
            page=cover,
            selection_evidence=binding("cover"),
            note="Explicit generated control.",
        ),
        CoverSlot(
            unit_id="B",
            source_family="generated-fixture",
            issue_id=candidate.issue_id,
            pdf_sha256=candidate.pdf_sha256,
            display_label="002",
            status="candidate-first-retained-page",
            page=candidate,
            selection_evidence=binding("candidate"),
            note="Could be a wrapper; not a verified cover.",
        ),
        CoverSlot(
            unit_id="C",
            source_family="generated-fixture",
            issue_id="fixture-c",
            pdf_sha256=None,
            display_label="003",
            status="not-located-in-inspected-pdf",
            page=None,
            selection_evidence=binding("missing"),
            note="Retained extent lacks an identified front page.",
        ),
        CoverSlot(
            unit_id="D",
            source_family="generated-fixture",
            issue_id="fixture-d",
            pdf_sha256=None,
            display_label="004",
            status="unavailable",
            page=None,
            selection_evidence=binding("unavailable"),
            note="No eligible source image.",
        ),
    )
    request = CoverMosaicPlan(
        source_frame=binding("frame"),
        annotation_receipt=binding("annotations"),
        aggregation_runtime=binding("runtime"),
        order_basis="Explicit generated order, not historical chronology.",
        declared_source_units=4,
        slots=slots,
    )
    # Removing the candidate's actual file demonstrates that it is not opened as cover evidence.
    (tmp_path / candidate.image.path).unlink()
    settings = MosaicSettings(columns=2, slots_per_sheet=2)
    figures = cover_mosaic(request, lambda p: resolve(tmp_path, p), settings)
    assert len(figures) == 2
    manifests = [MOSAIC_MANIFEST.validate_json(f.manifest) for f in figures]
    assert [tile["slot_index"] for m in manifests for tile in m["tiles"]] == [0, 1, 2, 3]
    assert sum(tile["source_pixels_displayed"] for m in manifests for tile in m["tiles"]) == 1
    assert manifests[0]["selected_role_counts"] == {"front-cover": 1}
    assert all(
        hashlib.sha256(f.png).hexdigest() == m["png_sha256"]
        for f, m in zip(figures, manifests, strict=True)
    )
    repeated = cover_mosaic(request, lambda p: resolve(tmp_path, p), settings)
    assert repeated == figures
    first = manifests[0]["tiles"][0]["box"]
    with Image.open(io.BytesIO(figures[0].png)) as image:
        assert image.getpixel(((first[0] + first[2]) // 2, (first[1] + first[3]) // 2)) == (
            255,
            0,
            0,
        )


def test_mosaic_scope_and_allocation_refusals(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0)
    slot = CoverSlot(
        unit_id="A",
        source_family="generated-fixture",
        issue_id=source.issue_id,
        pdf_sha256=source.pdf_sha256,
        display_label="001",
        status="verified-cover",
        selected_role="issue-front-page",
        page=source,
        selection_evidence=binding(),
        note="Newsletter-style generated front page.",
    )
    assert cover_slot_label(slot) == "FRONT PAGE"
    assert cover_slot_label(slot.model_copy(update={"selected_role": "front-cover"})) == "COVER"
    with pytest.raises(ValidationError, match="incomplete or repeated"):
        _ = CoverMosaicPlan(
            source_frame=binding(),
            annotation_receipt=binding(),
            aggregation_runtime=binding("runtime"),
            order_basis="Declared order",
            declared_source_units=2,
            slots=(slot,),
        )
    request = CoverMosaicPlan(
        source_frame=binding(),
        annotation_receipt=binding(),
        aggregation_runtime=binding("runtime"),
        order_basis="Declared order",
        declared_source_units=1,
        slots=(slot,),
    )
    with pytest.raises(StudyError, match="allocation"):
        _ = cover_mosaic(
            request, lambda p: resolve(tmp_path, p), MosaicSettings(maximum_sheet_pixels=1000)
        )
    with pytest.raises(ValidationError, match="both declared text"):
        _ = MosaicSettings(label_height=20, font_pixels=12)
    with pytest.raises(ValidationError, match="cover tile"):
        _ = MosaicSettings(tile_width=512, tile_height=768)
    with pytest.raises(ValidationError, match="source page"):
        _ = slot.model_validate({**slot.model_dump(), "page": None})
    with pytest.raises(ValidationError, match="role requires"):
        _ = slot.model_validate({**slot.model_dump(), "selected_role": None})


def test_encoded_output_budget_preserves_a_real_high_detail_source(tmp_path: Path) -> None:
    source = page(tmp_path, "fixture-a", 0, 0, size=(64, 64))
    raw_pixels = bytes((index * 73) % 251 for index in range(64 * 64 * 3))
    with Image.frombytes("RGB", (64, 64), raw_pixels) as image, io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        raw = buffer.getvalue()
    target = tmp_path / source.image.path
    _ = target.write_bytes(raw)
    source = source.model_copy(
        update={
            "image": ArtifactBinding(path=source.image.path, sha256=hashlib.sha256(raw).hexdigest())
        }
    )
    slot = CoverSlot(
        unit_id="A",
        source_family="generated-fixture",
        issue_id=source.issue_id,
        pdf_sha256=source.pdf_sha256,
        display_label="001",
        status="verified-cover",
        selected_role="front-cover",
        page=source,
        selection_evidence=binding(),
        note="Explicit generated high-detail source.",
    )
    request = CoverMosaicPlan(
        source_frame=binding(),
        annotation_receipt=binding(),
        aggregation_runtime=binding("runtime"),
        order_basis="Generated",
        declared_source_units=1,
        slots=(slot,),
    )
    figures = cover_mosaic(request, lambda p: resolve(tmp_path, p))
    assert len(figures[0].png) > 1000
    with pytest.raises(StudyError, match="output bound"):
        _ = cover_mosaic(
            request, lambda p: resolve(tmp_path, p), MosaicSettings(maximum_output_bytes=1000)
        )


@pytest.mark.parametrize(
    "value", ["../escape.json", "/absolute.json", "./relative.json", "bad\\path.json", "."]
)
def test_artifact_binding_cannot_expand_filesystem_scope(value: str) -> None:
    with pytest.raises(ValidationError, match="project-local"):
        _ = ArtifactBinding(path=value, sha256="a" * 64)
