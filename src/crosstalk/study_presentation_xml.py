"""Bounded inert SVG parsing, resolved paints and unchanged data-text/geometry fingerprints."""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from typing import Final

from crosstalk.study_language_records import StudyError
from crosstalk.study_presentation_paint import LOCAL, color

SVG: Final = "http://www.w3.org/2000/svg"
XML: Final = "http://www.w3.org/XML/1998/namespace"
XLINK: Final = "http://www.w3.org/1999/xlink"
PAINT: Final = {"fill", "stroke", "color", "stop-color"}
ALLOWED: Final = {
    "svg",
    "g",
    "rect",
    "line",
    "circle",
    "ellipse",
    "path",
    "polygon",
    "polyline",
    "text",
    "tspan",
    "defs",
    "clipPath",
    "stop",
    "metadata",
    "title",
    "desc",
}
LEAVES: Final = {
    "rect",
    "line",
    "circle",
    "ellipse",
    "path",
    "polygon",
    "polyline",
    "text",
    "tspan",
    "stop",
    "use",
}
STYLE: Final = PAINT | {
    "fill-opacity",
    "stroke-opacity",
    "stop-opacity",
    "opacity",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "text-anchor",
    "dominant-baseline",
    "clip-path",
    "stroke-dasharray",
    "display",
}
type SemanticNode = tuple[
    str, tuple[tuple[str, str], ...], str | None, str | None, tuple[SemanticNode, ...]
]


def local(tag: str) -> str:
    """Only SVG elements are accepted; namespace aliases cannot smuggle active content."""
    if tag.startswith("{" + SVG + "}"):
        return tag.split("}", 1)[1]
    raise StudyError("presentation requires the SVG namespace on every element")


def styles(value: str) -> dict[str, str]:
    """Parse a bounded property list rather than execute CSS or external style references."""
    result: dict[str, str] = {}
    for declaration in value.split(";"):
        if not declaration.strip():
            continue
        if ":" not in declaration:
            raise StudyError("malformed SVG style declaration")
        key, setting = (part.strip() for part in declaration.split(":", 1))
        if key not in STYLE or key in result:
            raise StudyError("unsupported/duplicate SVG style property needs a redraw")
        if "url" in setting.casefold() and not LOCAL.fullmatch(setting):
            raise StudyError("external SVG style reference refused")
        result[key] = setting
    return result


def _attributes(node: ET.Element) -> None:
    """Check passive attribute namespace, local references and CSS once at each XML node."""
    for key, value in node.attrib.items():
        name = key.rsplit("}", 1)[-1]
        if (
            key.startswith("{")
            and not key.startswith("{" + XML + "}")
            and not key.startswith("{" + XLINK + "}")
        ):
            raise StudyError("foreign SVG attribute namespace refused")
        if name.casefold().startswith("on") or (name == "href" and not value.startswith("#")):
            raise StudyError("active/external SVG attribute refused")
        if "url" in value.casefold() and key != "style" and not LOCAL.fullmatch(value):
            raise StudyError("external SVG reference refused")
        if key == "style":
            _ = styles(value)


