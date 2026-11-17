"""Escaped vector labels and conservative paragraph wrapping retain complete supplied text."""

from __future__ import annotations

import unicodedata
from html import escape

from crosstalk.study_language_records import StudyError

type Box = tuple[float, float, float, float]


def text(position: tuple[float, float], value: str, size: float = 22) -> str:
    """Keep every supplied label inert, including markup characters in article titles."""
    return (
        (
            '<text x="'
            + f"{position[0]:.2f}"
            + '" y="'
            + f"{position[1]:.2f}"
            + '" font-size="'
            + f"{size:.2f}"
            + '">'
        )
        + escape(value)
        + "</text>"
    )


def arrow(start: tuple[float, float], end: tuple[float, float], shade: str) -> str:
    """Draw a source-flow annotation with its caller-declared paint."""
    x, y = end
    return (
        f'<line x1="{start[0]}" y1="{start[1]}" x2="{x - 8}" y2="{y}" '
        + f'stroke="{shade}" stroke-width="3"/>'
        + (
            '<polygon points="'
            + f"{x - 10}"
            + ","
            + f"{y - 7}"
            + " "
            + f"{x}"
            + ","
            + f"{y}"
            + " "
            + f"{x - 10}"
            + ","
            + f"{y + 7}"
            + '" fill="'
            + f"{shade}"
            + '"/>'
        )
    )


def width(value: str, size: float) -> float:
    """Estimate wrapping advances, without calling those estimates measured glyph ink."""
    total = 0.0
    for char in value:
        if char.isspace():
            unit = 0.3
        elif char in "ilI.,'`:;!|":
            unit = 0.32
        elif char in "MWmw@%&":
            unit = 1.05
        elif char.isascii():
            unit = 0.85 if char.isupper() else 0.62
        else:
            unit = 2.0 if unicodedata.east_asian_width(char) in {"W", "F"} else 1.05
        total += unit * size
    return total


def paragraph(box: Box, value: str, size: float = 22) -> str:
    """Wrap complete text; refuse overflow rather than dropping an exclusion or limitation."""
    x, y, available_width, available_height = box
    lines: list[str] = []
    line = ""
    for word in value.split():
        if width(word, size) > available_width:
            raise StudyError("graphical paragraph contains an overlong unbreakable word")
        candidate = (line + " " + word).strip()
        if line and width(candidate, size) > available_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) * size * 1.25 > available_height:
        raise StudyError("graphical paragraph exceeds its bounded complete-text area")
    return "".join(
        text((x, y + size + index * size * 1.25), line, size) for index, line in enumerate(lines)
    )
