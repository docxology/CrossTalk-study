"""Bounded full-page OCR through MuPDF's explicit native Tesseract API."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, ClassVar, Final, Literal, assert_never

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pymupdf import utils

from crosstalk.ocr_records import Block, OcrError, PageResult, Status, TextlessBlock
from crosstalk.ocr_source import page_key

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.ocr_records import EngineBinding, Settings
    from crosstalk.ocr_source import PreparedPage

STR: Final = TypeAdapter(str)
type NativeBlock = tuple[float, float, float, float, str, int, int]

BLOCKS: Final = TypeAdapter(tuple[NativeBlock, ...])


def partition_blocks(
    parsed: tuple[NativeBlock, ...],
) -> tuple[tuple[Block, ...], tuple[TextlessBlock, ...]]:
    """Retain textless native blocks separately before applying text-geometry requirements."""
    omitted = tuple(
        TextlessBlock(bbox=(a, b, c, d), text=value, number=number)
        for a, b, c, d, value, number, kind in parsed
        if kind == 0 and not value.strip()
    )
    blocks = tuple(
        Block(bbox=(a, b, c, d), text=value, number=number)
        for a, b, c, d, value, number, kind in parsed
        if kind == 0 and value.strip()
    )
    return blocks, omitted


class Rectangle(BaseModel):
    """Geometry projection at the untyped PDF binding boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, allow_inf_nan=False)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    x0: float
    y0: float
    x1: float
    y1: float


class PageGeometry(BaseModel):
    """OCR output is mapped back to the unrotated physical crop box."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    rect: Rectangle
    cropbox: Rectangle
    rotation: int


class DocumentInfo(BaseModel):
    """Actual raw PDF page-tree and encryption checks, without image rescanning."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    page_count: int = Field(ge=1, le=500)
    needs_pass: bool
    is_pdf: bool


def geometry_status(
    blocks: tuple[Block, ...], width: float, height: float, tolerance: float
) -> Literal["within-declared-bounds", "out-of-bounds", "no-text-blocks"]:
    """Check numeric page bounds; glyph alignment and reading order remain unreviewed."""
    if not blocks:
        return "no-text-blocks"
    if any(
        left < -tolerance
        or top < -tolerance
        or right > width + tolerance
        or bottom > height + tolerance
        for block in blocks
        for left, top, right, bottom in (block.bbox,)
    ):
        return "out-of-bounds"
    return "within-declared-bounds"


def recognize(
    selected: PreparedPage, engine: EngineBinding, settings: Settings, model: Path
) -> PageResult:
    """OCR one already verified PDF page; an empty result is an explicit unreviewed state."""
    started = time.perf_counter()
    text = ""
    blocks: tuple[Block, ...] = ()
    omitted: tuple[TextlessBlock, ...] = ()
    error: str | None = None
    status: Status = "ocr-empty"
    with pymupdf.open(stream=selected.pdf_bytes, filetype="pdf") as document:
        info = DocumentInfo.model_validate(document, from_attributes=True)
        if not info.is_pdf or info.needs_pass or selected.source.page_index >= info.page_count:
            raise OcrError("actual PDF page tree, format or encryption refuses the selected page")
        page = document[selected.source.page_index]
        geometry = PageGeometry.model_validate(page, from_attributes=True)
        width = math.ceil(geometry.rect.width * settings.dpi / 72)
        height = math.ceil(geometry.rect.height * settings.dpi / 72)
        if width * height > settings.maximum_pixels:
            status, error = "bound-refused", "full-page raster exceeds declared pixel bound"
        else:
            try:
                textpage = utils.get_textpage_ocr(
                    page,
                    flags=0,
                    language=settings.language,
                    dpi=settings.dpi,
                    full=True,
                    tessdata=str(model.parent),
                )
                text = STR.validate_python(getattr(textpage, "extractText")())
                parsed = BLOCKS.validate_python(getattr(textpage, "extractBLOCKS")())
                blocks, omitted = partition_blocks(parsed)
                status = "ocr-produced" if text.strip() else "ocr-empty"
            except (RuntimeError, OSError, ValueError) as caught:
                status, error = "engine-error", f"{type(caught).__name__}: {caught}"
    bounds = geometry_status(
        blocks, geometry.cropbox.width, geometry.cropbox.height, settings.geometry_tolerance_points
    )
    quality = ("ocr-unreviewed", "reading-order-unverified", "geometry-unreviewed")
    if omitted:
        quality += ("textless-ocr-blocks-omitted",)
    match bounds:
        case "out-of-bounds":
            quality += ("ocr-block-outside-page",)
        case "within-declared-bounds" | "no-text-blocks":
            pass
        case _:
            assert_never(bounds)
    return PageResult(
        cache_key=page_key(selected.source, engine),
        source=selected.source,
        engine=engine,
        status=status,
        native_characters=len(selected.native_text),
        native_extractor_version=selected.native_version,
        text=text,
        blocks=blocks,
        omitted_textless_blocks=omitted,
        omitted_textless_block_count=len(omitted),
        page_width_points=geometry.cropbox.width,
        page_height_points=geometry.cropbox.height,
        rotation=geometry.rotation,
        cropbox_unrotated=(
            geometry.cropbox.x0,
            geometry.cropbox.y0,
            geometry.cropbox.x1,
            geometry.cropbox.y1,
        ),
        geometry_tolerance_points=settings.geometry_tolerance_points,
        geometry_status=bounds,
        quality=quality,
        rendered_width_pixels=width,
        rendered_height_pixels=height,
        elapsed_seconds=time.perf_counter() - started,
        error=error,
    )
