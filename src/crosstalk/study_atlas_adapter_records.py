"""Keep separate page measurement, thumbnail and native-layout identities."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from crosstalk.appearance_batch_records import AppearanceArtifact  # noqa: TC001 -- Pydantic resolves these fields at runtime.
from crosstalk.appearance_context import appearance_key
from crosstalk.atlas_records import ArtifactBinding, PageImage  # noqa: TC001 -- Pydantic resolves these fields at runtime.
from crosstalk.study_language_records import Digest, Record, StudyError
from crosstalk.study_layout_records import PageLayout  # noqa: TC001 -- Pydantic resolves these fields at runtime.


class AtlasUnit(Record):
    """One explicitly declared source-distinct PDF, never an inferred historical issue slot."""

    unit_id: str
    issue_id: str
    pdf: ArtifactBinding
    physical_pages: int = Field(ge=1, le=1000)
    source_family: Literal["nps-current-catalog"] = "nps-current-catalog"
    catalog_label: str
    issued_metadata: str | None


class AcceptedAppearance(Record):
    """Full-render descriptors and optional accepted thumbnail pixels have different units."""

    artifact: AppearanceArtifact
    record_binding: ArtifactBinding
    image: PageImage | None
    pixel_unavailable_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def matching_pixels(self) -> AcceptedAppearance:
        """A page-context key is not a shared rendering epoch; use the complete engine digest."""
        page, engine = self.artifact.page, self.artifact.engine
        epoch = hashlib.sha256(engine.model_dump_json().encode()).hexdigest()
        if self.artifact.cache_key != appearance_key(
            page.source_pdf_sha256, page.page_index, engine
        ):
            raise StudyError("accepted appearance cache identity disagrees with PDF/page/engine")
        if (self.image is None) != (self.pixel_unavailable_reason is not None):
            raise StudyError("accepted descriptor needs explicit thumbnail availability")
        if self.image is not None and (
            self.image.pdf_sha256 != page.source_pdf_sha256
            or self.image.page_index != page.page_index
            or self.image.total_pdf_pages != page.total_pdf_pages
            or self.image.source_evidence != self.record_binding
            or self.image.image.sha256 != page.thumbnail_sha256
            or self.image.rendering_identity != epoch
            or self.image.image_basis != "accepted-appearance-thumbnail"
            or (self.image.width, self.image.height)
            != (page.thumbnail_width, page.thumbnail_height)
        ):
            raise StudyError(
                "accepted thumbnail differs from full-render record or shared " + "engine epoch"
            )
        return self


class BoundLayout(Record):
    """Native metadata has its own method and missingness; no-native fonts stay unavailable."""

    record: PageLayout
    source: ArtifactBinding


class AtlasPageSlot(Record):
    """Every declared physical page survives refusal, failure or absence of visual evidence."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    status: Literal["measured", "missing", "refused", "failed", "unattempted"]
    reason: str = Field(min_length=1, max_length=500)
    appearance: AcceptedAppearance | None
    layout: BoundLayout | None
    layout_unavailable_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def page_key(self) -> str:
        """Use physical identity rather than folios, aliases or image hashes."""
        return f"{self.pdf_sha256}:{self.page_index}"

    @model_validator(mode="after")
    def evidence_scope(self) -> AtlasPageSlot:
        """Presence, identity and an observed native-zero set cannot contradict their status."""
        if (self.status == "measured") != (self.appearance is not None):
            raise StudyError(
                "appearance status differs from actual measured descriptor availability"
            )
        if (self.layout is None) != (self.layout_unavailable_reason is not None):
            raise StudyError("native-layout missingness needs an explicit reason")
        if self.appearance is not None:
            page = self.appearance.artifact.page
            if (page.source_pdf_sha256, page.page_index) != (self.pdf_sha256, self.page_index):
                raise StudyError("appearance evidence crosses physical page identity")
            if (
                self.appearance.image is not None
                and self.appearance.image.issue_id != self.issue_id
            ):
                raise StudyError("appearance thumbnail crosses issue identity")
        if self.layout is not None and (
            self.layout.record.pdf_sha256,
            self.layout.record.page_index,
        ) != (self.pdf_sha256, self.page_index):
            raise StudyError("layout evidence crosses physical page identity")
        return self


class AtlasInputFrame(Record):
    """Require a complete physical frame; the caller owns live file/source admission."""

    receipt: ArtifactBinding
    appearance_projection: ArtifactBinding
    rendering_identity: Digest
    layout_reconciliation: ArtifactBinding
    units: tuple[AtlasUnit, ...] = Field(min_length=1, max_length=2000)
    pages: tuple[AtlasPageSlot, ...] = Field(min_length=1, max_length=30_000)

    @model_validator(mode="after")
    def exact_frame(self) -> AtlasInputFrame:
        """Retain each physical page once; require prior alias reconciliation."""
        issues = {unit.issue_id: unit for unit in self.units}
        if (
            len(issues) != len(self.units)
            or len({unit.pdf.sha256 for unit in self.units}) != len(self.units)
            or len({unit.unit_id for unit in self.units}) != len(self.units)
        ):
            raise StudyError("atlas input issue/PDF identities repeat or alias")
        expected = {
            (unit.pdf.sha256, index) for unit in self.units for index in range(unit.physical_pages)
        }
        actual = {(page.pdf_sha256, page.page_index) for page in self.pages}
        if actual != expected or len(actual) != len(self.pages):
            raise StudyError("atlas input omits or repeats a declared physical page")
        layout_methods: set[str] = set()
        for slot in self.pages:
            unit = issues.get(slot.issue_id)
            if unit is None or unit.pdf.sha256 != slot.pdf_sha256:
                raise StudyError("atlas page and declared issue/PDF disagree")
            if slot.appearance is not None:
                item = slot.appearance
                epoch = hashlib.sha256(item.artifact.engine.model_dump_json().encode()).hexdigest()
                if (
                    epoch != self.rendering_identity
                    or item.artifact.page.total_pdf_pages != unit.physical_pages
                ):
                    raise StudyError("atlas frame mixes rendering epochs or PDF page counts")
                if item.image is not None and item.image.source_pdf != unit.pdf:
                    raise StudyError("atlas image uses another source PDF locator")
            if slot.layout is not None:
                layout_methods.add(slot.layout.record.implementation_sha256)
        if len(layout_methods) > 1:
            raise StudyError("native-layout metadata mixes measurement methods")
        return self
