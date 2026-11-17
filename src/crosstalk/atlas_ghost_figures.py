"""Ghost displays expose coverage and unchanged representative page images together."""

from __future__ import annotations

import hashlib
import io
import json
import math
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from crosstalk.atlas_pixels import encode_png, grayscale_png, normalize_page
from crosstalk.atlas_records import PageImage, RasterFigure
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import JsonValue

    from crosstalk.atlas_ghost_records import GhostAggregate

_PANELS = (
    "MEAN GRAY",
    "VARIATION (SD)",
    "DARK FRACTION",
    "EDGE FRACTION",
    "VIEWPORT SUPPORT",
    "EDGE SUPPORT",
)


def _gray(value: float | None, index: int, width: int, *, inverted: bool, scale: float) -> int:
    """Display missing pixels as a light checker, never as zero-valued source observations."""
    if value is None:
        x, y = index % width, index // width
        return 232 if (x // 4 + y // 4) % 2 else 255
    if not 0 <= value <= scale + 1e-8:
        raise StudyError("ghost display value exceeds its explicitly fixed scale")
    value = min(scale, value) / scale
    return math.floor(255 * (1 - value if inverted else value) + 0.5)


def ghost_map_pngs(result: GhostAggregate) -> tuple[bytes, ...]:
    """Fixed display scales preserve comparisons across supplied clusters/settings."""
    maps = result.maps
    stddev = tuple(
        math.sqrt(value) if value is not None else None for value in maps.population_variance
    )
    support = tuple(
        value / result.total_source_weight if result.total_source_weight else None
        for value in maps.support_weight
    )
    edge_support = tuple(
        value / result.total_source_weight if result.total_source_weight else None
        for value in maps.edge_support_weight
    )
    rows = (
        (maps.mean_gray, False, 255.0),
        (stddev, True, 127.5),
        (maps.dark_fraction, True, 1.0),
        (maps.edge_fraction, True, 1.0),
        (support, True, 1.0),
        (edge_support, True, 1.0),
    )
    return tuple(
        grayscale_png(
            tuple(
                _gray(value, index, maps.width, inverted=inverted, scale=scale)
                for index, value in enumerate(values)
            ),
            maps.width,
            maps.height,
        )
        for values, inverted, scale in rows
    )


def _label(
    draw: ImageDraw.ImageDraw, position: tuple[int, int], value: str, width: int, size: int = 14
) -> None:
    font = ImageFont.load_default(size=size)
    bounds = draw.textbbox((0, 0), value, font=font)
    if bounds[2] - bounds[0] > width:
        raise StudyError("ghost panel label exceeds its declared width")
    draw.text(position, value, font=font, fill="black")


def _caption(result: GhostAggregate) -> str:
    missing = len(result.unavailable_page_keys)
    return (
        f"Cluster {result.plan.cluster_id}: {result.eligible_source_pages} "
        + "eligible physical-page images "
        + f"from {result.eligible_issues} issues; {missing} assigned pages "
        + "lack declared eligible pixels. "
        + f"Weighting is {result.plan.weighting}; each pixel divides by actual viewport support. "
        + "Equal-issue mode fixes each page weight to one divided by its "
        + "issue's eligible-page count; partial local viewport support "
        + "retains that fractional weight. "
        + "Panels show mean grayscale (0-255), population SD (0-127.5), threshold-dark fraction, "
        + "forward-gradient edge fraction and their support fractions (0-1). "
        + "Darker means larger values except the mean-gray panel. "
        + "Checker cells have no corresponding pixel support. Complete "
        + "viewports are isotropically fitted with white padding excluded; "
        + "no registration, cropping or semantic classification is "
        + "performed. Variation is descriptive heterogeneity, not an "
        + "uncertainty interval."
    )


def ghost_overview(result: GhostAggregate) -> RasterFigure:
    """Show all six complementary maps so a smooth ghost cannot hide uneven support."""
    width, height = result.maps.width, result.maps.height
    gutter, header, label = 16, 45, 28
    panel_width = max(width, 180)
    frame_width = 3 * panel_width + 4 * gutter
    frame_height = header + 2 * (height + label + gutter)
    images = ghost_map_pngs(result)
    with Image.new("RGB", (frame_width, frame_height), "white") as canvas:
        draw = ImageDraw.Draw(canvas)
        _label(draw, (gutter, 8), f"GHOST / {result.plan.cluster_id}", frame_width - 2 * gutter, 18)
        for index, (title, raw) in enumerate(zip(_PANELS, images, strict=True)):
            row, column = divmod(index, 3)
            left = gutter + column * (panel_width + gutter)
            top = header + row * (height + label + gutter)
            _label(draw, (left, top), title, panel_width)
            with Image.open(io.BytesIO(raw)) as panel:
                canvas.paste(panel, (left, top + label))
        png = encode_png(canvas)
    manifest = {
        "method": "visual-atlas-ghost-display-1",
        "aggregate_sha256": hashlib.sha256(result.model_dump_json().encode()).hexdigest(),
        "implementation_sha256": result.implementation_sha256,
        "input_plan_sha256": result.input_plan_sha256,
        "panel_names": _PANELS,
        "panel_png_sha256": tuple(hashlib.sha256(raw).hexdigest() for raw in images),
        "png_sha256": hashlib.sha256(png).hexdigest(),
        "display_scales": ((0, 255), (0, 127.5), (0, 1), (0, 1), (0, 1), (0, 1)),
        "unknown_pixels": "4-pixel light checker, not a measured zero",
        "cluster_semantics_inferred": False,
    }
    return RasterFigure(
        f"ghost-{result.plan.cluster_id}",
        png,
        _caption(result),
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    )


def ghost_representatives(
    result: GhostAggregate, resolve: Callable[[PageImage], bytes]
) -> RasterFigure:
    """Show the caller's exact medoid/exemplar list; never replace an unavailable representative."""
    selected = result.plan.representative_page_keys
    members = {member.page_key: member for member in result.plan.members}
    columns = min(3, len(selected))
    width, height = result.plan.pixels.width, result.plan.pixels.height
    panel_width, gutter, header, label = max(width, 180), 16, 45, 28
    frame_width = columns * (panel_width + gutter) + gutter
    frame_height = header + math.ceil(len(selected) / columns) * (height + label + gutter)
    records: list[dict[str, JsonValue]] = []
    with Image.new("RGB", (frame_width, frame_height), "white") as canvas:
        draw = ImageDraw.Draw(canvas)
        _label(draw, (gutter, 8), "REPRESENTATIVES", frame_width - 2 * gutter, 16)
        for index, key in enumerate(selected):
            member = members[key]
            row, column = divmod(index, columns)
            left, top = (
                gutter + column * (panel_width + gutter),
                header + row * (height + label + gutter),
            )
            _label(draw, (left, top), f"SOURCE {index + 1:02d}", panel_width)
            transform = None
            if member.page is not None:
                page = normalize_page(resolve(member.page), member.page, result.plan.pixels)
                try:
                    canvas.paste(page.rgb, (left, top + label))
                    transform = page.transform.model_dump()
                finally:
                    page.rgb.close()
            else:
                draw.rectangle(
                    (left, top + label, left + width, top + label + height),
                    fill="#eeeeee",
                    outline="#777777",
                )
                _label(draw, (left + 4, top + label + 10), "UNAVAILABLE", panel_width - 8, 12)
            records.append(
                {"display_source": index + 1, "member": member.model_dump(), "transform": transform}
            )
        png = encode_png(canvas)
    caption = (
        "Original source-image representatives for cluster "
        + f"{result.plan.cluster_id}, in the exact supplied order. "
        + f"Selection basis: {result.plan.representative_basis} "
        + "Colors and complete aspect ratios are retained; normalization is a display transform. "
        + "Missing representatives remain labelled placeholders. These "
        + "examples do not validate semantic cluster identity or represent "
        + "every member."
    )
    manifest = {
        "method": "visual-atlas-representatives-1",
        "input_plan_sha256": result.input_plan_sha256,
        "clustering_receipt": result.plan.clustering_receipt.model_dump(),
        "records": records,
        "png_sha256": hashlib.sha256(png).hexdigest(),
        "source_pixels_recolored": False,
    }
    return RasterFigure(
        f"ghost-{result.plan.cluster_id}-representatives",
        png,
        caption,
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    )
