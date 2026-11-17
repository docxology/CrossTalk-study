"""Admitted discrete SVG derivatives retain data geometry/fonts and bind actual native pixel QA."""

from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.study_language_records import StudyError, StudyFigure
from crosstalk.study_presentation_admit import admit
from crosstalk.study_presentation_ink import SourceCanvas, add_red_legend, clear_legend
from crosstalk.study_presentation_legend import amend_legends
from crosstalk.study_presentation_native import native_identity, render_vector
from crosstalk.study_presentation_records import PresentationReceipt
from crosstalk.study_presentation_xml import SVG, parse, semantics, serialize, styles

if TYPE_CHECKING:
    from crosstalk.study_presentation_records import SvgPresentation

METHOD_FILES: Final = (
    "study_presentation.py",
    "study_presentation_records.py",
    "study_presentation_xml.py",
    "study_presentation_paint.py",
    "study_presentation_admit.py",
    "study_presentation_legend.py",
    "study_presentation_native.py",
    "study_presentation_ink.py",
    "study_language_records.py",
    "models.py",
    "extraction_runtime.py",
)


@dataclass(frozen=True, slots=True)
class PresentedFigure:
    """Pair the exact SVG with external receipts to avoid self-referential hashes."""

    figure: StudyFigure
    receipt: PresentationReceipt
    source_png: bytes
    presented_png: bytes


def implementation_digest() -> str:
    """Bind presentation helpers independently of measurement methods."""
    directory = Path(__file__).parent
    members: list[tuple[str, int, str]] = []
    for name in METHOD_FILES:
        raw = (directory / name).read_bytes()
        members.append((name, len(raw), hashlib.sha256(raw).hexdigest()))
    return hashlib.sha256(
        json.dumps((members, sys.version), separators=(",", ":")).encode()
    ).hexdigest()


def restyle_svg(raw: bytes, request: SvgPresentation) -> PresentedFigure:
    """Refuse unsupported encodings and retain actual native render evidence."""
    if (
        len(raw) > request.maximum_source_bytes
        or hashlib.sha256(raw).hexdigest() != request.source_svg_sha256
    ):
        raise StudyError("presentation source differs from its independent digest/byte bound")
    method, runtime = implementation_digest(), native_identity()
    root = parse(raw, request.maximum_elements)
    before = semantics(root)
    admitted = admit(root, request)
    source_render = render_vector(raw, request)
    clearance = clear_legend(SourceCanvas(root, source_render, admitted.canvas_rgb), request)
    amend_legends(root, request, admitted.mapping)
    approved = semantics(root)
    for paint in admitted.paints:
        style = styles(paint.element.get("style", ""))
        paint.element.set(paint.key, paint.target)
        _ = style.pop(paint.key, None)
        if style:
            paint.element.set(
                "style", ";".join(key + ":" + value for key, value in sorted(style.items()))
            )
        elif "style" in paint.element.attrib:
            del paint.element.attrib["style"]
    after = semantics(root)
    if approved != after:
        raise StudyError("presentation changed data text, fonts or nonpaint attributes")
    add_red_legend(root, request)
    metadata = ET.Element("{" + SVG + "}metadata")
    metadata.text = json.dumps(
        {
            "presentation_request": request.model_dump(),
            "method_sha256": method,
            "native_runtime_identity": runtime,
            "source_svg_sha256": request.source_svg_sha256,
            "source_measurement_identity": request.source_measurement_identity,
            "approved_attribute_text_sha256": approved,
            "data_geometry_fonts_preserved": True,
            "measurement_recomputed": False,
            "measurement_admission": (
                "caller-required; presentation does not estab" + "lish current scientific custody"
            ),
            "render_receipt": (
                "separate exact-final-SVG record; actual144dp"
                + "i RGB checks do not establish semantic accur"
                + "acy"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    root.insert(0, metadata)
    rendered_svg = serialize(root)
    final_render = render_vector(rendered_svg.encode(), request)
    receipt = PresentationReceipt(
        implementation_sha256=method,
        source_svg_sha256=request.source_svg_sha256,
        source_measurement_identity=request.source_measurement_identity,
        original_attribute_text_sha256=before,
        approved_attribute_text_sha256=approved,
        presented_attribute_text_sha256=after,
        channel_mapping=admitted.mapping,
        red_channel=request.red_focus.channel if request.red_focus is not None else None,
        annotation_edits=request.annotation_edits,
        source_render=source_render.observation,
        presented_render=final_render.observation,
        source_legend_pixels_different_from_canvas=clearance,
        native_runtime_identity=runtime,
    )
    if implementation_digest() != method or native_identity() != runtime:
        raise StudyError(
            "presentation source/native distribution chan" + "ged during the actual render pass"
        )
    caption = request.caption.complete
    if request.red_focus is not None:
        caption += " Red identifies the declared " + request.red_focus.channel + " channel."
    return PresentedFigure(
        StudyFigure(name=request.name, svg=rendered_svg, caption=caption),
        receipt,
        source_render.png,
        final_render.png,
    )
