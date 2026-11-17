"""Measure observed raster pixels with explicit decoder provenance and bounded fallback."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

import PIL
from PIL import Image, ImageStat
from pymupdf.mupdf import FzErrorBase

from crosstalk.image_native import MAX_IMAGE_PIXELS, native_pixels, read_visual_bytes
from crosstalk.models import AcquisitionError

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.analysis_records import PixelDecoder
    from crosstalk.records import ImageOccurrence, PageRecord


class RasterDecodeError(AcquisitionError):
    """One unavailable source asset; an initial Pillow failure survives native failure."""

    def __init__(
        self,
        path: str,
        stage: Literal["image-integrity", "image-pillow", "image-native"],
        error_type: str,
        reason: str,
        initial_error: str | None = None,
    ) -> None:
        """Keep typed fields while Python retains its mutable exception traceback protocol."""
        self.path: str = path
        self.stage: Literal["image-integrity", "image-pillow", "image-native"] = stage
        self.error_type: str = error_type
        self.reason: str = reason
        self.initial_error: str | None = initial_error
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        """Keep both decoder outcomes visible without disguising failed source admission."""
        first = f"; initial Pillow failure: {self.initial_error}" if self.initial_error else ""
        return f"{self.stage}: {self.path}: {self.error_type}: {self.reason}{first}"


@dataclass(frozen=True, slots=True)
class RasterMeasurement:
    """Finite image descriptors and the exact method used to obtain their pixels."""

    mean_rgb: tuple[float, float, float]
    entropy: float
    pixel_decoder: PixelDecoder
    pixel_decoder_version: str
    preview_png: bytes
    pixel_source_pdf: str | None = None
    pixel_source_sha256: str | None = None
    pixel_source_page_index: int | None = None
    pixel_source_xref: int | None = None
    pixel_decoder_initial_error: str | None = None


class RasterDimensionError(AcquisitionError):
    """A dimension/integrity disagreement must never enable a decoder fallback."""


def _measure(
    encoded: bytes, dimensions: tuple[int, int]
) -> tuple[tuple[float, float, float], float, bytes]:
    """Apply the same RGB thumbnail and entropy rules to either decoder's observed pixels."""
    with Image.open(io.BytesIO(encoded)) as source:
        if source.size != dimensions:
            raise RasterDimensionError(
                "decoded raster dimensions disagree with the saved occurrence"
            )
        with source.convert("RGB") as sample:
            sample.thumbnail((256, 256))
            means = ImageStat.Stat(sample).mean
            with sample.convert("L") as grayscale:
                entropy = grayscale.entropy()
            with io.BytesIO() as buffer:
                sample.save(buffer, format="PNG")
                png = buffer.getvalue()
    return (means[0], means[1], means[2]), entropy, png


def _native_measurement(
    root: Path, page: PageRecord, image: ImageOccurrence, encoded: bytes, initial: str
) -> RasterMeasurement:
    """Keep source-context decoding and both failure records at one typed boundary."""
    try:
        native = native_pixels(root, page, image, encoded)
        mean, entropy, png = _measure(native.png, (image.width, image.height))
    except (OSError, ValueError, RuntimeError, FzErrorBase) as error:
        raise RasterDecodeError(
            image.path or "unavailable", "image-native", type(error).__name__, str(error), initial
        ) from error
    return RasterMeasurement(
        mean,
        entropy,
        "pymupdf-source-context",
        native.version,
        png,
        native.source_pdf,
        native.source_sha256,
        native.source_page_index,
        native.source_xref,
        initial,
    )


def measure_raster(root: Path, page: PageRecord, image: ImageOccurrence) -> RasterMeasurement:
    """Use Pillow first; source-verified JPX may use native PDF context after decode failure."""
    relative = image.path or "unavailable"
    try:
        if image.path is None or image.width * image.height > MAX_IMAGE_PIXELS:
            raise AcquisitionError("saved image or 100M-pixel bound is unavailable")
        encoded = read_visual_bytes(root, image.path)
        if image.sha256 != hashlib.sha256(encoded).hexdigest():
            raise AcquisitionError("saved image digest differs from the sealed occurrence")
    except (OSError, ValueError) as error:
        raise RasterDecodeError(
            relative, "image-integrity", type(error).__name__, str(error)
        ) from error
    try:
        mean, entropy, png = _measure(encoded, (image.width, image.height))
    except (
        RasterDimensionError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise RasterDecodeError(
            relative, "image-integrity", type(error).__name__, str(error)
        ) from error
    except (OSError, ValueError) as error:
        initial = f"{type(error).__name__}: {error}"
        if not relative.lower().endswith((".jpx", ".jp2")):
            raise RasterDecodeError(
                relative, "image-pillow", type(error).__name__, str(error)
            ) from error
        result = _native_measurement(root, page, image, encoded, initial)
    else:
        result = RasterMeasurement(mean, entropy, "pillow", PIL.__version__, png)
    try:
        if read_visual_bytes(root, relative) != encoded:
            raise AcquisitionError("saved image changed during pixel measurement")
    except (OSError, ValueError) as error:
        raise RasterDecodeError(
            relative, "image-integrity", type(error).__name__, str(error)
        ) from error
    return result
