"""Check reserved legend space using sampled pixels, not text estimates."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pymupdf
from pydantic import TypeAdapter

from crosstalk.study_language_records import StudyError
from crosstalk.study_presentation_xml import SVG

if TYPE_CHECKING:
    from crosstalk.study_presentation_native import RenderedVector
    from crosstalk.study_presentation_records import SvgPresentation


@dataclass(frozen=True, slots=True)
class SourceCanvas:
    """Bind the parsed source, sampled render and admitted canvas color."""

    root: ET.Element
    rendered: RenderedVector
    rgb: str


def clear_legend(source: SourceCanvas, request: SvgPresentation) -> int | None:
    """Count sampled source pixels differing by>2RGBlevels from the actual declared canvas color."""
    area = request.legend_area
    if area is None:
        return None
    x, y, width, height = (float(part) for part in source.root.attrib["viewBox"].split())
    if not (
        x <= area.x
        and y <= area.y
        and area.x + area.width <= x + width
        and area.y + area.height <= y + height
    ):
        raise StudyError("reserved legend lies outside the source viewBox")
    pixels = source.rendered.observation
    if abs(pixels.width_pixels * height - pixels.height_pixels * width) > max(width, height):
        raise StudyError(
            "native viewport and viewBox aspect ratios di" + "ffer; reserved mapping is unsupported"
        )
    left = math.floor((area.x - x) / width * pixels.width_pixels) - 2
    top = math.floor((area.y - y) / height * pixels.height_pixels) - 2
    right = math.ceil((area.x + area.width - x) / width * pixels.width_pixels) + 2
    bottom = math.ceil((area.y + area.height - y) / height * pixels.height_pixels) + 2
    if not (0 <= left < right <= pixels.width_pixels and 0 <= top < bottom <= pixels.height_pixels):
        raise StudyError("reserved legend lacks its two-pixel source-render clearance")
    background = tuple(int(source.rgb[index : index + 2], 16) for index in (1, 3, 5))
    differences = 0
    for row in range(top, bottom):
        for column in range(left, right):
            start = (row * pixels.width_pixels + column) * 3
            if any(
                abs(source.rendered.samples[start + index] - value) > 2
                for index, value in enumerate(background)
            ):
                differences += 1
    if differences:
        raise StudyError("reserved legend would overwrite actual sampled source pixels")
    return differences


def add_red_legend(root: ET.Element, request: SvgPresentation) -> None:
    """A visible explicit red role occupies only an actually sampled clear, caller-reserved area."""
    focus, area = request.red_focus, request.legend_area
    if focus is None or area is None:
        return
    width = float(root.attrib["viewBox"].split()[2])
    size = max(18.0, request.minimum_print_font_points * width / request.target_print_width_points)
    label = "Red: " + focus.channel
    measured = TypeAdapter(float).validate_python(
        pymupdf.get_text_length(label, fontname="helv", fontsize=size)
    )
    if measured + 24 > area.width or size * 1.7 > area.height:
        raise StudyError(
            "reserved legend cannot fit its named red rol" + "e at the declared print font size"
        )
    node = ET.SubElement(
        root,
        "{" + SVG + "}text",
        {
            "x": str(area.x + 12),
            "y": str(area.y + size * 1.25),
            "font-family": "Helvetica",
            "font-size": str(size),
            "fill": "#b00020",
        },
    )
    node.text = label
