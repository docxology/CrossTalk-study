"""Conservative source-role admission refuses encodings that cannot survive discrete recoloring."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

from crosstalk.study_language_records import StudyError
from crosstalk.study_presentation_paint import contrast, luminance, opaque
from crosstalk.study_presentation_xml import background, local, painted_nodes, styles

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET
    from collections.abc import Mapping

    from crosstalk.study_presentation_records import SvgPresentation
    from crosstalk.study_presentation_xml import PaintedNode


@dataclass(frozen=True, slots=True)
class RolePaint:
    """One resolved leaf attribute and its independently declared discrete destination."""

    element: ET.Element
    key: str
    target: str


@dataclass(frozen=True, slots=True)
class AdmittedPlot:
    """Only declared data colors and separately admitted static annotation/axis roles remain."""

    paints: tuple[RolePaint, ...]
    mapping: tuple[tuple[str, str, str], ...]
    canvas_rgb: str


@dataclass(frozen=True, slots=True)
class PaintRoles:
    """An admitted canvas and declared data/decorative roles share one source scale."""

    backdrop: ET.Element
    targets: Mapping[str, str]
    decorations: frozenset[str | None]
    print_scale: float


@dataclass(frozen=True, slots=True)
class ResolvedPaint:
    """Only a data mark updates its form inventory; static annotation is a separate role."""

    paint: RolePaint
    canvas_rgb: str | None = None
    data_form: tuple[str, str] | None = None


def _explicit_states(root: ET.Element) -> None:
    """Opacity, hidden marks and indirect clipping contexts require a scientific-data redraw."""
    for node in root.iter():
        declared = dict(node.attrib)
        declared.update(styles(node.get("style", "")))
        for key in ("opacity", "fill-opacity", "stroke-opacity", "stop-opacity"):
            if key in declared:
                try:
                    opacity = float(declared[key])
                except ValueError as error:
                    raise StudyError("invalid source opacity") from error
                if opacity != 1.0:
                    raise StudyError("translucent marks cannot use this discrete derivative")
        if any(
            key in declared
            for key in ("display", "visibility", "clip-path", "mask", "filter", "transform")
        ):
            raise StudyError(
                "hidden/clipped/filter contexts require an ex" + "plicit bound-data redraw"
            )
        if local(node.tag) in {"defs", "clipPath", "stop"}:
            raise StudyError("paint servers and clipping definitions need a bound-data redraw")


def _mapping(request: SvgPresentation) -> tuple[tuple[str, str, str], ...]:
    """A maximum of three caller-declared discrete roles uses black, gray and optional named red."""
    rows: list[tuple[str, str, str]] = []
    for channel in request.channels:
        source = opaque(channel.source_paint)
        if source is None or source == "#ffffff":
            raise StudyError("a data channel cannot be transparent or white")
        target = "#000000" if channel.tone == "black" else "#777777"
        if request.red_focus is not None and channel.channel == request.red_focus.channel:
            if opaque(request.red_focus.source_paint) != source:
                raise StudyError("red source color disagrees with its declared data role")
            target = "#b00020"
        rows.append((channel.channel, source, target))
    if len({source for _, source, _ in rows}) != len(rows) or len(
        {target for _, _, target in rows}
    ) != len(rows):
        raise StudyError(
            "declared data channels collapse; use labels/" + "shapes in a bound-data redraw"
        )
    return tuple(rows)


def _form(node: ET.Element, key: str, print_scale: float) -> str:
    """Require distinct sufficiently large circles/boxes for low-contrast roles."""
    tag = local(node.tag)
    if key != "fill":
        return "unsupported"
    try:
        if tag == "circle" and float(node.get("r", "0")) * print_scale >= 3:
            return "filled-circle"
        if (
            tag == "rect"
            and min(float(node.get(name, "0")) for name in ("width", "height")) * print_scale >= 6
        ):
            return "filled-box"
    except ValueError as error:
        raise StudyError("data mark dimensions are not explicit finite source units") from error
    return "unsupported"


def _resolve(roles: PaintRoles, row: PaintedNode, attribute: tuple[str, str]) -> ResolvedPaint:
    """Resolve one opaque computed attribute without changing its source text or geometry."""
    key, rgb = attribute
    if row.element is roles.backdrop and key == "fill":
        if luminance(rgb) < 0.9:
            raise StudyError("dark/background plots need a bound-data redraw")
        return ResolvedPaint(RolePaint(row.element, key, "#ffffff"), canvas_rgb=rgb)
    if local(row.element.tag) in {"text", "tspan"}:
        if luminance(rgb) > 0.25:
            raise StudyError("light annotations can disappear on white; redraw required")
        return ResolvedPaint(RolePaint(row.element, key, "#000000"))
    if rgb in roles.targets:
        return ResolvedPaint(
            RolePaint(row.element, key, roles.targets[rgb]),
            data_form=(rgb, _form(row.element, key, roles.print_scale)),
        )
    if key == "stroke" and rgb in roles.decorations:
        return ResolvedPaint(
            RolePaint(row.element, key, "#dddddd" if luminance(rgb) > 0.4 else "#000000")
        )
    if (
        key == "fill"
        and rgb == "#ffffff"
        and any(name == "stroke" and opaque(value) in roles.targets for name, value in row.values)
    ):
        return ResolvedPaint(RolePaint(row.element, key, "#ffffff"))
    raise StudyError("unassigned paint role requires a bound-data redraw")


def _distinctions(
    mapping: tuple[tuple[str, str, str], ...], shapes: Mapping[str, set[str]]
) -> None:
    """Low-contrast categorical pairs need existing distinct sufficiently large mark forms."""
    for (_, left, left_target), (_, right, right_target) in combinations(mapping, 2):
        if contrast(left_target, right_target) < 3 and (
            "unsupported" in shapes[left] | shapes[right] or shapes[left] & shapes[right]
        ):
            raise StudyError(
                "low-contrast data channels share mark forms;" + " redraw with direct labels/shapes"
            )


def admit(root: ET.Element, request: SvgPresentation) -> AdmittedPlot:
    """Require a light canvas, dark annotations and explicit data roles."""
    _explicit_states(root)
    backdrop = background(root)
    if backdrop is None:
        raise StudyError("a direct full-canvas background must be explicit")
    mapping = _mapping(request)
    targets = {source: target for _, source, target in mapping}
    decorations = frozenset(opaque(value) for value in request.decorative_strokes)
    rendered_text = " ".join(
        (node.text or "") for node in root.iter() if local(node.tag) in {"text", "tspan"}
    )
    if any(channel.legend_text not in rendered_text for channel in request.channels):
        raise StudyError("a declared data role lacks its literal source legend label")
    shapes: dict[str, set[str]] = {source: set() for source in targets}
    print_scale = request.target_print_width_points / float(root.attrib["viewBox"].split()[2])
    roles = PaintRoles(backdrop, targets, decorations, print_scale)
    result: list[RolePaint] = []
    canvas = ""
    for row in painted_nodes(root):
        paints = {key: opaque(value) for key, value in row.values}
        for key, rgb in paints.items():
            if rgb is None:
                continue
            resolved = _resolve(roles, row, (key, rgb))
            if resolved.canvas_rgb is not None:
                canvas = resolved.canvas_rgb
            if resolved.data_form is not None:
                source, form = resolved.data_form
                shapes[source].add(form)
            result.append(resolved.paint)
    if not canvas or any(not value for value in shapes.values()):
        raise StudyError("a declared canvas or data channel is absent")
    _distinctions(mapping, shapes)
    return AdmittedPlot(tuple(result), mapping, canvas)
