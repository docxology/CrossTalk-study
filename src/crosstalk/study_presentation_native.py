"""Observe SVG/PDF/RGB output; parser text bounds remain distinct from sampled pixels."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable  # noqa: TC003 -- native callable projected by Pydantic at runtime.
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Literal

import pymupdf
from pydantic import ConfigDict, Field, TypeAdapter

from crosstalk.extraction_runtime import runtime_identity
from crosstalk.study_language_records import Record, StudyError
from crosstalk.study_presentation_records import NativeRenderObservation

if TYPE_CHECKING:
    from crosstalk.study_presentation_records import SvgPresentation

BYTES: Final = TypeAdapter(bytes)
IMAGES: Final = TypeAdapter(tuple[tuple[int, ...], ...])
TEXT_FLAGS: Final = TypeAdapter(int).validate_python(getattr(pymupdf, "TEXTFLAGS_TEXT"))  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
type BBox = tuple[float, float, float, float]


class PdfInfo(Record):
    """Only accessible single-page vector derivatives can cross this native boundary."""

    page_count: int
    needs_pass: Literal[0, 1]
    is_pdf: bool


class Rectangle(Record):
    """Actual native PDF geometry, before any raster allocation."""

    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Span(Record):
    """Native parser bounds/size are not treated as measured glyph ink."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="ignore", allow_inf_nan=False
    )
    bbox: BBox
    size: float = Field(gt=0)
    text: str


class Line(Record):
    """Only text spans are projected from the native dictionary result."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    spans: tuple[Span, ...]


class Block(Record):
    """A no-image text extraction produces finite text blocks."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    lines: tuple[Line, ...] = ()


class TextPage(Record):
    """Untrusted native output is parsed once before domain-level font/bounds checks."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    blocks: tuple[Block, ...]


class Pixels(Record):
    """Positive three-channel opaque RGB dimensions must agree with the copied sample count."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    n: int = Field(ge=3, le=3)
    alpha: int = Field(ge=0, le=0)
    samples: bytes
    tobytes: Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class RenderedVector:
    """Bound native sample observations and retained bytes support independent later image QA."""

    observation: NativeRenderObservation
    pdf: bytes
    png: bytes
    samples: bytes


def native_identity() -> str:
    """Bind exact PyMuPDF RECORD/native shared-library bytes as well as the reported version."""
    version = TypeAdapter(str).validate_python(pymupdf.VersionBind)
    identity = runtime_identity(Path(pymupdf.__file__).absolute().parent.parent, version)
    return hashlib.sha256(
        json.dumps(
            (version, identity.sha256, identity.files, identity.byte_count), separators=(",", ":")
        ).encode()
    ).hexdigest()


def _text(
    page: pymupdf.Page, request: SvgPresentation, frame: Rectangle
) -> tuple[int, float | None]:
    """Check parsed span extents and their point size at the declared final print width."""
    text = TextPage.model_validate(
        getattr(page, "get_text")("dict", flags=TEXT_FLAGS, clip=pymupdf.INFINITE_RECT()),  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
        strict=False,
    )
    sizes: list[float] = []
    for block in text.blocks:
        for line in block.lines:
            for span in line.spans:
                if not span.text.strip():
                    continue
                x0, y0, x1, y1 = span.bbox
                if not (0 <= x0 < x1 <= frame.width + 0.01 and 0 <= y0 < y1 <= frame.height + 0.01):
                    raise StudyError("native parser text bounds extend outside the figure")
                sizes.append(span.size * request.target_print_width_points / frame.width)
    minimum = min(sizes) if sizes else None
    if minimum is not None and minimum + 0.001 < request.minimum_print_font_points:
        raise StudyError(
            "figure text is below the requested final pri" + "nt size; bound-data redraw needed"
        )
    return len(sizes), minimum


def render_vector(raw: bytes, request: SvgPresentation) -> RenderedVector:
    """Convert actual admitted SVG, render at144dpi, and return only bounded opaque RGB pixels."""
    with pymupdf.open(stream=raw, filetype="svg") as source:
        converted = BYTES.validate_python(source.convert_to_pdf())
    with pymupdf.open(stream=converted, filetype="pdf") as document:
        info = PdfInfo.model_validate(document, from_attributes=True)
        if info.page_count != 1 or not info.is_pdf or info.needs_pass:
            raise StudyError("figure conversion did not produce an accessible single-page PDF")
        page = document[0]
        if IMAGES.validate_python(getattr(page, "get_images")()):  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
            raise StudyError("research-plot conversion unexpectedly contains raster evidence")
        frame = Rectangle.model_validate(getattr(page, "rect"), from_attributes=True)  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
        scale = request.render_dpi / 72
        if (
            math.ceil(frame.width * scale) * math.ceil(frame.height * scale)
            > request.maximum_render_pixels
        ):
            raise StudyError("actual SVG raster target exceeds the finite pixel bound")
        spans, minimum = _text(page, request, frame)
        pixels = Pixels.model_validate(
            getattr(page, "get_pixmap")(  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
                matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
            ),
            from_attributes=True,
        )
        if len(pixels.samples) != pixels.width * pixels.height * 3:
            raise StudyError("native RGB samples disagree with observed dimensions")
        png = BYTES.validate_python(pixels.tobytes("png"))
        pdf = BYTES.validate_python(
            getattr(document, "tobytes")(garbage=4, deflate=True, no_new_id=True)  # noqa: B009 -- Parse the partial native dependency through its typed boundary.
        )
    geometry = f"RGB:{pixels.width}:{pixels.height}:3\0".encode()
    observation = NativeRenderObservation(
        svg_sha256=hashlib.sha256(raw).hexdigest(),
        pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        rgb_matrix_sha256=hashlib.sha256(geometry + pixels.samples).hexdigest(),
        png_sha256=hashlib.sha256(png).hexdigest(),
        width_pixels=pixels.width,
        height_pixels=pixels.height,
        text_spans=spans,
        minimum_print_font_points=minimum,
    )
    return RenderedVector(observation, pdf, png, pixels.samples)
