"""Conservative PDF text paint diagnostics, separate from OCR admission."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypedDict, cast

import pymupdf

from crosstalk.appearance_render import NativeFrame, NativePixmap

if TYPE_CHECKING:
    from collections.abc import Iterable


class PaintClass(StrEnum):
    """Observable span classes; background contrast is tested separately."""

    IGNORE = "ignore-mode"
    TRANSPARENT = "zero-opacity"
    WHITE = "white-paint"
    OTHER = "other-paint"


@dataclass(frozen=True, slots=True)
class VisibilityWitness:
    """An exact text span and a conservative rendered-blank witness."""

    page_index: int
    bbox: tuple[float, float, float, float]
    paint: PaintClass
    dark_pixels: int
    pixels: int

    @property
    def blank(self) -> bool:
        """Require a strictly white grayscale raster over the clipped box."""
        return self.pixels > 0 and self.dark_pixels == 0


def paint_class(kind: int, opacity: float, color: tuple[float, ...]) -> PaintClass:
    """Classify trace metadata in priority order without inferring semantic loss."""
    if kind == 3:
        return PaintClass.IGNORE
    if opacity == 0:
        return PaintClass.TRANSPARENT
    if kind in (0, 1) and (len(color) in (1, 3)) and all(value == 1 for value in color):
        return PaintClass.WHITE
    return PaintClass.OTHER


_Box = tuple[float, float, float, float]
type _TraceChar = tuple[int, int, tuple[float, float], _Box]


class _TraceSpan(TypedDict):
    chars: tuple[_TraceChar, ...]
    type: int
    opacity: float
    color: tuple[float, ...] | None
    bbox: _Box


def span_text(span: _TraceSpan) -> str:
    """Decode the Unicode code points in paint order; do not infer word spaces."""
    return "".join(chr(item[0]) for item in span["chars"] if 0 <= item[0] <= 0x10FFFF)


def document_trace(
    source: pymupdf.Document, phrases: Iterable[str] = ()
) -> tuple[Counter[str], list[VisibilityWitness]]:
    """Count witness-bearing pages and classify exact anchor spans."""
    anchors = tuple(phrases)
    counts: Counter[str] = Counter()
    witnesses: list[VisibilityWitness] = []
    for page_index in range(len(source)):
        page = source[page_index]
        counts["pages"] += 1
        seen: set[PaintClass] = set()
        for span in cast("list[_TraceSpan]", page.get_texttrace()):
            if not span["chars"]:
                continue
            kind = paint_class(span["type"], span["opacity"], tuple(span["color"] or ()))
            seen.add(kind)
            if anchors and any(phrase in span_text(span) for phrase in anchors):
                frame = NativeFrame.model_validate(page).rect
                x0, y0, x1, y1 = span["bbox"]
                left, top = max(frame.x0, x0), max(frame.y0, y0)
                right, bottom = min(frame.x1, x1), min(frame.y1, y1)
                if left >= right or top >= bottom:
                    dark, total = 0, 0
                else:
                    rect = pymupdf.Rect(left, top, right, bottom)
                    pix = NativePixmap.model_validate(
                        getattr(page, "get_pixmap")(  # noqa: B009 -- Native adapter boundary.
                            matrix=pymupdf.Matrix(2, 2),
                            clip=rect,
                            colorspace=pymupdf.csGRAY,
                            annots=False,
                        )
                    )
                    samples = pix.samples
                    total, dark = len(samples), len(samples) - samples.count(b"\xff")
                witnesses.append(VisibilityWitness(page_index, span["bbox"], kind, dark, total))
        counts.update(kind.value for kind in seen)
        if seen:
            counts["trace-pages"] += 1
        if seen and seen <= {PaintClass.TRANSPARENT, PaintClass.IGNORE}:
            counts["nonpainting-only-pages"] += 1
    return counts, witnesses
