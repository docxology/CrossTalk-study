"""Parse partially annotated PyMuPDF results at one dependency boundary.

Dynamic method access is confined here because upstream returns untyped
containers. Every result crosses a Pydantic parser before domain code uses it.
"""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003 -- Pydantic validates this field at runtime.
from typing import TYPE_CHECKING, ClassVar, Final

import pymupdf
from pydantic import ConfigDict, Field, TypeAdapter

from crosstalk.records import ImageInfo, Record

if TYPE_CHECKING:
    from crosstalk.records import BBox

Block = tuple[float, float, float, float, str, int, int]
BLOCKS: Final = TypeAdapter(tuple[Block, ...])
IMAGE_INFOS: Final = TypeAdapter(tuple[ImageInfo, ...])
PNG_BYTES: Final = TypeAdapter(bytes)


class DocumentInfo(Record):
    """Parsed document metadata; missing or malformed properties fail closed."""

    page_count: int
    needs_pass: bool
    is_pdf: bool


class Rectangle(Record):
    """Positive page dimensions in PDF points."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class PageGeometry(Record):
    """Geometry parsed from a live page without trusting upstream Any fields."""

    rect: Rectangle


class ImagePayload(Record):
    """Exact bytes and format parsed from the PDF image adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    image: bytes
    ext: str = Field(pattern=r"^[a-zA-Z0-9]{1,8}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RenderedPixmap(Record):
    """Parse the live renderer's callable; its returned bytes are parsed again."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    tobytes: Callable[[str], bytes]


def document_info(document: pymupdf.Document) -> DocumentInfo:
    """Parse live document properties into a fully typed record."""
    return DocumentInfo.model_validate(document, from_attributes=True)


def page_geometry(page: pymupdf.Page) -> Rectangle:
    """Parse live page dimensions before arithmetic or rendering."""
    return PageGeometry.model_validate(page, from_attributes=True).rect


def image_infos(page: pymupdf.Page) -> tuple[ImageInfo, ...]:
    """Parse every image occurrence returned by the dependency."""
    return IMAGE_INFOS.validate_python(getattr(page, "get_image_info")(xrefs=True))


def image_payload(document: pymupdf.Document, xref: int) -> ImagePayload:
    """Parse image bytes before hashing or file publication."""
    return ImagePayload.model_validate(getattr(document, "extract_image")(xref))


def text_blocks(page: pymupdf.Page) -> tuple[Block, ...]:
    """Parse exact tuple shapes before extracting text or coordinates."""
    return BLOCKS.validate_python(getattr(page, "get_text")("blocks", sort=True))


def block_bbox(block: Block) -> BBox:
    """Project the four coordinate fields without an untyped tuple slice."""
    return block[0], block[1], block[2], block[3]


def preview_png(page: pymupdf.Page, scale: float) -> bytes:
    """Parse a rendered PNG before decoding it with Pillow."""
    pixmap = RenderedPixmap.model_validate(
        getattr(page, "get_pixmap")(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    )
    return PNG_BYTES.validate_python(pixmap.tobytes("png"))
