"""Typed readonly MuPDF object metadata; no stream bytes, hashes or pixmaps are requested."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import Field, InstanceOf, TypeAdapter
from pymupdf.mupdf import FzDocument, PdfDocument, PdfObj

if TYPE_CHECKING:
    import pymupdf

type PdfKind = Literal["null", "dictionary", "array", "name", "integer", "other"]
NODE: Final = TypeAdapter(InstanceOf[PdfObj])
FZ: Final = TypeAdapter(InstanceOf[FzDocument])
PDF: Final = TypeAdapter(InstanceOf[PdfDocument])
INTEGER: Final = TypeAdapter(Annotated[int, Field(strict=True)])
TEXT: Final = TypeAdapter(str)
FLAG: Final = TypeAdapter(bool)


class NativeMetadataError(ValueError):
    """Unsupported native metadata is unavailable evidence rather than a guessed value."""

    def __init__(self, reason: str) -> None:
        """Retain one explicit unsupported native-metadata observation."""
        self.reason: str = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PdfEntry:
    """A native dictionary name and readonly value retain their actual parent context."""

    name: str
    node: PdfNode


@dataclass(frozen=True, slots=True)
class PdfNode:
    """Foreign object lifetime stays inside the source document's context manager."""

    value: PdfObj

    def _flag(self, method: str) -> bool:
        return FLAG.validate_python(getattr(self.value, method)())

    def kind(self) -> PdfKind:
        """Classify only the metadata primitives needed by the declared image audit."""
        for method, kind in (
            ("pdf_is_null", "null"),
            ("pdf_is_dict", "dictionary"),
            ("pdf_is_array", "array"),
            ("pdf_is_name", "name"),
            ("pdf_is_int", "integer"),
        ):
            if self._flag(method):
                return TypeAdapter(PdfKind).validate_python(kind)
        return "other"

    def xref(self) -> int | None:
        """This is a metadata-object identity, never an occurrence-to-image resolution."""
        if self._flag("pdf_is_indirect"):
            return INTEGER.validate_python(getattr(self.value, "pdf_to_num")())  # noqa: B009
        return None

    def get(self, name: str) -> PdfNode:
        """Let the native PDF parser read escaped/inline dictionaries without text regexes."""
        return PdfNode(NODE.validate_python(getattr(self.value, "pdf_dict_gets")(name)))  # noqa: B009

    def name(self) -> str:
        """Read only a confirmed name, preserving native parser interpretation."""
        if not self._flag("pdf_is_name"):
            raise NativeMetadataError("PDF metadata value is not a name")
        return TEXT.validate_python(getattr(self.value, "pdf_to_name")())  # noqa: B009

    def integer(self) -> int:
        """A real/fractional declaration cannot be silently truncated into an image dimension."""
        if not self._flag("pdf_is_int"):
            raise NativeMetadataError("PDF metadata value is not an integer")
        return INTEGER.validate_python(getattr(self.value, "pdf_to_int64")())  # noqa: B009

    def entries(self, maximum: int) -> tuple[PdfEntry, ...]:
        """Bound native dictionary traversal before constructing a Python result tuple."""
        count = INTEGER.validate_python(getattr(self.value, "pdf_dict_len")())  # noqa: B009
        if self.kind() != "dictionary" or not 0 <= count <= maximum:
            raise NativeMetadataError("PDF dictionary exceeds its metadata traversal bound")
        return tuple(
            PdfEntry(
                PdfNode(
                    NODE.validate_python(getattr(self.value, "pdf_dict_get_key")(index))  # noqa: B009 -- Parse native return.
                ).name(),
                PdfNode(NODE.validate_python(getattr(self.value, "pdf_dict_get_val")(index))),  # noqa: B009
            )
            for index in range(count)
        )

    def array(self, maximum: int) -> tuple[PdfNode, ...]:
        """Bound arrays used for annotation and color-key metadata; never read a stream."""
        count = INTEGER.validate_python(getattr(self.value, "pdf_array_len")())  # noqa: B009
        if self.kind() != "array" or not 0 <= count <= maximum:
            raise NativeMetadataError("PDF array exceeds its metadata traversal bound")
        return tuple(
            PdfNode(NODE.validate_python(getattr(self.value, "pdf_array_get")(index)))  # noqa: B009
            for index in range(count)
        )


def page_object(document: pymupdf.Document, page: pymupdf.Page) -> PdfNode:
    """Obtain actual PDF metadata objects from the opened original document."""
    fz = FZ.validate_python(getattr(document, "this"))  # noqa: B009
    pdf = PDF.validate_python(getattr(fz, "pdf_document_from_fz_document")())  # noqa: B009
    xref = INTEGER.validate_python(getattr(page, "xref"))  # noqa: B009
    return PdfNode(NODE.validate_python(getattr(pdf, "pdf_load_object")(xref)))  # noqa: B009
