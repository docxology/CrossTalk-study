"""Typed observations for four abstracts; the caller owns source custody."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from crosstalk.study_language_records import Digest, Record, StudyError


class AbstractBinding(Record):
    """Retained input identity; authoring never invents current results."""

    path: str = Field(min_length=1, max_length=1200)
    sha256: Digest

    @model_validator(mode="after")
    def local_path(self) -> AbstractBinding:
        """Keep scientific provenance relocatable without admitting traversal paths."""
        parsed = PurePosixPath(self.path)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or "\\" in self.path
            or not parsed.parts
            or parsed.as_posix() != self.path
        ):
            raise StudyError("graphical input binding must be a project-local POSIX path")
        return self


class HistogramBin(Record):
    """One disclosed bin, retaining its exact source-unit count."""

    label: str = Field(min_length=1, max_length=14)
    count: int = Field(ge=0)


class AbstractHistogram(Record):
    """A finite distribution with unavailable units outside the eligible denominator."""

    title: str = Field(min_length=1, max_length=42)
    unit: str = Field(min_length=1, max_length=24)
    bins: tuple[HistogramBin, ...] = Field(min_length=1, max_length=10)
    eligible_units: int = Field(ge=0)
    unavailable_units: int = Field(ge=0)
    total_units: int = Field(ge=0)
    basis: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def denominator(self) -> AbstractHistogram:
        """A histogram cannot silently lose values or count missing measurements as zero."""
        if (
            sum(row.count for row in self.bins) != self.eligible_units
            or self.eligible_units + self.unavailable_units != self.total_units
            or len({row.label for row in self.bins}) != len(self.bins)
        ):
            raise StudyError("graphical histogram bins and denominators disagree")
        return self


class CatalogYear(Record):
    """Catalog-issued year label; printed chronology remains independently unverified."""

    year: int = Field(ge=1400, le=2200)
    rows: int = Field(ge=0)


class CorpusScope(Record):
    """Current captured NPS and separate publisher families, with an unknown historical census."""

    captured_catalog_rows: int = Field(ge=0)
    verified_pdf_sources: int = Field(ge=0)
    physical_pages: int = Field(ge=0)
    current_native_pages: int = Field(ge=0)
    catalog_years: tuple[CatalogYear, ...] = Field(max_length=200)
    undated_catalog_rows: int = Field(ge=0)
    historical_findings: tuple[str, ...] = Field(default=(), max_length=3)
    historical_expected_issues: None = None
    publisher_cards: int = Field(ge=0)
    publisher_public_candidates: int = Field(ge=0)
    publisher_contact_only: int = Field(ge=0)
    publisher_verified_pdfs: int = Field(ge=0)
    publisher_note: str = Field(min_length=1, max_length=180)

    @model_validator(mode="after")
    def frame(self) -> CorpusScope:
        """Keep families/date missingness explicit and reject contradictory source counts."""
        years = tuple(row.year for row in self.catalog_years)
        if (
            sum(row.rows for row in self.catalog_years) + self.undated_catalog_rows
            != self.captured_catalog_rows
            or years != tuple(sorted(set(years)))
            or (years and max(years) - min(years) > 200)
            or self.verified_pdf_sources > self.captured_catalog_rows
            or self.physical_pages < self.verified_pdf_sources
            or self.current_native_pages > self.physical_pages
            or self.publisher_public_candidates + self.publisher_contact_only
            != self.publisher_cards
            or self.publisher_verified_pdfs > self.publisher_public_candidates
        ):
            raise StudyError("graphical corpus source-family/date counts disagree")
        return self


class LayerScope(Record):
    """One observed text layer; OCR-empty status differs from normalized zero-token text."""

    layer: Literal["native", "ocr"]
    supplied_units: int = Field(ge=0)
    tokens: int = Field(ge=0)
    observed_issues: int = Field(ge=0)
    positive_token_issues: int = Field(ge=0)
    zero_token_units: int = Field(ge=0)
    diversity: AbstractHistogram

    @model_validator(mode="after")
    def scope(self) -> LayerScope:
        """Unit-level diversity and zero-token counts belong to this exact layer frame."""
        if (
            self.positive_token_issues > self.observed_issues
            or self.zero_token_units > self.supplied_units
            or self.observed_issues > self.supplied_units
            or self.positive_token_issues > self.supplied_units - self.zero_token_units
            or self.tokens < self.supplied_units - self.zero_token_units
            or bool(self.tokens) != bool(self.positive_token_issues)
            or self.diversity.total_units != self.supplied_units
        ):
            raise StudyError("graphical text-layer denominators disagree")
        return self


class OCRWorkload(Record):
    """Targeting/operational outcomes never establish transcription accuracy."""

    total_physical_pages: int = Field(ge=0)
    targeted_pages: int = Field(ge=0)
    produced_pages: int = Field(ge=0)
    accepted_empty_pages: int = Field(ge=0)
    failed_pages: int = Field(ge=0)
    untargeted_pages: int = Field(ge=0)

    @model_validator(mode="after")
    def outcomes(self) -> OCRWorkload:
        """Every target is accounted once; untargeted originals remain outside the OCR cohort."""
        if (
            self.produced_pages + self.accepted_empty_pages + self.failed_pages
            != self.targeted_pages
            or self.targeted_pages + self.untargeted_pages != self.total_physical_pages
        ):
            raise StudyError("graphical OCR outcome counts disagree")
        return self


class NativeViewScope(Record):
    """Physical-page exclusion/subsets only; transformed text needs a different explicit model."""

    label: str = Field(min_length=1, max_length=34)
    units: int = Field(ge=0)
    tokens: int = Field(ge=0)
    positive_token_issues: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent_counts(self) -> NativeViewScope:
        """Positive-token issues need positive pages/tokens; an all-tokenless view is allowed."""
        if (
            self.positive_token_issues > self.units
            or self.tokens < self.positive_token_issues
            or bool(self.tokens) != bool(self.positive_token_issues)
        ):
            raise StudyError("graphical native view counts disagree")
        return self


class LanguageScope(Record):
    """Layer-separated raw distributions and explicitly supplied native sensitivity rows."""

    native: LayerScope
    ocr: LayerScope
    ocr_workload: OCRWorkload
    native_views: tuple[NativeViewScope, ...] = Field(default=(), max_length=3)
    normalization_note: str = Field(min_length=1, max_length=180)


class DescriptorCoverage(Record):
    """Mutually exclusive operational states within one declared physical-page frame."""

    total_pages: int = Field(ge=0)
    measured_pages: int = Field(ge=0)
    refused_pages: int = Field(ge=0)
    failed_pages: int = Field(ge=0)
    unattempted_pages: int = Field(ge=0)

    @model_validator(mode="after")
    def partition(self) -> DescriptorCoverage:
        """Unknown/missing receipts must be refused by the caller rather than relabelled unseen."""
        if (
            self.measured_pages + self.refused_pages + self.failed_pages + self.unattempted_pages
            != self.total_pages
        ):
            raise StudyError("graphical descriptor coverage does not partition its source frame")
        return self


class VisualScope(Record):
    """Whole-page appearance and reported native typography use independent measurement cohorts."""

    appearance: DescriptorCoverage
    layout: DescriptorCoverage
    native_span_pages: int = Field(ge=0)
    no_native_span_pages: int = Field(ge=0)
    native_union_refused_pages: int = Field(ge=0)
    appearance_entropy: AbstractHistogram
    reported_font_size: AbstractHistogram
    native_union_fraction: AbstractHistogram
    interpretation_note: str = Field(min_length=1, max_length=180)

    @model_validator(mode="after")
    def descriptor_frames(self) -> VisualScope:
        """Native typography absence remains separate from visible printed content."""
        if (
            self.native_span_pages + self.no_native_span_pages != self.layout.measured_pages
            or self.native_union_refused_pages > self.native_span_pages
            or self.appearance_entropy.total_units != self.appearance.total_pages
            or self.appearance_entropy.eligible_units != self.appearance.measured_pages
            or self.reported_font_size.total_units != self.layout.measured_pages
            or self.reported_font_size.eligible_units != self.native_span_pages
            or self.native_union_fraction.total_units != self.layout.measured_pages
            or self.native_union_fraction.eligible_units
            != self.layout.measured_pages - self.native_union_refused_pages
        ):
            raise StudyError("graphical visual descriptor cohorts disagree")
        return self


class EvidenceStage(Record):
    """Discovery entries, page/region witnesses and appraised articles retain explicit units."""

    label: str = Field(min_length=1, max_length=34)
    count: int | None = Field(ge=0)
    unit: str = Field(min_length=1, max_length=20)
    qualification: str = Field(min_length=1, max_length=70)


class SelectedReading(Record):
    """A bounded source-checked appraisal example, never a validated article census."""

    title: str = Field(min_length=1, max_length=140)
    source_locator: str = Field(min_length=1, max_length=80)
    evidence_note: str = Field(min_length=1, max_length=110)
    limitation_note: str = Field(min_length=1, max_length=110)


class LiteratureScope(Record):
    """Actual review progress and its unresolved extent; no unmeasured human agreement."""

    stages: tuple[EvidenceStage, ...] = Field(min_length=2, max_length=6)
    selected_readings: tuple[SelectedReading, ...] = Field(default=(), max_length=20)
    scope_note: str = Field(min_length=1, max_length=200)
    article_census_status: Literal["provisional-not-validated-census"] = (
        "provisional-not-validated-census"
    )
    human_agreement_status: Literal["not-measured"] = "not-measured"


class AbstractInputs(Record):
    """Immutable supplied observations; actual source admission remains external."""

    observed_at: str = Field(min_length=10, max_length=40)
    corpus: CorpusScope
    language: LanguageScope
    visual: VisualScope
    literature: LiteratureScope
    bindings: tuple[AbstractBinding, ...] = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def shared_frames(self) -> AbstractInputs:
        """Shared physical scope is explicit without pooling overlapping text layers."""
        if (
            self.language.native.layer != "native"
            or self.language.ocr.layer != "ocr"
            or self.language.native.supplied_units != self.corpus.current_native_pages
            or self.language.native.observed_issues > self.corpus.verified_pdf_sources
            or self.language.ocr.observed_issues > self.language.native.observed_issues
            or self.language.ocr.supplied_units
            != self.language.ocr_workload.produced_pages
            + self.language.ocr_workload.accepted_empty_pages
            or self.language.ocr_workload.total_physical_pages != self.corpus.physical_pages
            or self.visual.appearance.total_pages != self.corpus.physical_pages
            or self.visual.layout.total_pages != self.corpus.physical_pages
            or len({view.label for view in self.language.native_views})
            != len(self.language.native_views)
            or any(
                view.units > self.language.native.supplied_units
                or view.tokens > self.language.native.tokens
                or view.positive_token_issues > self.language.native.positive_token_issues
                or view.positive_token_issues > self.language.native.observed_issues
                for view in self.language.native_views
            )
            or len({row.path for row in self.bindings}) != len(self.bindings)
        ):
            raise StudyError("graphical source frames or provenance membership disagree")
        return self
