"""Idempotent full-text indexing of current verified physical PDF pages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.extraction_method import page_method_current
from crosstalk.index_implementation import INDEX_IMPLEMENTATION_FILES
from crosstalk.index_observe import IndexReader
from crosstalk.index_read import current_corpus_index
from crosstalk.models import AcquisitionError, file_digest, safe_directory
from crosstalk.records import PageRecord, write_records
from crosstalk.search_records import IndexedPage, TextIndexSummary
from crosstalk.text_store import write_page_database

if TYPE_CHECKING:
    from crosstalk.index_records import CorpusIndexRow

SOURCE_FILES: Final = (
    "text_index.py",
    "text_store.py",
    "text_search.py",
    "search_records.py",
    "lexicon.py",
    *INDEX_IMPLEMENTATION_FILES,
)


def implementation_digest() -> str:
    """Bind the exact retrieval implementation independently of runtime output dates."""
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def _pages(reader: IndexReader, row: CorpusIndexRow) -> tuple[IndexedPage, ...]:
    """Only current, source-bound extraction text becomes searchable content."""
    relative = f"data/processed/pages/{row.issue_id}.jsonl"
    raw = reader.read(relative)
    if hashlib.sha256(raw).hexdigest() != row.extraction.page_artifact_sha256:
        raise AcquisitionError("page cache changed before text indexing")
    if reader.digest(f"data/raw/pdf/{row.issue_id}.pdf").sha256 != row.pdf.actual_sha256:
        raise AcquisitionError("PDF changed before text indexing")
    pages = tuple(PageRecord.model_validate_json(line) for line in raw.splitlines())
    if len(pages) != row.extraction.extracted_pages or any(
        page.issue_id != row.issue_id
        or page.page_index != index
        or page.source_sha256 != row.pdf.actual_sha256
        or not page_method_current(page, reader.producer)
        or page.source_pdf != f"data/raw/pdf/{row.issue_id}.pdf"
        for index, page in enumerate(pages)
    ):
        raise AcquisitionError("page identity disagrees with current corpus index")
    return tuple(
        IndexedPage(
            issue_id=row.issue_id,
            title=row.title,
            source_url=row.landing_url,
            source_sha256=page.source_sha256,
            page_index=page.page_index,
            page_label=page.page_label,
            text=page.text,
        )
        for page in pages
    )


def build_text_index(root: Path, max_pages: int = 100_000) -> TextIndexSummary:
    """Reuse an unchanged valid cache or atomically rebuild one row per physical page."""
    root = root.absolute()
    if not 1 <= max_pages <= 1_000_000:
        raise AcquisitionError("text-index page bound must be between 1 and 1,000,000")
    with current_corpus_index(root) as rows:
        directory = safe_directory(root, "data/processed/index")
        reader = IndexReader(root)
        corpus_digest = hashlib.sha256(
            reader.read("data/processed/index/corpus-index.jsonl")
        ).hexdigest()
        implementation = implementation_digest()
        accepted: list[IndexedPage] = []
        skipped: list[str] = []
        for row in rows:
            if (
                row.pdf.integrity != "verified"
                or not row.extraction.current
                or row.duplicate_of_issue_id
            ):
                skipped.append(row.issue_id)
                continue
            accepted.extend(_pages(reader, row))
            if len(accepted) > max_pages:
                raise AcquisitionError("page-search index exceeds its explicit page bound")
        bindings = reader.source_bindings()
        target = directory / "page-search.sqlite"
        receipt = directory / "page-search.jsonl"
        if target.is_symlink() or receipt.is_symlink():
            raise AcquisitionError("page-search cache path is a symlink")
        if receipt.is_file() and target.is_file():
            try:
                previous = TextIndexSummary.model_validate_json(receipt.read_bytes())
            except ValueError:
                previous = None
            if previous is not None and (
                previous.corpus_index_sha256 == corpus_digest
                and previous.implementation_sha256 == implementation
                and previous.source_bindings == bindings
                and file_digest(target) == previous.database_sha256
            ):
                reader.recheck()
                return previous
        available = write_page_database(target, tuple(accepted))
        reader.recheck()
        result = TextIndexSummary(
            database_sha256=file_digest(target),
            corpus_index_sha256=corpus_digest,
            implementation_sha256=implementation,
            source_bindings=bindings,
            indexed_issues=len({page.issue_id for page in accepted}),
            indexed_pages=len(accepted),
            skipped_issue_ids=tuple(skipped),
            fts5_available=available,
        )
        write_records(receipt, (result,))
        return result
