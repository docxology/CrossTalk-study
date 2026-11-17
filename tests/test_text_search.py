"""Real SQLite page retrieval and idempotent source-custody regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pymupdf
import pytest

from crosstalk.acquisition_lock import project_lock
from crosstalk.corpus_index import build_corpus_index
from crosstalk.extract import extract_corpus
from crosstalk.models import AcquisitionError, file_digest
from crosstalk.records import write_records
from crosstalk.text_index import build_text_index
from crosstalk.text_search import search_pages
from tests.test_analysis import make_pdf
from tests.test_corpus_index import catalog_at, register_pdf

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def searchable(tmp_path: Path) -> Path:
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    source = tmp_path / "data/raw/pdf" / f"{ids[0]}.pdf"
    make_pdf(source, ("Software security assurance.", "Software reliability testing."))
    issue = issue.model_copy(update={"sha256": file_digest(source)})
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    _ = build_corpus_index(tmp_path)
    return tmp_path


def test_page_search_returns_bounded_source_grounded_hits(searchable: Path) -> None:
    # Given two verified pages and two unresolved catalog peers.
    summary = build_text_index(searchable)
    # When querying through actual SQLite FTS5.
    if not summary.fts5_available:
        with pytest.raises(AcquisitionError, match="FTS5"):
            search_pages(searchable, "software")
        return
    result = search_pages(searchable, "software", limit=1)
    # Then result limits do not change the matching-page denominator or provenance.
    assert summary.indexed_pages == 2
    assert summary.indexed_issues == 1
    assert len(summary.skipped_issue_ids) == 2
    assert result.total_matching_pages == 2
    assert len(result.hits) == 1
    assert result.hits[0].source_sha256 == file_digest(
        next((searchable / "data/raw/pdf").glob("*.pdf"))
    )


def test_all_terms_must_match_the_same_page(searchable: Path) -> None:
    # Given words distributed across separate physical pages.
    summary = build_text_index(searchable)
    if not summary.fts5_available:
        return
    # When asking for words that never co-occur on one page.
    result = search_pages(searchable, "security reliability")
    # Then issue-level co-occurrence is not falsely reported as a page hit.
    assert result.total_matching_pages == 0
    assert result.hits == ()


def test_query_operators_are_literal_words(searchable: Path) -> None:
    # Given a current page index.
    summary = build_text_index(searchable)
    if not summary.fts5_available:
        return
    # When the user includes text resembling an FTS operator.
    result = search_pages(searchable, "software OR security")
    # Then it is an all-term word query, never an injected OR expression.
    assert result.query_terms == ("software", "OR", "security")
    assert result.total_matching_pages == 0


def test_identical_text_rebuild_preserves_database_and_receipt(searchable: Path) -> None:
    # Given an already indexed source snapshot.
    first = build_text_index(searchable)
    paths = (
        searchable / first.database_path,
        searchable / "data/processed/index/page-search.jsonl",
    )
    before = tuple((path.stat().st_mtime_ns, path.read_bytes()) for path in paths)
    # When repeating the same indexing operation.
    second = build_text_index(searchable)
    # Then no rows, database bytes, receipt bytes or mtimes are changed.
    assert second == first
    assert tuple((path.stat().st_mtime_ns, path.read_bytes()) for path in paths) == before


@pytest.mark.parametrize("query", ["Straße", "ﬁrmware"])
def test_unicode_query_uses_the_same_folding_as_indexed_text(tmp_path: Path, query: str) -> None:
    # Given actual Unicode PDF text whose full Python folding differs from FTS5 unicode61.
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    source = tmp_path / "data/raw/pdf" / f"{ids[0]}.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        _ = page.insert_htmlbox(pymupdf.Rect(20, 20, 400, 200), "<p>Straße ﬁrmware</p>")
        document.save(source)
    issue = issue.model_copy(update={"sha256": file_digest(source)})
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    _ = build_corpus_index(tmp_path)
    summary = build_text_index(tmp_path)
    if not summary.fts5_available:
        return
    # When searching for an unchanged word copied from the extracted source.
    result = search_pages(tmp_path, query)
    # Then Python full-casefold expansion cannot turn a present word into a missing match.
    assert result.total_matching_pages == 1
    assert query in result.hits[0].excerpt
    assert result.query_terms == (query,)


def test_stale_page_text_cannot_be_searched(searchable: Path) -> None:
    # Given an index built before an independent page-cache edit.
    _ = build_text_index(searchable)
    path = next((searchable / "data/processed/pages").glob("*.jsonl"))
    _ = path.write_text(path.read_text().replace("security", "changed"))
    # When a reader tries to use the historical verified cache.
    with pytest.raises(AcquisitionError):
        search_pages(searchable, "software")
    # Then the stale full-text index is unavailable rather than silently reused.


def test_database_corruption_is_not_a_zero_match(searchable: Path) -> None:
    # Given an indexed database whose bytes were corrupted afterward.
    summary = build_text_index(searchable)
    _ = (searchable / summary.database_path).write_bytes(b"preserved damaged cache")
    # When searching that cache.
    with pytest.raises(AcquisitionError, match="digest mismatch"):
        search_pages(searchable, "software")
    # Then corruption cannot masquerade as a successful empty retrieval.


def test_page_search_writer_refuses_symlink_destination(searchable: Path) -> None:
    # Given a generated destination aliased to an external original.
    directory = searchable / "data/processed/index"
    original = searchable / "original.sqlite"
    _ = original.write_bytes(b"preserve original")
    (directory / "page-search.sqlite").symlink_to(original)
    # When building the page cache.
    with pytest.raises(AcquisitionError, match="symlink"):
        build_text_index(searchable)
    # Then the external original is unchanged.
    assert original.read_bytes() == b"preserve original"


def test_index_page_bound_refuses_partial_success(searchable: Path) -> None:
    # Given a two-page source and a one-page whole-index bound.
    # When the index cannot cover all eligible current pages within its declared bound.
    with pytest.raises(AcquisitionError, match="page bound"):
        build_text_index(searchable, max_pages=1)
    # Then no database is published as a complete text snapshot.
    assert not (searchable / "data/processed/index/page-search.sqlite").exists()


def test_nested_writer_is_excluded_by_real_os_lock(searchable: Path) -> None:
    # Given another operation holding the actual project lock.
    with project_lock(searchable), pytest.raises(AcquisitionError, match="busy"):
        # When a page-index writer requests admission.
        build_text_index(searchable)
    # Then the writer refuses instead of racing the held operation.


@pytest.mark.parametrize("query", ["", "123", "word " * 300])
def test_invalid_search_input_refuses_before_index_access(tmp_path: Path, query: str) -> None:
    # Given an invalid query and no cache files.
    # When validating the public retrieval boundary.
    with pytest.raises(AcquisitionError, match="search"):
        search_pages(tmp_path, query)
    # Then no index is required to reject the invalid request.
