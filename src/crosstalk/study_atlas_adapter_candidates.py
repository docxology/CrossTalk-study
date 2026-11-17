"""Explicit inspection sheets display provisional source pages without calling them covers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable  # noqa: TC003 -- Pydantic/native callback boundary.
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont
from pydantic import Field, model_validator

from crosstalk.atlas_pixels import encode_png, normalize_page
from crosstalk.atlas_records import ArtifactBinding, PageImage, PixelSettings, RasterFigure
from crosstalk.study_language_records import Record, StudyError

if TYPE_CHECKING:
    from crosstalk.cover_records import CoverDecision
    from crosstalk.study_atlas_adapter_records import AtlasInputFrame


class CandidateTile(Record):
    """A queue location, including a source slot with no usable candidate image."""

    unit_id: str
    display_label: str = Field(pattern=r"^[ -~]{1,32}$")
    page_index: int | None = Field(ge=0)
    page: PageImage | None
    reason: str
    selection_status: str


class CandidateSheets(Record):
    """Every declared source retains a slot without gaining cover status."""

    source_frame: ArtifactBinding
    candidate_receipt: ArtifactBinding
    aggregation_runtime: ArtifactBinding
    declared_units: tuple[str, ...]
    tiles: tuple[CandidateTile, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def complete_queue(self) -> CandidateSheets:
        """Retain empty candidate slots; reject duplicate or omitted source units."""
        if len(set(self.declared_units)) != len(self.declared_units) or {
            tile.unit_id for tile in self.tiles
        } != set(self.declared_units):
            raise StudyError("candidate sheets omit or repeat declared source units")
        identities = tuple((tile.unit_id, tile.page_index) for tile in self.tiles)
        if len(set(identities)) != len(identities):
            raise StudyError("candidate sheet repeats one physical source slot")
        for tile in self.tiles:
            if tile.page is not None and tile.page.page_index != tile.page_index:
                raise StudyError("candidate image and declared physical page disagree")
        return self


class CandidateSelection(Record):
    """Queue and runtime receipts are supplied after their own independent source admission."""

    candidate_receipt: ArtifactBinding
    aggregation_runtime: ArtifactBinding


def candidate_plan(
    frame: AtlasInputFrame, decisions: tuple[CoverDecision, ...], selection: CandidateSelection
) -> CandidateSheets:
    """Bridge the candidate queue without granting inspected-cover status."""
    units = {unit.unit_id: unit for unit in frame.units}
    known = {slot.page_key: slot for slot in frame.pages}
    if {row.unit.unit_id for row in decisions} != set(units) or len(decisions) != len(units):
        raise StudyError("candidate decisions do not retain the declared source frame")
    tiles: list[CandidateTile] = []
    for number, decision in enumerate(sorted(decisions, key=lambda item: item.unit.unit_id), 1):
        unit = units[decision.unit.unit_id]
        if (decision.unit.issue_id, decision.unit.pdf_sha256, decision.unit.physical_pages) != (
            unit.issue_id,
            unit.pdf.sha256,
            unit.physical_pages,
        ):
            raise StudyError("candidate decision source identity disagrees")
        if not decision.candidate_page_indices:
            tiles.append(
                CandidateTile(
                    unit_id=unit.unit_id,
                    display_label=f"I{number:03d}",
                    page_index=None,
                    page=None,
                    reason=decision.note,
                    selection_status="NO CANDIDATE",
                )
            )
        for index in decision.candidate_page_indices:
            slot = known[f"{unit.pdf.sha256}:{index}"]
            image = slot.appearance.image if slot.appearance is not None else None
            tiles.append(
                CandidateTile(
                    unit_id=unit.unit_id,
                    display_label=f"I{number:03d} p{index:03d}",
                    page_index=index,
                    page=image,
                    reason=decision.note + " " + slot.reason,
                    selection_status="CANDIDATE" if image is not None else "UNAVAILABLE",
                )
            )
    return CandidateSheets(
        source_frame=frame.receipt,
        candidate_receipt=selection.candidate_receipt,
        aggregation_runtime=selection.aggregation_runtime,
        declared_units=tuple(sorted(units)),
        tiles=tuple(tiles),
    )


def _label(
    draw: ImageDraw.ImageDraw, position: tuple[int, int], value: str, available: int
) -> None:
    """Reject oversized labels rather than clipping or abbreviating them."""
    font = ImageFont.load_default(size=12)
    bounds = draw.textbbox((0, 0), value, font=font)
    if bounds[2] - bounds[0] > available:
        raise StudyError("candidate-sheet label exceeds its declared width")
    draw.text(position, value, font=font, fill="black")


def render_candidate_sheets(
    plan: CandidateSheets, resolve: Callable[[PageImage], bytes]
) -> tuple[RasterFigure, ...]:
    """Render at most48 provisional source images with original RGB pixels per sheet."""
    settings = PixelSettings(width=144, height=192)
    columns, per_sheet, gutter, label, header = 6, 48, 12, 36, 54
    result: list[RasterFigure] = []
    for sheet, offset in enumerate(range(0, len(plan.tiles), per_sheet), 1):
        tiles = plan.tiles[offset : offset + per_sheet]
        width = gutter + columns * (settings.width + gutter)
        height = header + math.ceil(len(tiles) / columns) * (settings.height + label + gutter)
        if width * height > 12_000_000:
            raise StudyError("candidate-sheet pixel capacity exceeded")
        with Image.new("RGB", (width, height), "white") as canvas:
            draw = ImageDraw.Draw(canvas)
            _label(
                draw, (gutter, 8), "INSPECTION CANDIDATES / NOT COVER DECISIONS", width - 2 * gutter
            )
            for index, tile in enumerate(tiles):
                row, column = divmod(index, columns)
                left, top = (
                    gutter + column * (settings.width + gutter),
                    header + row * (settings.height + label + gutter),
                )
                if tile.page is not None:
                    normalized = normalize_page(resolve(tile.page), tile.page, settings)
                    try:
                        canvas.paste(normalized.rgb, (left, top))
                    finally:
                        normalized.rgb.close()
                else:
                    draw.rectangle(
                        (left, top, left + settings.width, top + settings.height),
                        fill="#dddddd",
                        outline="black",
                    )
                _label(draw, (left, top + settings.height + 2), tile.display_label, settings.width)
                _label(
                    draw, (left, top + settings.height + 17), tile.selection_status, settings.width
                )
            png = encode_png(canvas)
        manifest = json.dumps(
            {
                "method": "atlas-inspection-queue-1",
                "source_frame": plan.source_frame.model_dump(),
                "candidate_receipt": plan.candidate_receipt.model_dump(),
                "aggregation_runtime": plan.aggregation_runtime.model_dump(),
                "declared_units": plan.declared_units,
                "sheet": sheet,
                "tile_offset": offset,
                "tiles": tuple(tile.model_dump() for tile in tiles),
                "png_sha256": hashlib.sha256(png).hexdigest(),
                "all_images_provisional": True,
                "source_pixels_recolored": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        result.append(
            RasterFigure(
                f"cover-inspection-{sheet:03d}",
                png,
                (
                    f"Provisional source-page inspection queue, sheet{sheet}: "
                    + f"{len(tiles)} retained candidate slots from{len(plan.declared_units)} "
                    + "declared PDF units. Physical indices are zero-based. "
                    + "These images are not cover selections; original source colors/aspect "
                    + "ratios remain intact."
                ),
                manifest,
            )
        )
    return tuple(result)
