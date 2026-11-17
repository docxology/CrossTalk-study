"""Optional source-located continuation graphs do not claim unverified page-region ownership."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from crosstalk.study_graphical_records import AbstractBinding  # noqa: TC001 -- Pydantic resolves this field at runtime.
from crosstalk.study_language_records import Digest, Record, StudyError


class ContinuationPage(Record):
    """Physical PDF index and supplied printed label are distinct source observations."""

    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    physical_page_index: int = Field(ge=0, le=499)
    printed_label: str | None = Field(default=None, min_length=1, max_length=20)
    label_basis: Literal["source-text-reference", "visually-verified", "unknown"]
    witness: AbstractBinding
    shared_page_note: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def label_scope(self) -> ContinuationPage:
        """An unknown printed label cannot silently become a physical-index-derived folio."""
        if (self.printed_label is None) != (self.label_basis == "unknown"):
            raise StudyError("continuation printed-label basis disagrees")
        return self


class ContinuationEdge(Record):
    """Reading order and explicit textual continuation markers carry separate evidence labels."""

    source_step: str
    target_step: str
    basis: Literal["explicit-text-marker", "source-reading-sequence"]
    marker: str = Field(min_length=1, max_length=110)
    witness: AbstractBinding


class ContinuationWitness(Record):
    """An admitted textual example; visual regions remain explicitly outside the source claim."""

    issue_id: str = Field(min_length=1, max_length=120)
    article_label: str = Field(min_length=1, max_length=140)
    pdf_sha256: Digest
    pdf_source: AbstractBinding
    pages: tuple[ContinuationPage, ...] = Field(min_length=2, max_length=5)
    edges: tuple[ContinuationEdge, ...] = Field(min_length=1, max_length=4)
    evidence_scope: Literal["source-located-text-only"] = "source-located-text-only"
    page_region_ownership_verified: Literal[False] = False

    @model_validator(mode="after")
    def graph_identity(self) -> ContinuationWitness:
        """Refuse missing/ambiguous nodes, self-edges and unsupported disconnected witness pages."""
        ids = {page.step_id for page in self.pages}
        physical = {page.physical_page_index for page in self.pages}
        pairs = {(edge.source_step, edge.target_step) for edge in self.edges}
        used = {step for edge in self.edges for step in (edge.source_step, edge.target_step)}
        if (
            len(ids) != len(self.pages)
            or len(physical) != len(self.pages)
            or len(pairs) != len(self.edges)
            or used != ids
            or any(edge.source_step == edge.target_step for edge in self.edges)
            or self.pdf_source.sha256 != self.pdf_sha256
        ):
            raise StudyError("continuation graph source identities disagree")
        reached = {self.pages[0].step_id}
        for _ in self.pages:
            for edge in self.edges:
                if edge.source_step in reached or edge.target_step in reached:
                    reached.update((edge.source_step, edge.target_step))
        if reached != ids:
            raise StudyError("continuation witness graph is disconnected")
        return self
