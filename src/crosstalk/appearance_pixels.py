"""Measure the exact standardized full render and derive its bounded preview."""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageStat

from .appearance_records import AppearanceError, AppearanceSettings, PixelCell, PixelSummary


@dataclass(frozen=True, slots=True)
class MeasuredPixels:
    """A bounded thumbnail accompanies full-render, separately denominated descriptors."""

    summary: PixelSummary
    png: bytes
    png_sha256: str
    thumbnail_width: int
    thumbnail_height: int


def _cells(image: Image.Image, settings: AppearanceSettings) -> tuple[PixelCell, ...]:
    """Partition every original render pixel exactly once without padding small images."""
    side = settings.grid_side
    cells: list[PixelCell] = []
    for row in range(side):
        for column in range(side):
            box = (
                image.width * column // side,
                image.height * row // side,
                image.width * (column + 1) // side,
                image.height * (row + 1) // side,
            )
            pixels = (box[2] - box[0]) * (box[3] - box[1])
            dark = 0
            if pixels:
                with image.crop(box) as cell:
                    dark = sum(cell.histogram()[: settings.dark_threshold])
            cells.append(
                PixelCell(
                    row=row,
                    column=column,
                    box=box,
                    pixels=pixels,
                    dark_pixels=dark,
                    dark_fraction=dark / pixels if pixels else None,
                )
            )
    return tuple(cells)


def measure_pixels(image: Image.Image, settings: AppearanceSettings) -> MeasuredPixels:
    """Retain physical pixel units and refuse unsupported color modes before measuring."""
    if image.mode != "RGB" or image.width * image.height > settings.max_pixels:
        raise AppearanceError("appearance measurement requires bounded RGB full-render pixels")
    pixels = image.width * image.height
    if pixels < 1:
        raise AppearanceError("appearance measurement requires a nonempty full render")
    means = ImageStat.Stat(image).mean
    with image.convert("L") as gray:
        histogram = gray.histogram()
        entropy = -sum((count / pixels) * math.log2(count / pixels) for count in histogram if count)
        dark = sum(histogram[: settings.dark_threshold])
        summary = PixelSummary(
            width=image.width,
            height=image.height,
            pixels=pixels,
            grayscale_entropy_bits=entropy,
            mean_rgb=(means[0], means[1], means[2]),
            dark_pixels=dark,
            dark_fraction=dark / pixels,
            cells=_cells(gray, settings),
        )
    with image.copy() as thumbnail, io.BytesIO() as buffer:
        thumbnail.thumbnail(
            (settings.thumbnail_edge, settings.thumbnail_edge), Image.Resampling.LANCZOS
        )
        thumbnail.save(buffer, format="PNG", optimize=False, compress_level=6)
        png = buffer.getvalue()
        dimensions = thumbnail.size
    if len(png) > 4_000_000:
        raise AppearanceError("appearance thumbnail exceeds its four MB output byte bound")
    return MeasuredPixels(
        summary, png, hashlib.sha256(png).hexdigest(), dimensions[0], dimensions[1]
    )
