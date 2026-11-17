"""Bounded original SVG figure plates retained as vectors in the dossier PDF."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Final

import pymupdf
from pydantic import TypeAdapter

from crosstalk.dossier_layout import MUTED, Label, PageCanvas, TextStyle
from crosstalk.models import AcquisitionError, file_digest
from crosstalk.statistical_source import read_artifact

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.dossier_records import DossierInput

PDF_BYTES: Final = TypeAdapter(bytes)
XREF: Final = TypeAdapter(int)
SVG_NAMESPACE: Final = "{http://www.w3.org/2000/svg}"
ALLOWED_TAGS: Final = frozenset(
    {"svg", "title", "desc", "metadata", "style", "text", "rect", "line", "circle", "g"}
)


class _StaticSVGBuilder(ET.TreeBuilder):
    """Reject every DTD before document text can expand declared entities."""

    def doctype(self, _name: str, _pubid: str | None, _system: str | None) -> None:
        """External and internal DTDs have no role in generated statistical SVGs."""
        raise AcquisitionError("statistical SVG document types/entities are prohibited")


def parse_static_svg(raw: bytes) -> ET.Element:
    """Parse bounded vector XML with a target that rejects all document types."""
    if len(raw) > 5_000_000:
        raise AcquisitionError("statistical SVG exceeds the 5 MB figure bound")
    try:
        return ET.fromstring(  # noqa: S314 -- Custom target refuses DTDs before entity expansion.
            raw,
            parser=ET.XMLParser(  # noqa: S314 -- Target rejects all DTDs before entity expansion.
                target=_StaticSVGBuilder()
            ),
        )
    except ET.ParseError as error:
        raise AcquisitionError("statistical figure is not a valid SVG") from error


def _vector_pdf(raw: bytes) -> bytes:
    """Admit the project's own static SVG vocabulary, excluding external resources."""
    root = parse_static_svg(raw)
    if root.tag != SVG_NAMESPACE + "svg":
        raise AcquisitionError("statistical figure must be an SVG document")
    for node in root.iter():
        if node.tag.removeprefix(SVG_NAMESPACE) not in ALLOWED_TAGS:
            raise AcquisitionError("statistical SVG contains an unsupported or active element")
        for name, value in node.attrib.items():
            if (
                name.rsplit("}", 1)[-1].casefold() in {"href", "src"}
                or name.casefold().startswith("on")
                or "url(" in value.casefold()
            ):
                raise AcquisitionError("statistical SVG contains external or active attributes")
        if node.tag == SVG_NAMESPACE + "style" and any(
            token in (node.text or "").casefold() for token in ("url(", "@import")
        ):
            raise AcquisitionError("statistical SVG contains an external style resource")
    with pymupdf.open(stream=raw, filetype="svg") as source:
        return PDF_BYTES.validate_python(
            getattr(source, "convert_to_pdf")()  # noqa: B009 -- PDF dependency boundary.
        )


def figure_plates(
    document: pymupdf.Document, root: Path, content: DossierInput
) -> tuple[PageCanvas, ...]:
    """Insert figure plates after the four graphical abstracts without rasterization."""
    bindings = {binding.path: binding.sha256 for binding in content.source_bindings}
    canvases: list[PageCanvas] = []
    for index, figure in enumerate(content.figures, start=5):
        if bindings.get(figure.path) != figure.sha256:
            raise AcquisitionError("dossier statistical figure lacks a matching source binding")
        path = root / figure.path
        if file_digest(path) != figure.sha256:
            raise AcquisitionError("dossier statistical SVG digest changed")
        converted = _vector_pdf(read_artifact(path))
        canvas = PageCanvas(document.new_page(width=595, height=842), index)
        canvas.heading(
            figure.title,
            "Current-source statistical observations and diagnostic limits.",
            eyebrow="STATISTICAL FIGURE",
        )
        with pymupdf.open(stream=converted, filetype="pdf") as vector:
            _ = XREF.validate_python(
                getattr(canvas.page, "show_pdf_page")(  # noqa: B009 -- PDF dependency boundary.
                    pymupdf.Rect(28, 176, 567, 568), vector, 0, keep_proportion=True
                )
            )
        canvas.text(Label((42, 601, 553, 746), figure.caption, TextStyle(10.2)))
        canvas.text(
            Label((42, 754, 553, 784), "SVG SHA-256 " + figure.sha256, TextStyle(7.5, color=MUTED))
        )
        canvases.append(canvas)
    return tuple(canvases)
