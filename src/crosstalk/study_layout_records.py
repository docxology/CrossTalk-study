"""Independent native-layout derivative; font flags remain reported metadata."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- Pydantic parses the selected physical path at runtime.
from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator

from crosstalk.study_language_records import Digest, Record, StudyError

Coordinates = tuple[float, float, float, float]
Matrix = tuple[float, float, float, float, float, float]


class NativeDocumentFacts(Record):
    """Parse only live native document admission fields at the dependency boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    is_pdf: bool
    needs_pass: Literal[0, 1]
    page_count: int


class Rectangle(Record):
    """Finite positive-area rectangle in an explicitly declared coordinate system."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def positive(self) -> Rectangle:
        """Reject degenerate geometry rather than clamp source observations."""
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise StudyError("layout rectangle requires positive area")
        return self

    @property
    def area(self) -> float:
        """Return area in squared PDF points."""
        return (self.x1 - self.x0) * (self.y1 - self.y0)


class NativeSpan(Record):
    """One native span; apparent bold/italic validity is not independently established."""

    bbox: Coordinates
    text: str
    font: str
    size: float = Field(ge=0)
    flags: int = Field(ge=0)
    color: int = Field(ge=0)
    origin: tuple[float, float]


class NativeLine(Record):
    """Native span order and writing direction, without a verified reading sequence."""

    bbox: Coordinates
    direction: tuple[float, float]
    writing_mode: int
    spans: tuple[NativeSpan, ...]


class FontMeasure(Record):
    """Native character-weighted reported typography at one size/font/flag combination."""

    font: str
    size_points: float
    reported_flags: int
    characters: int


class ColumnCandidate(Record):
    """Repeated near-horizontal line starts; indentation can also produce a candidate."""

    x_points: float
    supporting_lines: int


class LayoutSettings(Record):
    """Native text-only inspection; no images or raster decoding are requested."""

    maximum_pdf_bytes: int = Field(default=100_000_000, ge=1, le=100_000_000)
    maximum_spans: int = Field(default=20_000, ge=1, le=100_000)
    maximum_lines: int = Field(default=10_000, ge=1, le=20_000)
    maximum_union_rectangles: int = Field(default=2500, ge=1, le=10_000)
    column_start_tolerance: float = Field(default=12.0, gt=0, le=72)
    column_minimum_lines: int = Field(default=4, ge=2, le=100)


class LayoutRequest(Record):
    """Exact original PDF and a finite independently selected physical-page sequence."""

    pdf: Path
    pdf_sha256: Digest
    page_indices: Annotated[tuple[int, ...], Field(min_length=1, max_length=500)]
    settings: LayoutSettings = LayoutSettings()

    @model_validator(mode="after")
    def unique_pages(self) -> LayoutRequest:
        """Reject negative and repeated selections rather than multiply observations."""
        if min(self.page_indices) < 0 or len(set(self.page_indices)) != len(self.page_indices):
            raise StudyError("layout physical-page selection must be unique and nonnegative")
        return self


class PageLayout(Record):
    """Raw native geometry and separate measurements; current3 page bytes remain unchanged."""

    method_version: Literal["study-layout-1"] = "study-layout-1"
    pdf_sha256: Digest
    page_index: int
    implementation_sha256: Digest
    pymupdf_version: str
    settings: LayoutSettings
    cropbox: Coordinates
    mediabox: Coordinates
    rotation: Literal[0, 90, 180, 270]
    rotation_matrix: Matrix
    derotation_matrix: Matrix
    unrotated_frame: Rectangle
    displayed_rect: Coordinates
    lines: tuple[NativeLine, ...]
    fonts: tuple[FontMeasure, ...]
    column_start_candidates: tuple[ColumnCandidate, ...]
    text_status: Literal["native-spans-observed", "no-native-spans"]
    text_union_area_points_squared: float | None
    text_union_fraction: Annotated[float | None, Field(ge=0, le=1)]
    union_status: Literal["measured", "rectangle-capacity-refused"]
    spans_outside_frame: int
    degenerate_span_boxes: int
    median_character_weighted_size_points: float | None
    reported_bold_character_fraction: Annotated[float | None, Field(ge=0, le=1)]
    reported_italic_character_fraction: Annotated[float | None, Field(ge=0, le=1)]
    coordinates: Literal["unrotated crop-relative PDF points; top-left origin; y down"] = (
        "unrotated crop-relative PDF points; top-left origin; y down"
    )
    reading_order_verified: Literal[False] = False
    font_metadata_validated: Literal[False] = False
    union_scope: str = (
        "Union of native span rectangles intersected with the visible unrotated frame"
    )
