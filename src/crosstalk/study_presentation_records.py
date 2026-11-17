"""Conservative presentation admission separates node attributes from required rendered-pixel QA."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from crosstalk.study_language_records import Digest, Record, StudyError


class FigureCaption(Record):
    """What is shown, its unit and eligibility/exclusions, then one bounded takeaway."""

    shown: str = Field(min_length=1, max_length=260)
    unit: str = Field(min_length=1, max_length=120)
    eligibility: str = Field(min_length=1, max_length=260)
    takeaway: str = Field(min_length=1, max_length=220)

    @property
    def complete(self) -> str:
        """Keep the complete supplied caption, without implicit scientific reinterpretation."""
        return " ".join((self.shown, "Unit: " + self.unit + ".", self.eligibility, self.takeaway))


class PlotChannel(Record):
    """One explicitly declared categorical data channel; continuous/diverging scales need redraw."""

    channel: str = Field(min_length=1, max_length=80)
    source_paint: str = Field(min_length=1, max_length=60)
    tone: Literal["black", "gray"]
    legend_text: str = Field(min_length=1, max_length=100)


class RedFocus(Record):
    """Red selects one named declared data channel, never an inferred failure/danger category."""

    source_paint: str = Field(min_length=1, max_length=60)
    channel: str = Field(min_length=1, max_length=80)


class LegendArea(Record):
    """A caller-declared reserved rectangle in the source SVG viewBox coordinate system."""

    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class LegendWord(Record):
    """An approved color-word substitution retains all noncolor words, punctuation and numbers."""

    old_word: Literal[
        "Teal", "Coral", "Pale", "Blue", "Green", "Orange", "Purple", "Navy", "Red", "Black", "Gray"
    ]
    occurrence: int = Field(default=0, ge=0)
    channel: str = Field(min_length=1, max_length=80)


class LegendEdit(Record):
    """Bind an exact before/after annotation and its indexed source text node."""

    text_node_index: int = Field(ge=0)
    original_text: str = Field(min_length=1, max_length=1500)
    original_text_sha256: Digest
    expected_text: str = Field(min_length=1, max_length=1500)
    replacements: tuple[LegendWord, ...] = Field(min_length=1, max_length=8)
    role: Literal["color-legend"] = "color-legend"


class SvgPresentation(Record):
    """Admit declared discrete data roles on a light opaque canvas."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    source_svg_sha256: Digest
    source_measurement_identity: str = Field(min_length=1, max_length=240)
    source_kind: Literal["research-plot"] = "research-plot"
    encoding: Literal["single-channel", "categorical"]
    text_color_semantics: Literal["not-a-data-channel"]
    channels: tuple[PlotChannel, ...] = Field(min_length=1, max_length=3)
    decorative_strokes: tuple[str, ...] = Field(default=(), max_length=12)
    inherited_caption: str = Field(min_length=1, max_length=2000)
    caption: FigureCaption
    red_focus: RedFocus | None = None
    legend_area: LegendArea | None = None
    annotation_edits: tuple[LegendEdit, ...] = Field(default=(), max_length=40)
    font_policy: Literal["preserve"] = "preserve"
    target_print_width_points: float = Field(default=561.6, ge=100, le=720)
    minimum_print_font_points: float = Field(default=8.0, ge=7.5, le=24)
    render_dpi: Literal[144] = 144
    maximum_render_pixels: int = Field(default=8_000_000, ge=1, le=8_000_000)
    maximum_source_bytes: int = Field(default=16_000_000, ge=1, le=32_000_000)
    maximum_elements: int = Field(default=50_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def coherent_request(self) -> SvgPresentation:
        """Require unique role/annotation identities and a reserved red legend area."""
        names = tuple(channel.channel for channel in self.channels)
        if len(names) != len(set(names)) or (self.encoding == "single-channel" and len(names) != 1):
            raise StudyError("presentation channel identities disagree")
        if (self.red_focus is None) != (self.legend_area is None):
            raise StudyError("red requires a declared reserved legend area")
        if self.red_focus is not None and self.red_focus.channel not in names:
            raise StudyError("red focus is outside declared source channels")
        if len({edit.text_node_index for edit in self.annotation_edits}) != len(
            self.annotation_edits
        ):
            raise StudyError("approved annotation locations are repeated")
        return self


class NativeRenderObservation(Record):
    """Actual144dpi RGB sample identity; parser text boxes are separately named, not called ink."""

    svg_sha256: Digest
    pdf_sha256: Digest
    rgb_matrix_sha256: Digest
    png_sha256: Digest
    width_pixels: int = Field(gt=0)
    height_pixels: int = Field(gt=0)
    dpi: Literal[144] = 144
    text_spans: int = Field(ge=0)
    minimum_print_font_points: float | None


class PresentationReceipt(Record):
    """Separate approved node edits from actual source/presented render observations."""

    method_version: Literal["study-presentation-2"] = "study-presentation-2"
    implementation_sha256: Digest
    source_svg_sha256: Digest
    source_measurement_identity: str
    original_attribute_text_sha256: Digest
    approved_attribute_text_sha256: Digest
    presented_attribute_text_sha256: Digest
    attribute_projection_scope: Literal["original-nodes-after-approved-color-word-edits"] = (
        "original-nodes-after-approved-color-word-edits"
    )
    channel_mapping: tuple[tuple[str, str, str], ...]
    red_channel: str | None
    annotation_edits: tuple[LegendEdit, ...]
    source_render: NativeRenderObservation
    presented_render: NativeRenderObservation
    source_legend_pixels_different_from_canvas: int | None = Field(ge=0)
    native_runtime_identity: Digest
    measurement_recomputed: Literal[False] = False
    evidence_images_processed: Literal[False] = False
    original_svg_bytes_modified: Literal[False] = False

    @model_validator(mode="after")
    def unchanged_data(self) -> PresentationReceipt:
        """Only approved annotations may differ; red has an actually sampled blank source area."""
        if self.approved_attribute_text_sha256 != self.presented_attribute_text_sha256:
            raise StudyError("presentation changed unapproved node attributes/text")
        if self.red_channel is not None and self.source_legend_pixels_different_from_canvas != 0:
            raise StudyError("red legend lacks a clear bound source render")
        return self
