"""Declared source-page pixels and cover selections do not establish scientific admission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, model_validator

from crosstalk.study_language_records import Digest, Record, StudyError

Identifier = Annotated[str, Field(min_length=1, max_length=240)]
CoverStatus = Literal[
    "verified-cover", "candidate-first-retained-page", "not-located-in-inspected-pdf", "unavailable"
]
ImageBasis = Literal["full-page-render", "accepted-appearance-thumbnail"]


class ArtifactBinding(Record):
    """A caller-selected project-local artifact, rechecked independently before publication."""

    path: str = Field(min_length=1, max_length=1200)
    sha256: Digest

    @model_validator(mode="after")
    def local_path(self) -> ArtifactBinding:
        """Do not let an atlas metadata record expand filesystem custody."""
        value = PurePosixPath(self.path)
        if (
            not value.parts
            or value.is_absolute()
            or ".." in value.parts
            or "\\" in self.path
            or value.as_posix() != self.path
        ):
            raise StudyError("atlas binding requires an ordinary project-local POSIX path")
        return self


class PageImage(Record):
    """Exact PNG declaration; the caller still admits its PDF/render/index provenance."""

    issue_id: Identifier
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    total_pdf_pages: int = Field(ge=1)
    source_pdf: ArtifactBinding
    source_evidence: ArtifactBinding
    image: ArtifactBinding
    rendering_identity: Digest
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    image_basis: ImageBasis
    whole_declared_page_viewport: Literal[True] = True

    @property
    def page_key(self) -> str:
        """Physical PDF identity remains independent of catalog aliases and printed folios."""
        return f"{self.pdf_sha256}:{self.page_index}"

    @model_validator(mode="after")
    def physical_scope(self) -> PageImage:
        """Refuse internally contradictory PDF/page declarations."""
        if self.source_pdf.sha256 != self.pdf_sha256 or self.page_index >= self.total_pdf_pages:
            raise StudyError("atlas page lies outside its declared exact PDF")
        return self


class CoverSlot(Record):
    """One selected source unit, including sources with no verified cover in the retained PDF."""

    unit_id: Identifier
    source_family: Identifier
    issue_id: Identifier
    pdf_sha256: Digest | None
    display_label: str = Field(pattern=r"^[ -~]{1,32}$")
    period_label: str | None = Field(default=None, max_length=120)
    status: CoverStatus
    selected_role: Literal["front-cover", "issue-front-page"] | None = None
    page: PageImage | None
    selection_evidence: ArtifactBinding
    note: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def cover_scope(self) -> CoverSlot:
        """Position alone can never turn an uninspected first page into a cover."""
        if self.status == "verified-cover" and self.page is None:
            raise StudyError("verified cover requires an explicitly selected source page")
        if (self.status == "verified-cover") != (self.selected_role is not None):
            raise StudyError(
                "selected cover/front-page role requires explicit verified source inspection"
            )
        if self.page is not None and (
            self.page.issue_id != self.issue_id or self.page.pdf_sha256 != self.pdf_sha256
        ):
            raise StudyError("cover selection crosses its declared source unit")
        return self


class CoverMosaicPlan(Record):
    """The declared order is retained; metadata chronology is not silently reconciled here."""

    source_frame: ArtifactBinding
    annotation_receipt: ArtifactBinding
    aggregation_runtime: ArtifactBinding
    order_basis: str = Field(min_length=1, max_length=1200)
    declared_source_units: int = Field(ge=1, le=2000)
    slots: tuple[CoverSlot, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def source_membership(self) -> CoverMosaicPlan:
        """Every declared slot appears once, including missing and unverified covers."""
        if len(self.slots) != self.declared_source_units or len(
            {s.unit_id for s in self.slots}
        ) != len(self.slots):
            raise StudyError("cover mosaic source membership is incomplete or repeated")
        if len({s.display_label for s in self.slots}) != len(self.slots):
            raise StudyError("cover mosaic display labels must identify source slots uniquely")
        if len({s.issue_id for s in self.slots}) != len(self.slots):
            raise StudyError("cover mosaic repeats an issue source unit")
        digests = tuple(s.pdf_sha256 for s in self.slots if s.pdf_sha256 is not None)
        if len(set(digests)) != len(digests):
            raise StudyError("cover mosaic PDF aliases require prior source-unit reconciliation")
        ids: dict[str, str] = {}
        pdfs: dict[str, str] = {}
        for slot in self.slots:
            if slot.pdf_sha256 is not None:
                if ids.setdefault(slot.issue_id, slot.pdf_sha256) != slot.pdf_sha256:
                    raise StudyError("cover issue refers to conflicting PDFs")
                if pdfs.setdefault(slot.pdf_sha256, slot.issue_id) != slot.issue_id:
                    raise StudyError("cover PDF aliases require prior reconciliation")
        return self


class PixelSettings(Record):
    """Explicit allocation, interpolation and normalization bounds."""

    width: int = Field(default=128, ge=8, le=512)
    height: int = Field(default=192, ge=8, le=768)
    maximum_canvas_pixels: int = Field(default=196_608, ge=64, le=196_608)
    maximum_source_pixels: int = Field(default=8_000_000, ge=1, le=20_000_000)
    maximum_png_bytes: int = Field(default=16_000_000, ge=1, le=32_000_000)
    interpolation: Literal["Pillow LANCZOS"] = "Pillow LANCZOS"
    background: Literal["white"] = "white"
    placement: Literal["centered isotropic fit; integer dimension rounding"] = (
        "centered isotropic fit; integer dimension rounding"
    )

    @model_validator(mode="after")
    def allocation(self) -> PixelSettings:
        """A wide/long setting does not override the declared allocation bound."""
        if self.width * self.height > self.maximum_canvas_pixels:
            raise StudyError("atlas canvas exceeds its declared pixel capacity")
        return self


class MosaicSettings(Record):
    """Overview and readable detail sheets are separate, explicitly configured derivatives."""

    columns: int = Field(default=16, ge=1, le=24)
    slots_per_sheet: int = Field(default=288, ge=1, le=576)
    tile_width: int = Field(default=96, ge=32, le=512)
    tile_height: int = Field(default=132, ge=32, le=768)
    gutter: int = Field(default=8, ge=2, le=40)
    label_height: int = Field(default=30, ge=20, le=100)
    font_pixels: int = Field(default=12, ge=8, le=48)
    maximum_sheet_pixels: int = Field(default=12_000_000, ge=1000, le=16_000_000)
    maximum_output_bytes: int = Field(default=128_000_000, ge=1000, le=256_000_000)
    source_pixels: PixelSettings = PixelSettings()

    @model_validator(mode="after")
    def tile_capacity(self) -> MosaicSettings:
        """Keep both label lines and the normalized tile inside their explicit capacities."""
        if self.label_height < 2 * self.font_pixels + 4:
            raise StudyError("cover label area cannot contain both declared text lines")
        if self.tile_width * self.tile_height > self.source_pixels.maximum_canvas_pixels:
            raise StudyError("cover tile exceeds its normalized-source pixel capacity")
        return self


class PageTransform(Record):
    """No registration, crop or elastic warp is performed; all rounding is explicit."""

    page_key: str
    source_png_sha256: Digest
    source_width: int
    source_height: int
    canvas_width: int
    canvas_height: int
    placed_box: tuple[int, int, int, int]
    nominal_isotropic_scale: float = Field(gt=0)
    actual_scale_x: float = Field(gt=0)
    actual_scale_y: float = Field(gt=0)
    normalized_rgb_sha256: Digest


@dataclass(frozen=True, slots=True)
class RasterFigure:
    """Actual generated PNG plus relocatable JSON metadata, still awaiting guarded publication."""

    name: str
    png: bytes
    caption: str
    manifest: str
