"""Render original PDF appearance without depending on embedded-image xref resolution."""

from __future__ import annotations

import hashlib
import math
import platform
import struct
from dataclasses import dataclass
from typing import ClassVar, Literal

import pymupdf
from PIL import Image
from PIL import __version__ as pillow_version
from pydantic import BaseModel, ConfigDict, Field
from pymupdf.mupdf import FzErrorBase

from .appearance_audit import audit_page
from .appearance_pixels import measure_pixels
from .appearance_records import (
    AntiAliasState,
    AppearanceError,
    AppearanceSettings,
    BBox,
    PageAppearance,
    RenderedAppearance,
)


class NativeBox(BaseModel):
    """Parse native page rectangles once at the dependency boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, from_attributes=True, allow_inf_nan=False
    )
    x0: float
    y0: float
    x1: float
    y1: float

    def coordinates(self) -> BBox:
        """Preserve native point coordinates without clipping or changing the source page."""
        return self.x0, self.y0, self.x1, self.y1


class NativeFrame(BaseModel):
    """Page.rect is the rotated visible frame; original CropBox and MediaBox stay distinct."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    rect: NativeBox
    cropbox: NativeBox
    mediabox: NativeBox
    rotation: Literal[0, 90, 180, 270]


class NativePixmap(BaseModel):
    """Verify exact RGB sample shape before Pillow interprets the native buffer."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    n: int
    alpha: int
    samples: bytes


class NativeDocument(BaseModel):
    """Parse native source facts once without relying on incomplete upstream property stubs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    is_pdf: bool
    needs_pass: bool
    page_count: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class OpenedPdf:
    """Borrow the opened document with its exact selected bytes and parsed source facts."""

    document: pymupdf.Document
    raw: bytes
    facts: NativeDocument


def _pixel_bound(frame: NativeFrame, settings: AppearanceSettings) -> None:
    """Refuse allocation before calling the native renderer, with explicit rounding reserve."""
    rectangle = frame.rect
    if rectangle.x1 <= rectangle.x0 or rectangle.y1 <= rectangle.y0:
        raise AppearanceError("appearance page has an empty or reversed visible frame")
    scale = settings.dpi / 72
    width = math.ceil(rectangle.x1 * scale) - math.floor(rectangle.x0 * scale) + 2
    height = math.ceil(rectangle.y1 * scale) - math.floor(rectangle.y0 * scale) + 2
    if width * height > settings.max_pixels:
        raise AppearanceError("appearance prospective render exceeds its pixel allocation bound")


def _render_page(
    source: OpenedPdf,
    page_index: int,
    settings: AppearanceSettings,
) -> RenderedAppearance:
    """Measure the exact native RGB-on-white visible page and leave the PDF untouched."""
    page = source.document[page_index]
    frame = NativeFrame.model_validate(page)
    _pixel_bound(frame, settings)
    resource_audit = audit_page(source.document, page, settings)
    before = AntiAliasState.model_validate(pymupdf.TOOLS.show_aa_level())
    native = NativePixmap.model_validate(
        getattr(page, "get_pixmap")(  # noqa: B009 -- Parse the incompletely typed native return.
            dpi=settings.dpi,
            colorspace=pymupdf.csRGB,
            alpha=False,
            annots=settings.include_annotations,
        )
    )
    if (
        native.n != 3
        or native.alpha != 0
        or native.width * native.height > settings.max_pixels
        or len(native.samples) != native.width * native.height * 3
    ):
        raise AppearanceError("appearance native RGB sample shape or allocation is inconsistent")
    with Image.frombytes("RGB", (native.width, native.height), native.samples) as image:
        measured = measure_pixels(image, settings)
    pixel_digest = hashlib.sha256(b"crosstalk-page-rgb-v1\0")
    pixel_digest.update(struct.pack(">II", native.width, native.height))
    pixel_digest.update(native.samples)
    if before != AntiAliasState.model_validate(pymupdf.TOOLS.show_aa_level()):
        raise AppearanceError("native antialias state changed during appearance measurement")
    return RenderedAppearance(
        PageAppearance(
            source_pdf_sha256=hashlib.sha256(source.raw).hexdigest(),
            page_index=page_index,
            total_pdf_pages=source.facts.page_count,
            page_rect=frame.rect.coordinates(),
            cropbox=frame.cropbox.coordinates(),
            mediabox=frame.mediabox.coordinates(),
            rotation=frame.rotation,
            renderer_version=pymupdf.VersionBind,
            pillow_version=pillow_version,
            python_version=platform.python_version(),
            antialias=before,
            settings=settings,
            resource_audit=resource_audit,
            pixels=measured.summary,
            render_pixel_sha256=pixel_digest.hexdigest(),
            thumbnail_sha256=measured.png_sha256,
            thumbnail_width=measured.thumbnail_width,
            thumbnail_height=measured.thumbnail_height,
        ),
        measured.png,
    )


def render_pdf_bytes(
    raw: bytes, page_index: int, settings: AppearanceSettings
) -> RenderedAppearance:
    """A bounded measurement kernel; manager selections and seals belong to its outer workflow."""
    if not raw or len(raw) > settings.max_pdf_bytes:
        raise AppearanceError("appearance PDF bytes are empty or exceed their selected byte bound")
    if page_index < 0:
        raise AppearanceError("appearance physical page index must be nonnegative")
    try:
        with pymupdf.open(stream=raw, filetype="pdf") as document:
            facts = NativeDocument.model_validate(document)
            if not facts.is_pdf or facts.needs_pass or facts.page_count < 1:
                raise AppearanceError("appearance PDF is empty, unavailable or encrypted")
            if page_index >= facts.page_count:
                raise AppearanceError("appearance physical page is outside the original PDF")
            return _render_page(OpenedPdf(document, raw, facts), page_index, settings)
    except (FzErrorBase, RuntimeError) as error:
        raise AppearanceError("native PDF appearance rendering failed: " + str(error)) from error
