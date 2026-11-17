"""Bounded all-term search refuses stale source and retrieval caches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.index_observe import IndexReader
from crosstalk.index_read import current_corpus_index
from crosstalk.lexicon import TOKEN
from crosstalk.models import AcquisitionError
from crosstalk.search_records import SearchResult, TextIndexSummary
from crosstalk.text_index import implementation_digest
from crosstalk.text_store import query_page_database

if TYPE_CHECKING:
    from pathlib import Path


def search_pages(root: Path, query: str, limit: int = 20) -> SearchResult:
    """Treat input as literal word terms, without accepting SQL or FTS operators."""
    if len(query) > 1000 or not 1 <= limit <= 100:
        raise AcquisitionError("search query or result limit exceeds its bound")
    terms = tuple(dict.fromkeys(match.group() for match in TOKEN.finditer(query)))
    if not 1 <= len(terms) <= 16:
        raise AcquisitionError("search requires between 1 and 16 distinct word terms")
    expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with current_corpus_index(root):
        reader = IndexReader(root.absolute())
        summary = TextIndexSummary.model_validate_json(
            reader.read("data/processed/index/page-search.jsonl")
        )
        if summary.implementation_sha256 != implementation_digest():
            raise AcquisitionError("page-search implementation changed; rebuild required")
        if (
            reader.digest("data/processed/index/corpus-index.jsonl").sha256
            != summary.corpus_index_sha256
        ):
            raise AcquisitionError("corpus index changed; rebuild page search")
        for binding in summary.source_bindings:
            if reader.digest(binding.path).sha256 != binding.sha256:
                raise AcquisitionError("page-search input changed; rebuild required")
        if reader.digest(summary.database_path).sha256 != summary.database_sha256:
            raise AcquisitionError("page-search database digest mismatch; rebuild required")
        if not summary.fts5_available:
            raise AcquisitionError(
                "SQLite FTS5 is unavailable; page content remains indexed but search cannot run"
            )
        count, hits = query_page_database(reader.path(summary.database_path), expression, limit)
        reader.recheck()
        return SearchResult(
            query=query,
            query_terms=terms,
            indexed_pages=summary.indexed_pages,
            total_matching_pages=count,
            hits=hits,
            index_sha256=summary.database_sha256,
        )
