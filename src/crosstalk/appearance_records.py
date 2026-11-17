"""Explicit physical-page, rendering and pixel units for appearance descriptors."""

from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .appearance_audit_records import ResourceAudit

type Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type BBox = tuple[float, float, float, float]


class AppearanceError(ValueError):
    """A source or geometry refusal; unrelated valid native text remains admissible."""

    def __init__(self, reason: str) -> None:
        """Preserve typed context without freezing mutable exception traceback fields."""
        self.reason: str = reason
        super().__init__(reason)


class Record(BaseModel):
    """Parse finite frozen records at the external scientific-artifact boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class AppearanceSettings(Record):
    """Target-buffer and declared-raster policies do not certify full-process RAM use."""

    dpi: int = Field(default=72, ge=36, le=150)
    max_pixels: int = Field(default=20_000_000, ge=1, le=20_000_000)
    max_pdf_bytes: int = Field(default=100_000_000, ge=1, le=100_000_000)
    max_source_image_pixels: int = Field(default=100_000_000, ge=1, le=100_000_000)
    max_source_pixel_sum: int = Field(default=200_000_000, ge=1, le=200_000_000)
    max_metadata_nodes: int = Field(default=4096, ge=1, le=20_000)
    max_audit_depth: int = Field(default=64, ge=1, le=64)
    dark_threshold: int = Field(default=245, ge=1, le=255)
    grid_side: int = Field(default=4, ge=1, le=16)
    thumbnail_edge: int = Field(default=384, ge=64, le=1024)
    include_annotations: bool = True
    colorspace: Literal["RGB"] = "RGB"
    background: Literal["white"] = "white"
    grayscale_method: Literal["Pillow convert L"] = "Pillow convert L"


class PixelCell(Record):
    """One exact half-open pixel-grid cell, including explicitly empty small-image cells."""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    box: tuple[int, int, int, int]
    pixels: int = Field(ge=0)
    dark_pixels: int = Field(ge=0)
    dark_fraction: float | None

    @model_validator(mode="after")
    def cell_counts(self) -> Self:
        """Refuse contradictory areas, thresholds and invented empty-cell proportions."""
        left, top, right, bottom = self.box
        if min(left, top) < 0 or right < left or bottom < top:
            raise AppearanceError("pixel cell has invalid half-open bounds")
        if self.pixels != (right - left) * (bottom - top) or self.dark_pixels > self.pixels:
            raise AppearanceError("pixel cell counts disagree with its area")
        expected = self.dark_pixels / self.pixels if self.pixels else None
        if self.dark_fraction != expected:
            raise AppearanceError("pixel cell fraction disagrees with its exact denominator")
        return self


class PixelSummary(Record):
    """Full-render pixel descriptors; the thumbnail never supplies their denominator."""

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    pixels: int = Field(ge=1)
    grayscale_entropy_bits: float = Field(ge=0, le=8)
    mean_rgb: tuple[float, float, float]
    dark_pixels: int = Field(ge=0)
    dark_fraction: float = Field(ge=0, le=1)
    cells: tuple[PixelCell, ...]

    @model_validator(mode="after")
    def summary_counts(self) -> Self:
        """Require exact whole-render and cell count reconciliation."""
        if self.pixels != self.width * self.height or self.dark_pixels > self.pixels:
            raise AppearanceError("appearance counts disagree with the full-render dimensions")
        if self.dark_fraction != self.dark_pixels / self.pixels:
            raise AppearanceError("appearance fraction disagrees with the full-render denominator")
        if any(not 0 <= channel <= 255 for channel in self.mean_rgb):
            raise AppearanceError("appearance RGB mean is outside the measured channel range")
        if (
            sum(cell.pixels for cell in self.cells) != self.pixels
            or sum(cell.dark_pixels for cell in self.cells) != self.dark_pixels
        ):
            raise AppearanceError("appearance cell and whole-render counts disagree")
        return self


class AntiAliasState(Record):
    """Actual native rendering state is observed, never changed inside the library function."""

    graphics: int = Field(ge=0, le=8)
    text: int = Field(ge=0, le=8)
    graphics_min_line_width: float = Field(ge=0)


class PageAppearance(Record):
    """One exact original-PDF physical page, rather than an inferred semantic figure."""

    schema_version: Literal[1] = 1
    source_pdf_sha256: Digest
    page_index: int = Field(ge=0)
    total_pdf_pages: int = Field(ge=1)
    page_rect: BBox
    cropbox: BBox
    mediabox: BBox
    rotation: Literal[0, 90, 180, 270]
    renderer_version: str
    pillow_version: str
    python_version: str
    antialias: AntiAliasState
    settings: AppearanceSettings
    resource_audit: ResourceAudit
    pixels: PixelSummary
    render_pixel_sha256: Digest
    thumbnail_sha256: Digest
    thumbnail_width: int = Field(ge=1, le=1024)
    thumbnail_height: int = Field(ge=1, le=1024)
    semantic_genre: Literal["unclassified"] = "unclassified"
    source_accuracy: None = None

    @model_validator(mode="after")
    def source_policy(self) -> Self:
        """Passed source observations must comply with the recorded raster metadata policy."""
        if self.resource_audit.status != "passed":
            raise AppearanceError(
                "measured appearance requires a passed declared-image metadata audit"
            )
        audit = self.resource_audit
        if (
            audit.metadata_nodes > self.settings.max_metadata_nodes
            or audit.native_inventory_entries is None
            or audit.native_inventory_entries > self.settings.max_metadata_nodes
            or audit.native_max_declared_pixels is None
            or audit.native_max_declared_pixels > self.settings.max_source_image_pixels
            or audit.conservative_declared_pixel_sum > self.settings.max_source_pixel_sum
            or any(
                row.width * row.height > self.settings.max_source_image_pixels
                for row in audit.image_declarations
            )
        ):
            raise AppearanceError("passed source metadata exceeds its declared measurement policy")
        return self

    @model_validator(mode="after")
    def physical_scope(self) -> Self:
        """Pixel-grid and thumbnail metadata cannot silently disagree with their settings."""
        if any(
            box[2] <= box[0] or box[3] <= box[1]
            for box in (self.page_rect, self.cropbox, self.mediabox)
        ):
            raise AppearanceError("appearance page boxes must retain positive physical areas")
        if self.page_index >= self.total_pdf_pages:
            raise AppearanceError("appearance physical page is outside the original PDF")
        if len(self.pixels.cells) != self.settings.grid_side**2:
            raise AppearanceError("appearance grid does not match the declared side length")
        side = self.settings.grid_side
        for index, cell in enumerate(self.pixels.cells):
            row, column = divmod(index, side)
            expected = (
                self.pixels.width * column // side,
                self.pixels.height * row // side,
                self.pixels.width * (column + 1) // side,
                self.pixels.height * (row + 1) // side,
            )
            if (cell.row, cell.column, cell.box) != (row, column, expected):
                raise AppearanceError("appearance cells do not partition the declared pixel grid")
        if self.pixels.pixels > self.settings.max_pixels:
            raise AppearanceError("appearance render exceeds the declared allocation bound")
        if max(self.thumbnail_width, self.thumbnail_height) > self.settings.thumbnail_edge:
            raise AppearanceError("appearance thumbnail exceeds its declared edge bound")
        if self.thumbnail_width > self.pixels.width or self.thumbnail_height > self.pixels.height:
            raise AppearanceError("appearance thumbnail cannot exceed the measured render")
        return self


@dataclass(frozen=True, slots=True)
class RenderedAppearance:
    """Internal measured record and exact derived PNG, still awaiting manager output seals."""

    record: PageAppearance
    thumbnail_png: bytes
