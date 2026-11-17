"""Real-file and SQLite tests for complete, fresh, rebuildable catalog indexing."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from pydantic import ValidationError

from crosstalk.acquisition_lock import project_lock
from crosstalk.catalog import CatalogLink, CatalogSnapshot, import_catalog
from crosstalk.corpus_index import build_corpus_index
from crosstalk.extract import extract_corpus
from crosstalk.index_read import current_corpus_index, read_corpus_index
from crosstalk.models import SERIES_ID, AcquisitionError, Issue
from crosstalk.records import write_records
from tests.test_analysis import make_pdf

if TYPE_CHECKING:
    from pathlib import Path


def catalog_at(root: Path, count: int = 3) -> tuple[str, ...]:
    identifiers = tuple(str(UUID(int=index + 1)) for index in range(count))
    snapshot = CatalogSnapshot(
        observed_at="2026-11-05T00:00:00+00:00",
        source=f"https://calhoun.nps.edu/entities/series/{SERIES_ID}",
        reported_total=count,
        method="local real-format test export",
        records=tuple(
            CatalogLink(
                title="CrossTalk / January 1990" if index == 0 else f"CrossTalk Fixture {index}",
                url=f"https://calhoun.nps.edu/entities/publication/{identifier}",
                context="CrossTalk (Publisher, 1989-01) Show more",
            )
            for index, identifier in enumerate(identifiers)
        ),
    )
    path = root / "snapshot.json"
    _ = path.write_text(snapshot.model_dump_json())
    _ = import_catalog(path, root)
    return tuple(f"ct-{identifier}" for identifier in identifiers)


def register_pdf(root: Path, issue_id: str) -> Issue:
    source = root / "data/raw/pdf" / f"{issue_id}.pdf"
    make_pdf(source, ("Software security and engineering fixture",))
    return Issue(
        issue_id=issue_id,
        item_id=issue_id.removeprefix("ct-"),
        title="Fixture issue",
        landing_url=f"https://calhoun.nps.edu/entities/publication/{issue_id.removeprefix('ct-')}",
        pdf_url="https://calhoun.nps.edu/server/api/core/bitstreams/fixture/content",
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def test_all_catalog_records_remain_indexed_when_urls_unresolved(tmp_path: Path) -> None:
    # Given a complete 259-record catalog with no invented downloadable manifest rows.
    _ = catalog_at(tmp_path, 259)
    # When building and reading current metadata caches.
    summary = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then every catalog identity remains visible with explicit unresolved state.
    assert (summary.catalog_records, summary.unresolved_locators, len(rows)) == (259, 259, 259)
    assert all(row.pdf_url is None and row.pdf.integrity == "absent" for row in rows)
    assert rows[0].issued_metadata == "1989-01"
    assert rows[0].flags == ("title-metadata-year-conflict",)
    assert not summary.archive_complete


def test_duplicate_representative_prefers_verified_current_source(tmp_path: Path) -> None:
    # Given identical bytes under an earlier unregistered ID and a verified current ID.
    identifiers = catalog_at(tmp_path, 2)
    verified = register_pdf(tmp_path, identifiers[1])
    shutil.copyfile(
        tmp_path / f"data/raw/pdf/{identifiers[1]}.pdf",
        tmp_path / f"data/raw/pdf/{identifiers[0]}.pdf",
    )
    write_records(tmp_path / "data/manifest/issues.jsonl", (verified,))
    _ = extract_corpus(tmp_path)
    # When duplicate relationships are rebuilt from current evidence.
    _ = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then an ineligible alias cannot hide the eligible source from downstream search.
    assert rows[0].duplicate_of_issue_id == identifiers[1]
    assert rows[1].duplicate_of_issue_id is None
    assert rows[0].duplicate_group == tuple(identifiers)


def test_wrong_publication_locator_cannot_resolve_catalog_identity(tmp_path: Path) -> None:
    # Given checksum-valid bytes accompanied by the locator of another catalog item.
    identifiers = catalog_at(tmp_path, 2)
    verified = register_pdf(tmp_path, identifiers[0])
    wrong = verified.model_copy(
        update={
            "item_id": None,
            "landing_url": f"https://calhoun.nps.edu/entities/publication/{identifiers[1].removeprefix('ct-')}",
        }
    )
    write_records(tmp_path / "data/manifest/issues.jsonl", (wrong,))
    _ = extract_corpus(tmp_path)
    # When the index checks both source bytes and publication identity.
    summary = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then an absent item_id is never treated as proof of a contradictory locator.
    assert rows[0].manifest_binding_valid is False
    assert rows[0].locator_status == "manifest-mismatch"
    assert (summary.unresolved_locators, summary.verified_pdfs) == (2, 0)


def test_real_pdf_and_page_scope_are_current_in_sqlite(tmp_path: Path) -> None:
    # Given catalog identities and a real digest-pinned extracted PDF.
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    # When the complete catalog index is rebuilt.
    summary = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then integrity/scope are source-bound and SQLite retains unresolved peers too.
    assert (summary.verified_pdfs, summary.current_extractions, summary.unresolved_locators) == (
        1,
        1,
        2,
    )
    assert (rows[0].pdf.actual_sha256, rows[0].extraction.current) == (issue.sha256, True)
    with closing(sqlite3.connect(tmp_path / summary.sqlite_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 3
        if summary.fts5_available:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM issue_fts WHERE issue_fts MATCH 'Fixture'"
                ).fetchone()[0]
                == 2
            )


def test_identical_rebuild_does_not_rewrite_normalized_caches(tmp_path: Path) -> None:
    # Given an existing current cache generation.
    _ = catalog_at(tmp_path)
    first = build_corpus_index(tmp_path)
    paths = (tmp_path / first.jsonl_path, tmp_path / first.sqlite_path)
    before = tuple((path.stat().st_mtime_ns, path.read_bytes()) for path in paths)
    # When rebuilding from byte-identical observations.
    second = build_corpus_index(tmp_path)
    # Then deterministic record bytes and SQLite remain untouched.
    assert second.content_sha256 == first.content_sha256
    assert tuple((path.stat().st_mtime_ns, path.read_bytes()) for path in paths) == before


def test_changed_pdf_invalidates_saved_success_and_rebuild_records_failure(tmp_path: Path) -> None:
    # Given an index that previously verified a local PDF.
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    _ = build_corpus_index(tmp_path)
    _ = (tmp_path / "data/raw/pdf" / f"{ids[0]}.pdf").write_bytes(b"corrupt preserved original")
    # When a consumer requests current rows from the old cache.
    with pytest.raises(AcquisitionError):
        read_corpus_index(tmp_path)
    # Then the stale verified observation cannot be displayed.


def test_rebuild_keeps_corrupt_pdf_and_marks_stale_extraction(tmp_path: Path) -> None:
    # Given local bytes changed after extraction.
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    source = tmp_path / "data/raw/pdf" / f"{ids[0]}.pdf"
    corrupt = b"corrupt preserved original"
    _ = source.write_bytes(corrupt)
    # When current observations rebuild the index.
    _ = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then corruption stays inspectable and historical extraction cannot become current.
    assert (rows[0].pdf.integrity, rows[0].extraction.status) == ("invalid", "stale")
    assert source.read_bytes() == corrupt


def test_duplicate_bytes_are_linked_without_merging_catalog_identities(tmp_path: Path) -> None:
    # Given two publication identities whose local manifestations share exact bytes.
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    shutil.copyfile(
        tmp_path / "data/raw/pdf" / f"{ids[0]}.pdf", tmp_path / "data/raw/pdf" / f"{ids[1]}.pdf"
    )
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    # When rebuilding the catalog index.
    summary = build_corpus_index(tmp_path)
    rows = read_corpus_index(tmp_path)
    # Then distinct identities remain while the exact-byte relationship is explicit.
    assert (len(rows), summary.duplicate_pdf_groups) == (3, 1)
    assert rows[0].duplicate_group == ids[:2]
    assert rows[1].duplicate_of_issue_id == ids[0]


def test_newly_present_pdf_invalidates_prior_absence(tmp_path: Path) -> None:
    # Given an index with an explicitly absent PDF.
    ids = catalog_at(tmp_path)
    _ = build_corpus_index(tmp_path)
    _ = register_pdf(tmp_path, ids[0])
    # When reading the prior negative observation.
    with pytest.raises(AcquisitionError, match="appeared"):
        read_corpus_index(tmp_path)
    # Then a cached absence cannot survive a new local manifestation.


def test_busy_project_lock_refuses_rebuild(tmp_path: Path) -> None:
    # Given a real held project OS lock.
    # When another rebuild attempts admission.
    with project_lock(tmp_path), pytest.raises(AcquisitionError):
        build_corpus_index(tmp_path)
    # Then it cannot publish concurrently with an acquisition writer.


def test_malformed_cached_summary_never_displays_verified_rows(tmp_path: Path) -> None:
    # Given a valid generation whose saved summary is subsequently corrupted.
    _ = catalog_at(tmp_path)
    _ = build_corpus_index(tmp_path)
    _ = (tmp_path / "data/processed/index/index-summary.jsonl").write_text("{}\n")
    # When a consumer requests current index rows.
    with pytest.raises(ValidationError):
        read_corpus_index(tmp_path)
    # Then no cached verified state escapes a malformed source boundary.


def test_fifo_catalog_is_refused_without_waiting_for_a_writer(tmp_path: Path) -> None:
    # Given a nonregular catalog input with no writer.
    directory = tmp_path / "data/manifest"
    directory.mkdir(parents=True)
    os.mkfifo(directory / "catalog.jsonl")
    # When the bounded index source reader opens it nonblockingly.
    with pytest.raises(AcquisitionError, match="not a regular file"):
        build_corpus_index(tmp_path)
    # Then this finite rebuild cannot block on a filesystem pipe.


def test_guarded_reader_holds_real_lock_through_consumer(tmp_path: Path) -> None:
    # Given a freshly rebuilt catalog cache.
    _ = catalog_at(tmp_path)
    _ = build_corpus_index(tmp_path)
    # When a guarded consumer is using the validated snapshot.
    with (
        current_corpus_index(tmp_path) as rows,
        pytest.raises(AcquisitionError),
        project_lock(tmp_path),
    ):
        pytest.fail("a concurrent writer acquired the guarded project's lock")
    # Then it received the full catalog while a writer remained excluded.
    assert len(rows) == 3
