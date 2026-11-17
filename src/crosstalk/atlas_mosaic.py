"""Aspect-preserving cover sheets retain an explicit slot for every declared source unit."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from crosstalk.atlas_lineage import implementation_digest
from crosstalk.atlas_pixels import encode_png, normalize_page
from crosstalk.atlas_records import (
    CoverMosaicPlan,
    MosaicSettings,
    PageImage,
    PixelSettings,
    RasterFigure,
)
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import JsonValue

    from crosstalk.atlas_records import CoverSlot, PageTransform

_STATUS_LABEL = {
    "verified-cover": "COVER",
    "candidate-first-retained-page": "UNVERIFIED",
    "not-located-in-inspected-pdf": "NOT IN PDF",
    "unavailable": "UNAVAILABLE",
}


def cover_slot_label(slot: CoverSlot) -> str:
    """An inspected newsletter front page is not relabelled an outer cover."""
    if slot.status == "verified-cover" and slot.selected_role == "issue-front-page":
        return "FRONT PAGE"
    return _STATUS_LABEL[slot.status]


def _text(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int, available: int
) -> None:
    """Refuse clipped labels rather than silently abbreviating a source identity."""
    font = ImageFont.load_default(size=size)
    box = draw.textbbox((0, 0), value, font=font)
    if box[2] - box[0] > available:
        raise StudyError("atlas label exceeds its tile; select shorter unique overview labels")
    draw.text(xy, value, font=font, fill="black")


def _geometry(count: int, settings: MosaicSettings) -> tuple[int, int, int, int]:
    columns = min(settings.columns, count)
    rows = math.ceil(count / columns)
    width = max(
        columns * (settings.tile_width + settings.gutter) + settings.gutter,
        12 * (settings.font_pixels + 3),
    )
    header = max(32, settings.font_pixels * 3)
    height = (
        header
        + rows * (settings.tile_height + settings.label_height + settings.gutter)
        + settings.gutter
    )
    if width * height > settings.maximum_sheet_pixels:
        raise StudyError("cover sheet exceeds its declared allocation; split into more sheets")
    return width, height, columns, header


def _tile(
    canvas: Image.Image,
    slot: CoverSlot,
    box: tuple[int, int, int, int],
    settings: MosaicSettings,
    resolve: Callable[[PageImage], bytes],
) -> PageTransform | None:
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = box
    transform = None
    if slot.status == "verified-cover":
        if slot.page is None:
            raise StudyError("verified cover has no source page")
        pixels = settings.source_pixels.model_copy(
            update={"width": settings.tile_width, "height": settings.tile_height}
        )
        # Revalidate rather than allowing model_copy to bypass allocation constraints.
        pixels = PixelSettings.model_validate(pixels.model_dump())
        normalized = normalize_page(resolve(slot.page), slot.page, pixels)
        try:
            canvas.paste(normalized.rgb, (left, top))
            transform = normalized.transform
        finally:
            normalized.rgb.close()
    else:
        draw.rectangle(box, fill="#eeeeee")
        draw.line((left, top, right, bottom), fill="#cccccc", width=1)
        draw.line((right, top, left, bottom), fill="#cccccc", width=1)
    draw.rectangle(box, outline="#777777", width=1)
    _text(draw, (left, bottom + 1), slot.display_label, settings.font_pixels, settings.tile_width)
    _text(
        draw,
        (left, bottom + settings.font_pixels + 3),
        cover_slot_label(slot),
        settings.font_pixels,
        settings.tile_width,
    )
    return transform


DEFAULT_SETTINGS = MosaicSettings()


def cover_mosaic(
    plan: CoverMosaicPlan,
    resolve: Callable[[PageImage], bytes],
    settings: MosaicSettings = DEFAULT_SETTINGS,
) -> tuple[RasterFigure, ...]:
    """Create overview or detail sheets; unverified candidates are placeholders, never cover pixels.

    The resolver returns exact previously admitted PNG bytes. This function checks those bytes
    but does not grant source admission, infer a cover, crawl, or publish a file.
    """
    counts = Counter(slot.status for slot in plan.slots)
    roles = Counter(slot.selected_role for slot in plan.slots if slot.selected_role is not None)
    method = implementation_digest()
    plan_sha = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
    sheets = math.ceil(len(plan.slots) / settings.slots_per_sheet)
    output: list[RasterFigure] = []
    byte_count = 0
    for number, offset in enumerate(range(0, len(plan.slots), settings.slots_per_sheet), 1):
        selected = plan.slots[offset : offset + settings.slots_per_sheet]
        width, height, columns, header = _geometry(len(selected), settings)
        tiles: list[dict[str, JsonValue | tuple[int, int, int, int]]] = []
        with Image.new("RGB", (width, height), "white") as canvas:
            draw = ImageDraw.Draw(canvas)
            _text(
                draw,
                (settings.gutter, 6),
                f"SLOTS {number}/{sheets}",
                settings.font_pixels + 3,
                width - 2 * settings.gutter,
            )
            for index, slot in enumerate(selected):
                row, column = divmod(index, columns)
                grid_width = columns * settings.tile_width + (columns - 1) * settings.gutter
                left = (width - grid_width) // 2 + column * (settings.tile_width + settings.gutter)
                top = header + row * (
                    settings.tile_height + settings.label_height + settings.gutter
                )
                box = left, top, left + settings.tile_width, top + settings.tile_height
                transform = _tile(canvas, slot, box, settings, resolve)
                tiles.append(
                    {
                        "slot_index": offset + index,
                        "slot": slot.model_dump(),
                        "box": box,
                        "source_pixels_displayed": slot.status == "verified-cover",
                        "transform": transform.model_dump() if transform is not None else None,
                    }
                )
            png = encode_png(canvas)
        byte_count += len(png)
        if byte_count > settings.maximum_output_bytes:
            raise StudyError("cover atlas exceeds its total encoded output bound")
        manifest = {
            "method": "visual-atlas-cover-1",
            "implementation_sha256": method,
            "input_plan_sha256": plan_sha,
            "source_frame": plan.source_frame.model_dump(),
            "annotation_receipt": plan.annotation_receipt.model_dump(),
            "aggregation_runtime": plan.aggregation_runtime.model_dump(),
            "order_basis": plan.order_basis,
            "settings": settings.model_dump(),
            "sheet": number,
            "sheets": sheets,
            "width": width,
            "height": height,
            "all_source_status_counts": dict(sorted(counts.items())),
            "selected_role_counts": dict(sorted(roles.items())),
            "tiles": tiles,
            "png_sha256": hashlib.sha256(png).hexdigest(),
            "source_pixels_recolored": False,
            "cover_inferred_from_page_position": False,
        }
        caption = (
            "Source-inspected covers and front-page atlas, sheet "
            + f"{number}/{sheets}: {len(selected)} of {len(plan.slots)} declared "
            + "source units. "
            + f"The full frame contains {roles['front-cover']} selected front "
            + f"covers and {roles['issue-front-page']} selected issue front "
            + "pages, "
            + f"{counts['candidate-first-retained-page']} unverified first-page candidates, "
            + f"{counts['not-located-in-inspected-pdf']} not located in inspected "
            + f"PDFs and {counts['unavailable']} unavailable. "
            + "Only source-inspected selections supply image pixels. Labels map "
            + "to full source identities; date/order basis remains separately "
            + "declared. "
            + "Source colors and complete page aspect ratios are retained; "
            + "resampling is a display transform, not a new cover classification."
        )
        output.append(
            RasterFigure(
                f"cover-atlas-{number:03d}",
                png,
                caption,
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            )
        )
    if implementation_digest() != method:
        raise StudyError("atlas producer changed during cover/front-page composition")
    return tuple(output)
