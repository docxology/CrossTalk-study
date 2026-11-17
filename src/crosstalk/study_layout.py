"""Text-only PDF typography and bounded exact rectangle-union measurements."""

from __future__ import annotations

import hashlib
import math
import os
import stat
from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING, ClassVar, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from crosstalk.study_language import implementation_digest
from crosstalk.study_language_records import StudyError
from crosstalk.study_layout_records import (
    ColumnCandidate,
    FontMeasure,
    NativeDocumentFacts,
    NativeLine,
    NativeSpan,
    PageLayout,
    Rectangle,
)

if TYPE_CHECKING:
    from crosstalk.study_layout_records import LayoutRequest, LayoutSettings


class _Line(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", allow_inf_nan=False)
    bbox: tuple[float, float, float, float]
    direction: tuple[float, float] = Field(alias="dir")
    writing_mode: int = Field(alias="wmode")
    spans: tuple[_Span, ...]


class _Span(NativeSpan):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", allow_inf_nan=False)


class _Block(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    kind: int = Field(alias="type")
    lines: tuple[_Line, ...] = ()


class _Text(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    blocks: tuple[_Block, ...]


class _Geometry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, allow_inf_nan=False)
    x0: float
    y0: float
    x1: float
    y1: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)

    @property
    def coordinates(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1


class _Matrix(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, allow_inf_nan=False)
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @property
    def coefficients(self) -> tuple[float, float, float, float, float, float]:
        return self.a, self.b, self.c, self.d, self.e, self.f


class _PageFacts(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    number: int
    rotation: Literal[0, 90, 180, 270]
    cropbox: _Geometry
    mediabox: _Geometry
    rect: _Geometry
    rotation_matrix: _Matrix
    derotation_matrix: _Matrix


def rectangle_union_area(rectangles: tuple[Rectangle, ...]) -> float:
    """Exact axis-aligned union, including overlaps once; finite quadratic sweep bound."""
    if len(rectangles) > 10_000:
        raise StudyError("rectangle union exceeds its explicit 10000-rectangle bound")
    edges = sorted({x for rect in rectangles for x in (rect.x0, rect.x1)})
    area = 0.0
    for left, right in pairwise(edges):
        intervals = sorted(
            (rect.y0, rect.y1) for rect in rectangles if rect.x0 < right and rect.x1 > left
        )
        covered, stop = 0.0, -math.inf
        for low, high in intervals:
            covered += max(0.0, high - max(low, stop))
            stop = max(stop, high)
        area += (right - left) * covered
    return area


def _columns(
    lines: tuple[NativeLine, ...], settings: LayoutSettings
) -> tuple[ColumnCandidate, ...]:
    starts = sorted(line.bbox[0] for line in lines if line.spans and abs(line.direction[1]) < 0.01)
    groups: list[list[float]] = []
    for value in starts:
        if groups and value - groups[-1][0] <= settings.column_start_tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return tuple(
        ColumnCandidate(x_points=sum(group) / len(group), supporting_lines=len(group))
        for group in groups
        if len(group) >= settings.column_minimum_lines
    )


def _metrics(
    lines: tuple[NativeLine, ...], frame: Rectangle, settings: LayoutSettings
) -> tuple[tuple[FontMeasure, ...], tuple[Rectangle, ...], int, int]:
    fonts: Counter[tuple[str, float, int]] = Counter()
    boxes: list[Rectangle] = []
    outside, degenerate = 0, 0
    for line in lines:
        for span in line.spans:
            fonts[(span.font, span.size, span.flags)] += len(span.text)
            left, top, right, bottom = span.bbox
            outside += int(
                left < frame.x0 or top < frame.y0 or right > frame.x1 or bottom > frame.y1
            )
            if right <= left or bottom <= top:
                degenerate += 1
            elif min(right, frame.x1) > max(left, frame.x0) and min(bottom, frame.y1) > max(
                top, frame.y0
            ):
                boxes.append(
                    Rectangle(
                        x0=max(left, frame.x0),
                        y0=max(top, frame.y0),
                        x1=min(right, frame.x1),
                        y1=min(bottom, frame.y1),
                    )
                )
    if sum(len(line.spans) for line in lines) > settings.maximum_spans:
        raise StudyError("native span capacity exceeded")
    return (
        tuple(
            FontMeasure(font=font, size_points=size, reported_flags=flags, characters=count)
            for (font, size, flags), count in sorted(fonts.items())
        ),
        tuple(boxes),
        outside,
        degenerate,
    )


def _page(page: pymupdf.Page, request: LayoutRequest, method: str) -> PageLayout:
    parsed = _Text.model_validate(
        getattr(page, "get_text")(  # noqa: B009 -- Parse untyped native text payload.
            "dict",
            flags=TypeAdapter(int).validate_python(
                getattr(pymupdf, "TEXTFLAGS_TEXT")  # noqa: B009 -- Parse native constant.
            ),
            sort=False,
        )
    )
    if any(block.kind != 0 for block in parsed.blocks):
        raise StudyError("text-only native extraction unexpectedly returned nontext blocks")
    lines = tuple(
        NativeLine(
            bbox=line.bbox,
            direction=line.direction,
            writing_mode=line.writing_mode,
            spans=tuple(NativeSpan.model_validate(span.model_dump()) for span in line.spans),
        )
        for block in parsed.blocks
        for line in block.lines
    )
    if len(lines) > request.settings.maximum_lines:
        raise StudyError("native line capacity exceeded")
    facts = _PageFacts.model_validate(page)
    crop = facts.cropbox
    frame = Rectangle(x0=0.0, y0=0.0, x1=crop.width, y1=crop.height)
    fonts, boxes, outside, degenerate = _metrics(lines, frame, request.settings)
    characters = sum(font.characters for font in fonts)
    sizes = sorted((font.size_points, font.characters) for font in fonts if font.characters)
    cumulative, median = 0, None
    for size, count in sizes:
        cumulative += count
        if cumulative >= characters / 2:
            median = size
            break
    measured = len(boxes) <= request.settings.maximum_union_rectangles
    area = rectangle_union_area(boxes) if measured else None
    return PageLayout(
        pdf_sha256=request.pdf_sha256,
        page_index=facts.number,
        implementation_sha256=method,
        pymupdf_version=pymupdf.VersionBind,
        settings=request.settings,
        cropbox=facts.cropbox.coordinates,
        mediabox=facts.mediabox.coordinates,
        rotation=facts.rotation,
        rotation_matrix=facts.rotation_matrix.coefficients,
        derotation_matrix=facts.derotation_matrix.coefficients,
        unrotated_frame=frame,
        displayed_rect=facts.rect.coordinates,
        lines=lines,
        fonts=fonts,
        column_start_candidates=_columns(lines, request.settings),
        text_status="native-spans-observed" if characters else "no-native-spans",
        text_union_area_points_squared=area,
        text_union_fraction=area / frame.area if area is not None else None,
        union_status="measured" if measured else "rectangle-capacity-refused",
        spans_outside_frame=outside,
        degenerate_span_boxes=degenerate,
        median_character_weighted_size_points=median,
        reported_bold_character_fraction=sum(
            font.characters for font in fonts if font.reported_flags & 16
        )
        / characters
        if characters
        else None,
        reported_italic_character_fraction=sum(
            font.characters for font in fonts if font.reported_flags & 2
        )
        / characters
        if characters
        else None,
    )


def inspect_layout(request: LayoutRequest) -> tuple[PageLayout, ...]:
    """Read one exact regular PDF once; retain raw spans and no raster payloads or cache writes."""
    path = request.pdf.absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise StudyError("layout input alias refused")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > request.settings.maximum_pdf_bytes
        ):
            raise StudyError("layout needs a single-link bounded ordinary PDF")
        raw = stream.read(request.settings.maximum_pdf_bytes + 1)
        after = os.fstat(stream.fileno())
    if (
        len(raw) > request.settings.maximum_pdf_bytes
        or hashlib.sha256(raw).hexdigest() != request.pdf_sha256
    ):
        raise StudyError("layout PDF digest/byte capacity differs from independent selection")
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise StudyError("layout PDF changed during read")
    method = implementation_digest()
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        facts = NativeDocumentFacts.model_validate(document)
        if not facts.is_pdf or facts.needs_pass or max(request.page_indices) >= facts.page_count:
            raise StudyError("layout PDF/page selection is unavailable or encrypted")
        result = tuple(_page(document[index], request, method) for index in request.page_indices)
    if implementation_digest() != method:
        raise StudyError("layout implementation changed during inspection")
    return result
