"""Cover selection is an explicit source observation, separate from PDF completeness."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from crosstalk.article_records import ArticleError, ArticleRecord, Digest

CoverStatus = Literal[
    "verified-cover",
    "candidate-first-retained-page",
    "not-located-in-inspected-pdf",
    "unavailable",
]
CoverRole = Literal["front-cover", "issue-front-page"]


class CoverBinding(ArticleRecord):
    """The caller independently admits this exact relocatable artifact before use."""

    path: str = Field(min_length=1, max_length=1200)
    sha256: Digest

    @model_validator(mode="after")
    def local_path(self) -> CoverBinding:
        """Paths identify local evidence; they cannot widen the reader's file scope."""
        path = PurePosixPath(self.path)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.path
            or path.as_posix() != self.path
        ):
            raise ArticleError("cover evidence needs an ordinary project-relative POSIX path")
        return self


class CoverUnit(ArticleRecord):
    """One declared source-distinct PDF; dates and source family remain observations."""

    unit_id: str = Field(min_length=1, max_length=160)
    source_family: str = Field(min_length=1, max_length=80)
    issue_id: str = Field(min_length=1, max_length=120)
    pdf_sha256: Digest
    physical_pages: int = Field(ge=1, le=1000)
    display_label: str = Field(min_length=1, max_length=160)
    issued_observed: str | None = Field(default=None, max_length=80)
    catalog_evidence: CoverBinding


class WrapperExclusion(ArticleRecord):
    """An independently admitted wrapper decision must still match the actual native page."""

    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    native_artifact: CoverBinding
    page_text_sha256: Digest
    decision_evidence: CoverBinding


class CoverPageRender(ArticleRecord):
    """Source pixels have their own page/render identity, independent of native text."""

    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    image: CoverBinding
    render_identity: Digest
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_basis: Literal["full-render", "thumbnail"]


class CoverAssessment(ArticleRecord):
    """Authored visual selection; a recorded decision is not an agreement estimate."""

    unit_id: str
    pdf_sha256: Digest
    status: Literal["verified-cover", "not-located-in-inspected-pdf", "unavailable"]
    selected_page_index: int | None = Field(default=None, ge=0)
    selected_role: CoverRole | None = None
    inspected_page_indices: tuple[int, ...] = Field(max_length=1000)
    render_evidence: tuple[CoverPageRender, ...] = Field(max_length=1000)
    decision_evidence: CoverBinding
    reviewer: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=10, max_length=1200)
    independent_human_validation: Literal[False] = False
    verification_scope: Literal["source-image-selection-only"] = "source-image-selection-only"

    @model_validator(mode="after")
    def selection(self) -> CoverAssessment:
        """A selected cover needs an explicit page; other decisions select no image."""
        if (self.selected_page_index is not None) != (self.status == "verified-cover"):
            raise ArticleError("cover status and selected image disagree")
        if (self.selected_role is not None) != (self.status == "verified-cover"):
            raise ArticleError("cover selection must distinguish front cover from issue front page")
        if len(set(self.inspected_page_indices)) != len(self.inspected_page_indices):
            raise ArticleError("cover inspection repeats a physical page")
        if any(index < 0 for index in self.inspected_page_indices):
            raise ArticleError("cover inspection has a negative physical index")
        return self


class CoverDecision(ArticleRecord):
    """Every declared source retains a slot, including unresolved and absent cover selections."""

    unit: CoverUnit
    status: CoverStatus
    candidate_page_indices: tuple[int, ...]
    selected_page_index: int | None
    selected_role: CoverRole | None = None
    native_scope_complete: bool
    excluded_wrapper_indices: tuple[int, ...]
    evidence: tuple[CoverBinding, ...]
    selected_render: CoverPageRender | None = None
    note: str
    historical_issue_coverage_inferred: Literal[False] = False
    independent_human_validation: Literal[False] = False

    @model_validator(mode="after")
    def consistent_selection(self) -> CoverDecision:
        """Selection identity cannot change while its source slot keeps a verified label."""
        selected = self.selected_page_index
        if (selected is not None) != (self.status == "verified-cover"):
            raise ArticleError("cover decision status and selected physical page disagree")
        if (self.selected_role is not None) != (selected is not None):
            raise ArticleError(
                "cover decision must retain its selected front-cover/front-page role"
            )
        if (self.selected_render is not None) != (selected is not None):
            raise ArticleError("cover decision needs exactly its selected source render")
        for indices in (self.candidate_page_indices, self.excluded_wrapper_indices):
            if len(set(indices)) != len(indices) or any(
                not 0 <= i < self.unit.physical_pages for i in indices
            ):
                raise ArticleError("cover decision has duplicate or out-of-frame page indices")
        if self.selected_render is not None and (
            self.selected_render.pdf_sha256 != self.unit.pdf_sha256
            or self.selected_render.page_index != selected
            or selected in self.excluded_wrapper_indices
            or selected is None
            or not 0 <= selected < self.unit.physical_pages
        ):
            raise ArticleError("cover decision source render differs from its selected PDF page")
        return self
