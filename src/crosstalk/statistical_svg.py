"""Portable vector marks and finite scales for scientific descriptive figures."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Final, Literal

from crosstalk.records import Record
from crosstalk.statistical_visual_records import VisualMetadata  # noqa: TC001 -- Runtime schema.

NAVY: Final = "#13293b"
TEAL: Final = "#007574"
CORAL: Final = "#c6503b"
MUTED: Final = "#5e6b70"
PALE: Final = "#d9e6e1"
MIN_LABEL_SIZE: Final = 15
Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class LabelStyle:
    """Readable label typography in SVG user units."""

    size: int = 13
    color: str = NAVY
    anchor: Literal["start", "middle", "end"] = "start"


DEFAULT_LABEL_STYLE: Final = LabelStyle()


@dataclass(frozen=True, slots=True)
class Dot:
    """One observed point with a source-labeled accessible tooltip."""

    center: Point
    radius: float
    label: str
    color: str = TEAL


class FigurePayload(Record):
    """Scientific units accompany the complete statistical identity inside each SVG."""

    proof: VisualMetadata
    name: str
    unit: str
    caption: str
    observed_units: int | None


def number(value: float) -> str:
    """Display finite values compactly while CSV/JSON retain full precision."""
    return f"{value:.4g}"


def linear(value: float, domain: Point, target: Point) -> float:
    """Map a finite value into a positive plotting extent."""
    if domain[1] <= domain[0]:
        message = "plotting domain must have positive width"
        raise ValueError(message)
    return target[0] + (value - domain[0]) / (domain[1] - domain[0]) * (target[1] - target[0])


class SVGCanvas:
    """Mutable vector builder; ElementTree escapes all scientific labels and metadata."""

    def __init__(self, title: str, unit: str, width: int = 900) -> None:
        """Create a responsive accessible vector viewport with a stable design."""
        self.width: int = width
        self.root: ET.Element = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"0 0 {width} 430",
                "width": str(width),
                "height": "430",
                "role": "img",
                "aria-labelledby": "title desc",
                "style": f"min-width:{width}px;max-width:none;background:#fffdf8",
            },
        )
        self.title_node: ET.Element = ET.SubElement(self.root, "title", {"id": "title"})
        self.title_node.text = title
        ET.SubElement(self.root, "style").text = "text{font-family:Arial,Helvetica,sans-serif}"
        self.text((24, 34), title, LabelStyle(21))
        self.text((24, 61), unit, LabelStyle(13, MUTED))

    def text(self, position: Point, content: str, style: LabelStyle = DEFAULT_LABEL_STYLE) -> None:
        """Place one escaped scientific label."""
        ET.SubElement(
            self.root,
            "text",
            {
                "x": f"{position[0]:.3f}",
                "y": f"{position[1]:.3f}",
                "font-size": str(max(style.size, MIN_LABEL_SIZE)),
                "fill": style.color,
                "text-anchor": style.anchor,
            },
        ).text = content

    def rectangle(self, bounds: Box, fill: str) -> None:
        """Draw a nonnegative count bar or background region."""
        x, y, width, height = bounds
        if width < 0 or height < 0:
            message = "SVG rectangle dimensions must be nonnegative"
            raise ValueError(message)
        _ = ET.SubElement(
            self.root,
            "rect",
            {
                "x": f"{x:.3f}",
                "y": f"{y:.3f}",
                "width": f"{width:.3f}",
                "height": f"{height:.3f}",
                "fill": fill,
            },
        )

    def line(self, start: Point, end: Point, color: str = PALE) -> None:
        """Draw a reference axis or an explicitly eligible interval."""
        _ = ET.SubElement(
            self.root,
            "line",
            {
                "x1": f"{start[0]:.3f}",
                "y1": f"{start[1]:.3f}",
                "x2": f"{end[0]:.3f}",
                "y2": f"{end[1]:.3f}",
                "stroke": color,
                "stroke-width": "1.5",
            },
        )

    def dot(self, dot: Dot) -> None:
        """Render a point without connecting observations into a fitted trend."""
        node = ET.SubElement(
            self.root,
            "circle",
            {
                "cx": f"{dot.center[0]:.3f}",
                "cy": f"{dot.center[1]:.3f}",
                "r": str(dot.radius),
                "fill": dot.color,
                "fill-opacity": "0.7",
            },
        )
        ET.SubElement(node, "title").text = dot.label

    def interval(self, start: Point, end: Point) -> None:
        """Mark an eligible diagnostic interval explicitly in the machine-readable SVG."""
        _ = ET.SubElement(
            self.root,
            "line",
            {
                "x1": f"{start[0]:.3f}",
                "y1": f"{start[1]:.3f}",
                "x2": f"{end[0]:.3f}",
                "y2": f"{end[1]:.3f}",
                "stroke": NAVY,
                "stroke-width": "3",
                "data-role": "diagnostic-interval",
            },
        )

    def horizontal_axis(self, domain: Point, frame: Box) -> None:
        """Draw five labeled reference positions on a positive finite scale."""
        x, y, width, _ = frame
        self.line((x, y), (x + width, y))
        for index in range(5):
            value = domain[0] + (domain[1] - domain[0]) * index / 4
            left = x + width * index / 4
            self.line((left, y), (left, y + 5))
            self.text((left, y + 23), number(value), LabelStyle(12, MUTED, "middle"))

    def count_axis(self, maximum: float, frame: Box) -> None:
        """Count ticks never imply a sampling interval for a captured population."""
        x, y, _, height = frame
        self.line((x, y), (x, y + height))
        for index in range(3):
            value = maximum * index / 2
            top = y + height - height * index / 2
            self.text((x - 8, top + 4), number(value), LabelStyle(11, MUTED, "end"))

    def finish(self, payload: FigurePayload) -> str:
        """Attach exact receipts and a complete text alternative to the portable chart."""
        self.root.set("data-statistics-sha256", payload.proof.statistics_sha256)
        self.title_node.set("id", payload.name + "-title")
        self.root.set("aria-labelledby", payload.name + "-title " + payload.name + "-desc")
        ET.SubElement(self.root, "desc", {"id": payload.name + "-desc"}).text = payload.caption
        ET.SubElement(self.root, "metadata").text = payload.model_dump_json()
        return ET.tostring(self.root, encoding="unicode")


@dataclass(frozen=True, slots=True)
class FigureDraft:
    """A completed drawing and its scientific interpretation boundary."""

    name: str
    title: str
    unit: str
    observed_units: int | None
    caption: str
    canvas: SVGCanvas

    def svg(self, proof: VisualMetadata) -> str:
        """Serialize the vector chart under its source-bound metadata."""
        return self.canvas.finish(
            FigurePayload(
                proof=proof,
                name=self.name,
                unit=self.unit,
                caption=self.caption,
                observed_units=self.observed_units,
            )
        )