def parse(raw: bytes, maximum_elements: int) -> ET.Element:
    """Parse finite passive SVG; refuse active content and image evidence."""
    try:
        source = raw.decode("utf-8")
    except UnicodeError as error:
        raise StudyError("presentation requires UTF8 vector source") from error
    if "\x00" in source or "<!doctype" in source.casefold() or "<!entity" in source.casefold():
        raise StudyError("DTD/entity or non-UTF8 SVG source refused")
    try:
        root = ET.fromstring(source)  # noqa: S314 -- UTF8, bounded, no DTD/entities; passive tags/attributes checked below.
    except ET.ParseError as error:
        raise StudyError("malformed vector source") from error
    pending = [(root, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        tag = local(node.tag)
        if depth > 64 or count > maximum_elements or tag not in ALLOWED:
            raise StudyError("SVG tree exceeds passive vector shape/depth/capacity")
        _attributes(node)
        pending.extend((child, depth + 1) for child in node)
    if local(root.tag) != "svg":
        raise StudyError("presentation needs one SVG document root")
    return root


@dataclass(frozen=True, slots=True)
class PaintedNode:
    """Computed leaf paints include inherited/default channels, preventing accidental collapse."""

    element: ET.Element
    values: tuple[tuple[str, str], ...]


def painted_nodes(root: ET.Element) -> tuple[PaintedNode, ...]:
    """Resolve inherited SVG paints before any palette choice or replacement occurs."""
    pending = [(root, {"fill": "black", "stroke": "none", "color": "black", "stop-color": "black"})]
    result: list[PaintedNode] = []
    while pending:
        node, inherited = pending.pop()
        tag = local(node.tag)
        if tag == "metadata":
            continue
        computed = dict(inherited)
        declared = {key: value for key, value in node.attrib.items() if key in PAINT}
        declared.update(
            (key, value) for key, value in styles(node.get("style", "")).items() if key in PAINT
        )
        for key, value in declared.items():
            if value.casefold() != "inherit":
                computed[key] = (
                    inherited["color"]
                    if key == "color" and value.casefold() == "currentcolor"
                    else value
                )
        if tag in LEAVES:
            relevant = {"stop-color"} if tag == "stop" else {"fill", "stroke"}
            if tag == "line":
                relevant = {"stroke"}
            if tag in {"text", "tspan"}:
                relevant = {"fill", "stroke"}
            result.append(
                PaintedNode(
                    node,
                    tuple(
                        (
                            key,
                            computed["color"]
                            if computed[key].casefold() == "currentcolor"
                            else computed[key],
                        )
                        for key in sorted(relevant)
                    ),
                )
            )
        pending.extend((child, computed) for child in reversed(node))
    return tuple(result)


def background(root: ET.Element) -> ET.Element | None:
    """Recognize only a direct full-canvas background; never infer a plot cell or journal image."""
    parts = root.get("viewBox", "").split()
    if len(parts) != 4:
        raise StudyError("themed SVG needs an explicit finite viewBox")
    try:
        frame = tuple(float(part) for part in parts)
    except ValueError as error:
        raise StudyError("invalid source SVG viewBox") from error
    if not all(math.isfinite(value) for value in frame) or frame[2] <= 0 or frame[3] <= 0:
        raise StudyError("invalid source SVG viewBox")
    for node in root:
        if local(node.tag) != "rect":
            continue
        try:
            bounds = tuple(float(node.get(key, "0")) for key in ("x", "y", "width", "height"))
        except ValueError:
            continue
        if bounds == frame:
            return node
    return None


def semantics(root: ET.Element) -> str:
    """Fingerprint text/nonpaint attributes while preserving alpha/reference structure."""
    paints = {row.element: row.values for row in painted_nodes(root)}

    def project(node: ET.Element) -> SemanticNode:
        attributes = {
            key: value for key, value in node.attrib.items() if key not in PAINT | {"style"}
        }
        for key, value in styles(node.get("style", "")).items():
            if key not in PAINT:
                attributes["style:" + key] = value
        for key, value in paints.get(node, ()):
            rgb, alpha = color(value)
            attributes["paint-alpha:" + key] = (
                alpha
                if rgb is not None and alpha is not None
                else "opaque"
                if rgb is not None
                else value
            )
        children = tuple(project(child) for child in node if local(child.tag) != "metadata")
        return node.tag, tuple(sorted(attributes.items())), node.text, node.tail, children

    return hashlib.sha256(json.dumps(project(root), separators=(",", ":")).encode()).hexdigest()


def serialize(root: ET.Element) -> str:
    """Emit a literal SVG root without changing global XML registries."""
    xlink = any(key.startswith("{" + XLINK + "}") for node in root.iter() for key in node.attrib)

    def element(node: ET.Element, *, document_root: bool = False) -> str:
        attributes = dict(node.attrib)
        if document_root:
            attributes["xmlns"] = SVG
            if xlink:
                attributes["xmlns:xlink"] = XLINK
        pairs: list[str] = []
        for key, value in attributes.items():
            if key.startswith("{" + XML + "}"):
                name = "xml:" + key.split("}", 1)[1]
            elif key.startswith("{" + XLINK + "}"):
                name = "xlink:" + key.split("}", 1)[1]
            else:
                name = key
            pairs.append(" " + name + '="' + escape(value, quote=True) + '"')
        tag = local(node.tag)
        body = escape(node.text or "") + "".join(element(child) for child in node)
        return "<" + tag + "".join(pairs) + ">" + body + "</" + tag + ">" + escape(node.tail or "")

    return element(root, document_root=True)
