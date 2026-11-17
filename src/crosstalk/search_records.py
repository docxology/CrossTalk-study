"""Typed full-text cache custody and source-grounded search results."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from crosstalk.index_records import IndexBinding  # noqa: TC001 -- Pydantic resolves nested records.
from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves digest fields at runtime.
from crosstalk.records import Record


class IndexedPage(Record):
    """A searchable physical page, never an inferred article."""

    issue_id: str
    title: str
    source_url: str
    source_sha256: Digest
    page_index: Annotated[int, Field(ge=0)]
    page_label: str
    text: str


class TextIndexSummary(Record):
    """Content identities and exact scope of one rebuildable local search cache."""

    schema_version: Literal[1] = 1
    database_path: Literal["data/processed/index/page-search.sqlite"] = (
        "data/processed/index/page-search.sqlite"
    )
    database_sha256: Digest
    corpus_index_sha256: Digest
    implementation_sha256: Digest
    source_bindings: tuple[IndexBinding, ...]
    indexed_issues: Annotated[int, Field(ge=0)]
    indexed_pages: Annotated[int, Field(ge=0)]
    skipped_issue_ids: tuple[str, ...]
    fts5_available: bool
    tokenizer: str = "FTS5 unicode61 remove_diacritics 0; retrieval, not linguistic measurement"
    archive_complete: Literal[False] = False


class SearchHit(Record):
    """One matching PDF page with its original source locator and byte identity."""

    issue_id: str
    title: str
    source_url: str
    source_sha256: Digest
    page_index: Annotated[int, Field(ge=0)]
    page_label: str
    excerpt: str


class SearchResult(Record):
    """Bounded all-term retrieval on the current source-verified page index."""

    query: str
    query_terms: tuple[str, ...]
    indexed_pages: Annotated[int, Field(ge=0)]
    total_matching_pages: Annotated[int, Field(ge=0)]
    hits: tuple[SearchHit, ...]
    index_sha256: Digest
    scope: str = "Indexed source-verified extracted pages only; no article or archive census"
