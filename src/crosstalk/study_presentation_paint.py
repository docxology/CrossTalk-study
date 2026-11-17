"""Explicit RGB parsing and a small, contrast-tested discrete briefing palette."""

from __future__ import annotations

import re
from typing import Final

from crosstalk.study_language_records import StudyError

NAMES: Final = {
    "black": "#000000",
    "white": "#ffffff",
    "gray": "#808080",
    "grey": "#808080",
    "red": "#ff0000",
    "navy": "#000080",
    "teal": "#008080",
}
RGB: Final = re.compile(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")
RGBA: Final = re.compile(
    "rgba\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d"
    + "{1,3})\\s*,\\s*(0(?:\\.\\d+)?|1(?:\\.0+)?)\\s*\\)"
)
LOCAL: Final = re.compile(r"url\(#[A-Za-z_][A-Za-z0-9_.:-]*\)")


def color(value: str) -> tuple[str | None, str | None]:
    """Only explicit finite RGB paints can cross this presentation boundary."""
    normalized = value.strip().lower()
    if normalized in {"none", "inherit", "currentcolor"} or LOCAL.fullmatch(value.strip()):
        return None, None
    if normalized in NAMES:
        return NAMES[normalized], None
    if re.fullmatch(r"#[0-9a-f]{3}", normalized):
        return "#" + "".join(char * 2 for char in normalized[1:]), None
    if re.fullmatch(r"#[0-9a-f]{6}", normalized):
        return normalized, None
    match = RGB.fullmatch(normalized) or RGBA.fullmatch(normalized)
    if match is None:
        raise StudyError("unsupported SVG paint needs a data-bound redraw")
    values = tuple(int(match.group(index)) for index in (1, 2, 3))
    if max(values) > 255:
        raise StudyError("SVG paint exceeds the RGB range")
    return "#" + "".join(f"{component:02x}" for component in values), match.group(4) if len(
        match.groups()
    ) == 4 else None


def opaque(value: str) -> str | None:
    """Local paint servers, inherited expressions and translucency require a bound-data redraw."""
    rgb, alpha = color(value)
    if (alpha is not None and float(alpha) != 1.0) or (rgb is None and value.casefold() != "none"):
        raise StudyError("only explicit opaque RGB or none is supported")
    return rgb


def luminance(rgb: str) -> float:
    """Compute sRGB luminance for contrast screening, without perceptual claims."""
    components = tuple(int(rgb[index : index + 2], 16) / 255 for index in (1, 3, 5))
    linear = tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in components
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    """Compute a contrast ratio; low-contrast data pairs require different existing mark forms."""
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)
