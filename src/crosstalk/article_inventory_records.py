"""Typed per-issue discovery results keep observations distinct from unique article units."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from crosstalk.article_evidence import EvidenceCard  # noqa: TC001 -- Pydantic resolves this field at runtime.
from crosstalk.article_records import ArticleObservation, ArticleRecord, Digest
from crosstalk.study_layout_records import PageLayout  # noqa: TC001 -- Pydantic resolves this field at runtime.


class LayoutEvidence(ArticleRecord):
    """One parsed native layout page and the exact artifact containing its original bytes."""

    artifact_sha256: Digest
    page: PageLayout


class IssueDiscovery(ArticleRecord):
    """A discovery queue with explicit unresolved coverage, never an article census."""

    issue_id: str
    pdf_sha256: Digest
    physical_pages: int = Field(ge=1)
    native_pages: int = Field(ge=0)
    ocr_pages: int = Field(ge=0)
    layout_pages: int = Field(ge=0)
    status: Literal["provisional-observations", "no-entry-detected-unresolved"]
    observations: tuple[ArticleObservation, ...]
    cards: tuple[EvidenceCard, ...]
    corroborated_observations: int = Field(ge=0)
    unique_physical_starts: int = Field(ge=0)
    unique_layer_starts: int = Field(ge=0)
    exact_passages_checked: int = Field(ge=0)
    article_census_complete: Literal[False] = False
    semantic_review_complete: Literal[False] = False
    boundary_accuracy_measured: Literal[False] = False
    scope: str = (
        "Text-row and calibrated native-font candidates are preserved as separate views. "
        + "Repeated headings or cross-layer matches remain unresolved. Counts of observations "
        + "and unique physical/layer starts use distinct denominators. Departments remain "
        + "available for genre review. Candidate windows do not certify article ownership."
    )
