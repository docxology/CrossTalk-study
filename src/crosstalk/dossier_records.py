"""Parsed inputs and publication receipts for the research dossier."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves the digest field at runtime.
from crosstalk.records import Record

Count = Annotated[int, Field(ge=0)]


class DossierAuthor(Record):
    """Author identity supplied by the project's manuscript metadata."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    orcid: Annotated[str, Field(pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")] | None = None


class YearCount(Record):
    """Catalog metadata count for a year, excluding unresolved date conflicts."""

    year: Annotated[int, Field(ge=1800, le=2200)]
    count: Count


class SourceBinding(Record):
    """Exact project-local source bytes that support the document inputs."""

    path: str
    sha256: Digest


class DossierEvidence(Record):
    """Distinct coverage units; a catalog is not an expected historical census."""

    catalog_records: Count
    catalog_reported_total: Count | None = None
    catalog_capture_matches_reported: bool = False
    downloaded_issues: Count
    analyzed_issues: Count
    pages: Count
    images: Count
    tokens: Count
    unresolved_records: Count
    date_conflicts: Count
    low_text_pages: Count
    year_counts: tuple[YearCount, ...]
    pilot_title: str
    pilot_url: str | None = None
    pilot_sha256: Digest | None = None
    archive_complete: Literal[False] = False


class DossierSection(Record):
    """One readable manuscript section; paragraphs paginate automatically."""

    title: Annotated[str, Field(min_length=1, max_length=150)]
    paragraphs: tuple[str, ...]


class DossierReference(Record):
    """Human-readable source label and its primary-source locator."""

    label: str
    url: str


class DossierMethod(Record):
    """One graphical lane separates implemented descriptors from planned research."""

    name: str
    implemented: str
    planned: str
    validation: str


class DossierFigure(Record):
    """One source-bound original statistical SVG, rendered as a vector figure plate."""

    title: Annotated[str, Field(min_length=1, max_length=120)]
    path: Annotated[str, Field(pattern=r"^output/figures/statistics/[a-z0-9-]+\.svg$")]
    sha256: Digest
    caption: Annotated[str, Field(min_length=1, max_length=900)]


class DossierInput(Record):
    """Complete source-bound dossier input, independent of rendering technology."""

    title: Annotated[str, Field(min_length=1, max_length=100)] = "CrossTalk"
    subtitle: Annotated[str, Field(min_length=1, max_length=240)]
    observed_at: str
    version: str
    authors: Annotated[tuple[DossierAuthor, ...], Field(min_length=1, max_length=6)]
    evidence: DossierEvidence
    sections: tuple[DossierSection, ...]
    references: tuple[DossierReference, ...]
    source_revision: str
    source_bindings: tuple[SourceBinding, ...]
    figures: Annotated[tuple[DossierFigure, ...], Field(max_length=24)] = ()
    methods: Annotated[tuple[DossierMethod, ...], Field(min_length=3, max_length=3)] = (
        DossierMethod(
            name="TEXT",
            implemented="Token counts, lexical diversity, modality proxies and keyword retrieval.",
            planned="Reviewed article topics, semantic change and rhetorical interpretation.",
            validation="OCR and reading-order checks; held-out annotations; length sensitivity.",
        ),
        DossierMethod(
            name="VISUAL",
            implemented="Embedded-image provenance, dimensions, color and grayscale entropy.",
            planned="Figure genres, vector diagrams, layout eras and visual metaphors.",
            validation="Stratified manual labels; mask/vector audit; editorial-genre controls.",
        ),
        DossierMethod(
            name="PAIRED",
            implemented="Physical page and region coordinates connect text and image records.",
            planned="Caption alignment, text-image retrieval and claim-evidence close reading.",
            validation="Region-level gold set; negative pairs; disagreement adjudication.",
        ),
    )


class DossierBuild(Record):
    """Finite verified document artifacts, never a scientific-completeness claim."""

    pdf_path: str
    pages: Annotated[int, Field(ge=4)]
    preview_paths: tuple[str, ...]
    input_sha256: Digest
    pdf_sha256: Digest
    text_boxes: Count
    frontmatter_pages: Literal[4] = 4
    archive_complete: Literal[False] = False
