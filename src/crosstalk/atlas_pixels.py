"""Bounded PNG decoding and aspect-preserving page normalization use original admitted pixels."""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

from PIL import Image
from pydantic import ConfigDict, TypeAdapter

from crosstalk.atlas_records import PageImage, PageTransform, PixelSettings
from crosstalk.study_language_records import StudyError

GRAY = TypeAdapter(tuple[int, ...])
IMAGE = TypeAdapter(Image.Image, config=ConfigDict(arbitrary_types_allowed=True))


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    """RGB page with white padding, grayscale values, and an explicit observed-region mask."""

    rgb: Image.Image
    gray: tuple[int, ...]
    transform: PageTransform


def encode_png(image: Image.Image) -> bytes:
    """Use a fixed nonoptimized encoding; exact bytes remain runtime/version bound."""
    with io.BytesIO() as output:
        image.save(output, format="PNG", optimize=False, compress_level=6)
        return output.getvalue()


def decode_png(raw: bytes, page: PageImage, settings: PixelSettings) -> Image.Image:
    """Verify digest, dimensions, mode and actual decode without changing global Pillow policy."""
    if (
        not 0 < len(raw) <= settings.maximum_png_bytes
        or hashlib.sha256(raw).hexdigest() != page.image.sha256
    ):
        raise StudyError("atlas source PNG differs from its declared digest/byte bound")
    with Image.open(io.BytesIO(raw)) as source:
        if (
            source.format != "PNG"
            or source.mode not in {"RGB", "L"}
            or getattr(source, "n_frames", 1) != 1
        ):
            raise StudyError("atlas input must be a single-frame opaque RGB or L PNG")
        if (
            source.size != (page.width, page.height)
            or source.width * source.height > settings.maximum_source_pixels
        ):
            raise StudyError("atlas source PNG dimensions differ or exceed the source bound")
        source.verify()
    with Image.open(io.BytesIO(raw)) as source:
        _ = source.load()
        return source.convert("RGB")


def normalize_page(raw: bytes, page: PageImage, settings: PixelSettings) -> NormalizedPage:
    """Fit the full viewport; preserve aspect ratio to integer-pixel rounding."""
    with decode_png(raw, page, settings) as source:
        scale = min(settings.width / source.width, settings.height / source.height)
        width = min(settings.width, max(1, math.floor(source.width * scale + 0.5)))
        height = min(settings.height, max(1, math.floor(source.height * scale + 0.5)))
        left, top = (settings.width - width) // 2, (settings.height - height) // 2
        canvas = Image.new("RGB", (settings.width, settings.height), "white")
        with IMAGE.validate_python(
            getattr(source, "resize")((width, height), Image.Resampling.LANCZOS)  # noqa: B009 -- parse external return.
        ) as resized:
            canvas.paste(resized, (left, top))
    with canvas.convert("L") as gray:
        values = GRAY.validate_python(getattr(gray, "getdata")())  # noqa: B009 -- parse Pillow's partially typed external pixel sequence once.
    if len(values) != settings.width * settings.height or any(
        not 0 <= value <= 255 for value in values
    ):
        canvas.close()
        raise StudyError("normalized atlas grayscale sample count/range disagrees")
    geometry = f"RGB:{settings.width}:{settings.height}:3\0".encode()
    transform = PageTransform(
        page_key=page.page_key,
        source_png_sha256=page.image.sha256,
        source_width=page.width,
        source_height=page.height,
        canvas_width=settings.width,
        canvas_height=settings.height,
        placed_box=(left, top, left + width, top + height),
        nominal_isotropic_scale=scale,
        actual_scale_x=width / page.width,
        actual_scale_y=height / page.height,
        normalized_rgb_sha256=hashlib.sha256(geometry + canvas.tobytes()).hexdigest(),
    )
    return NormalizedPage(canvas, values, transform)


def grayscale_png(values: tuple[int, ...], width: int, height: int) -> bytes:
    """Encode one explicitly scaled display, not an inferred semantic pixel map."""
    if len(values) != width * height or any(not 0 <= value <= 255 for value in values):
        raise StudyError("atlas display values disagree with their pixel dimensions/range")
    with Image.frombytes("L", (width, height), bytes(values)) as image:
        return encode_png(image)
