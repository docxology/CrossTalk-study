"""Bound native base-image decoding to the exact PDF, placement and encoded asset."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

import pymupdf
from pydantic import ConfigDict, Field, TypeAdapter

from crosstalk.extraction_method import current_extraction_producer, page_method_current
from crosstalk.image_inventory import scan_image_references
from crosstalk.models import AcquisitionError
from crosstalk.pdf_adapter import RenderedPixmap, document_info, image_payload
from crosstalk.records import Record

if TYPE_CHECKING:
    from crosstalk.records import ImageOccurrence, PageRecord

MAX_VISUAL_SOURCE_BYTES: Final = 100_000_000
MAX_IMAGE_PIXELS: Final = 100_000_000
TEXT: Final = TypeAdapter(str)


class NativeGeometry(Record):
    """Parse native raster properties before color conversion or output encoding."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    n: int = Field(ge=1, le=5)
    alpha: int = Field(ge=0, le=1)


@dataclass(frozen=True, slots=True)
class NativeRaster:
    """An in-memory PNG with independently checked PDF-context provenance."""

    png: bytes
    version: str
    source_pdf: str
    source_sha256: str
    source_page_index: int
    source_xref: int


def read_visual_bytes(root: Path, relative: str) -> bytes:
    """Read at most 100 MB from a regular contained source without following aliases."""
    parsed = Path(relative)
    if root.is_symlink() or parsed.is_absolute() or not parsed.parts or ".." in parsed.parts:
        raise AcquisitionError("visual source must remain inside a physical project directory")
    path = root
    for part in parsed.parts:
        path /= part
        if path.is_symlink():
            raise AcquisitionError(f"visual source contains a symlink: {relative}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_VISUAL_SOURCE_BYTES:
            raise AcquisitionError("visual source is nonregular or exceeds the 100 MB bound")
        raw = stream.read(MAX_VISUAL_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > MAX_VISUAL_SOURCE_BYTES or (
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_size, after.st_mtime_ns):
        raise AcquisitionError("visual source changed during its bounded read")
    return raw


def native_pixels(
    root: Path, page: PageRecord, image: ImageOccurrence, encoded: bytes
) -> NativeRaster:
    """Decode an uncomposited base image only after PDF/page/xref/byte agreement."""
    if (
        image.xref < 1
        or min(image.width, image.height) < 1
        or image.width * image.height > MAX_IMAGE_PIXELS
        or image not in page.images
        or image.sha256 != hashlib.sha256(encoded).hexdigest()
        or page.source_pdf != f"data/raw/pdf/{page.issue_id}.pdf"
    ):
        raise AcquisitionError("native raster identity or 100M-pixel bound disagrees")
    reference = image.reference
    producer = current_extraction_producer()
    if (
        not page_method_current(page, producer)
        or reference is None
        or reference.resolved_xref is None
    ):
        raise AcquisitionError(
            "native decoding requires current version3 resolved reference custody"
        )
    if (image.xref, image.bbox, image.width, image.height) != (
        reference.resolved_xref,
        reference.bbox,
        reference.width,
        reference.height,
    ):
        raise AcquisitionError(
            "native image placement or dimensions differ from reference evidence"
        )
    raw = read_visual_bytes(root, page.source_pdf)
    if hashlib.sha256(raw).hexdigest() != page.source_sha256:
        raise AcquisitionError("native PDF bytes differ from the sealed page source")
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        info = document_info(document)
        if not info.is_pdf or info.needs_pass or not 0 <= page.page_index < info.page_count <= 500:
            raise AcquisitionError("native PDF is unavailable or outside the page bound")
        scan = scan_image_references(document[page.page_index], producer)
        if scan.inventory != page.image_inventory or reference not in scan.references:
            raise AcquisitionError("native image placement or dimensions disagree with the PDF")
        png = _raster_png(document, image, encoded)
    if producer != current_extraction_producer():
        raise AcquisitionError("native library or implementation changed during raster decoding")
    return NativeRaster(
        png=png,
        version=TEXT.validate_python(getattr(pymupdf, "VersionBind")),  # noqa: B009
        source_pdf=page.source_pdf,
        source_sha256=page.source_sha256,
        source_page_index=page.page_index,
        source_xref=image.xref,
    )


def _raster_png(document: pymupdf.Document, image: ImageOccurrence, encoded: bytes) -> bytes:
    """Decode only matching encoded base bytes; separate PDF masks remain uncomposited."""
    if image_payload(document, image.xref).image != encoded:
        raise AcquisitionError("native xref bytes differ from the saved encoded asset")
    pixmap = pymupdf.Pixmap(document, image.xref)
    geometry = NativeGeometry.model_validate(pixmap)
    if (geometry.width, geometry.height) != (image.width, image.height):
        raise AcquisitionError("native raster dimensions disagree with the sealed occurrence")
    if geometry.n - geometry.alpha != 3:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    # Preserve intrinsic alpha; no separate mask is loaded or composited.
    return RenderedPixmap.model_validate(pixmap).tobytes("png")
