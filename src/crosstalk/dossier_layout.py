"""Small vector drawing primitives with explicit typography and overflow refusal."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING, Final

import pymupdf
from pydantic import TypeAdapter

from crosstalk.models import AcquisitionError
from crosstalk.records import Record

if TYPE_CHECKING:
    from crosstalk.records import BBox

RGB = tuple[float, float, float]
Point = tuple[float, float]
NAVY: Final[RGB] = (0.075, 0.16, 0.23)
TEAL: Final[RGB] = (0.0, 0.43, 0.43)
CORAL: Final[RGB] = (0.77, 0.31, 0.23)
IVORY: Final[RGB] = (0.97, 0.96, 0.93)
PALE: Final[RGB] = (0.9, 0.94, 0.92)
WHITE: Final[RGB] = (1.0, 1.0, 1.0)
MUTED: Final[RGB] = (0.34, 0.40, 0.43)
LINE: Final[RGB] = (0.78, 0.82, 0.81)
NUMBER: Final = TypeAdapter(float)


class _PointValue(Record):
    """Parse the PDF dependency's drawing result at the adapter boundary."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Typography in PDF points and an explicit RGB color space."""

    size: float = 10.2
    font: str = "helv"
    color: RGB = NAVY
    align: int = 0


@dataclass(frozen=True, slots=True)
class Label:
    """A text region whose fit is checked before publication."""

    bounds: BBox
    text: str
    style: TextStyle = TextStyle()


@dataclass(frozen=True, slots=True)
class Card:
    """One explanatory diagram node with a title and a readable body."""

    bounds: BBox
    title: str
    body: str
    accent: RGB = TEAL


def plain_text(text: str) -> str:
    """Normalize typographic punctuation for the portable Base-14 PDF fonts."""
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2013": "-",
        "\u2014": " - ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u2192": " -> ",
        "\u2264": "<=",
        "\u2265": ">=",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text.replace("**", "").replace("`", "")


def text_width(text: str, style: TextStyle) -> float:
    """Parse the partially typed dependency's measured font width."""
    return NUMBER.validate_python(
        getattr(pymupdf, "get_text_length")(  # noqa: B009 -- dependency typing boundary.
            plain_text(text), fontname=style.font, fontsize=style.size
        )
    )


def wrap_text(text: str, width: float) -> tuple[str, ...]:
    """Wrap prose using actual Base-14 glyph widths, splitting long locators."""
    lines: list[str] = []
    current = ""
    for word in plain_text(text).split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate, TextStyle()) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for character in word:
            if text_width(current + character, TextStyle()) > width and current:
                lines.append(current)
                current = ""
            current += character
    if current:
        lines.append(current)
    return tuple(lines or ("",))


class PageCanvas:
    """Mutable page builder counts successful bounded text placements."""

    def __init__(self, page: pymupdf.Page, number: int) -> None:
        """Initialize a consistent A4 editorial page and its folio."""
        self.page: pymupdf.Page = page
        self.number: int = number
        self.text_boxes: int = 0
        self.rectangle((0, 0, 595, 842), IVORY)
        self.rectangle((42, 30, 88, 35), TEAL)
        self.line((42, 795), (553, 795))
        self.text(
            Label(
                (42, 805, 492, 827),
                "CROSSTALK  /  RESEARCH PROTOCOL AND LOCAL EVIDENCE",
                TextStyle(8, color=MUTED),
            )
        )
        self.text(Label((515, 801, 553, 825), f"{number:02d}", TextStyle(11, "hebo", TEAL, 2)))

    def rectangle(self, bounds: BBox, fill: RGB) -> None:
        """Draw an opaque vector panel; PDF library results remain local."""
        _ = _PointValue.model_validate(
            getattr(self.page, "draw_rect")(bounds, color=fill, fill=fill, width=0),  # noqa: B009
            from_attributes=True,
        )

    def line(self, start: Point, end: Point) -> None:
        """Draw a thin connector or rule with a consistent neutral color."""
        _ = _PointValue.model_validate(
            getattr(self.page, "draw_line")(start, end, color=LINE, width=0.8),  # noqa: B009
            from_attributes=True,
        )

    def arrow(self, start: Point, end: Point) -> None:
        """Draw a directed connector without relying on Unicode arrow glyphs."""
        self.line(start, end)
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        if length == 0:
            raise AcquisitionError("Diagram connector has zero length")
        ux, uy = dx / length, dy / length
        self.line(end, (end[0] - 5 * ux + 3 * uy, end[1] - 5 * uy - 3 * ux))
        self.line(end, (end[0] - 5 * ux - 3 * uy, end[1] - 5 * uy + 3 * ux))

    def text(self, label: Label) -> None:
        """Refuse out-of-page or clipped text instead of dropping content."""
        x0, y0, x1, y1 = label.bounds
        if not (0 <= x0 < x1 <= 595 and 0 <= y0 < y1 <= 842):
            raise AcquisitionError("Dossier text region exceeds page bounds")
        remainder = NUMBER.validate_python(
            getattr(self.page, "insert_textbox")(  # noqa: B009 -- dependency typing boundary.
                label.bounds,
                plain_text(label.text),
                fontsize=label.style.size,
                fontname=label.style.font,
                color=label.style.color,
                align=label.style.align,
                lineheight=1.35,
            )
        )
        if remainder < -0.001:
            raise AcquisitionError(
                f"Dossier text would be clipped on page {self.number} "
                + f"(needs {-remainder:.2f} more points): {label.text[:60]}"
            )
        self.text_boxes += 1

    def card(self, card: Card) -> None:
        """Draw an explanatory card with a color-coded top rule."""
        x0, y0, x1, y1 = card.bounds
        self.rectangle(card.bounds, WHITE)
        self.rectangle((x0, y0, x1, y0 + 4), card.accent)
        self.text(
            Label(
                (x0 + 12, y0 + 13, x1 - 12, y0 + 38), card.title, TextStyle(11, "hebo", card.accent)
            )
        )
        self.text(Label((x0 + 12, y0 + 43, x1 - 12, y1 - 9), card.body, TextStyle(9.5)))

    def heading(self, title: str, subtitle: str, eyebrow: str = "GRAPHICAL ABSTRACT") -> None:
        """Reserve a fixed, readable header above the graphical content."""
        self.text(Label((42, 49, 553, 72), "CROSSTALK  /  " + eyebrow, TextStyle(9, "hebo", TEAL)))
        self.text(Label((42, 79, 553, 124), title, TextStyle(25, "tibo")))
        self.text(Label((42, 125, 553, 158), subtitle, TextStyle(10, color=MUTED)))
