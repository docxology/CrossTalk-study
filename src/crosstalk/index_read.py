"""Read corpus-index snapshots only after validating current source custody."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from itertools import islice
from typing import TYPE_CHECKING

from crosstalk.acquisition_lock import project_lock
from crosstalk.index_implementation import index_implementation_sha256
from crosstalk.index_observe import IndexReader
from crosstalk.index_records import CorpusIndexRow, CorpusIndexSummary
from crosstalk.models import AcquisitionError
from crosstalk.records import ExtractionSummary

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _cache(reader: IndexReader) -> tuple[CorpusIndexSummary, tuple[CorpusIndexRow, ...]]:
    """Check cache bytes and row identity before any stored observation is used."""
    summary = CorpusIndexSummary.model_validate_json(
        reader.read("data/processed/index/index-summary.jsonl").strip()
    )
    if summary.implementation_sha256 != index_implementation_sha256():
        raise AcquisitionError("index implementation changed; rebuild required")
    if (
        summary.jsonl_path != "data/processed/index/corpus-index.jsonl"
        or summary.sqlite_path != "data/processed/index/corpus-index.sqlite"
    ):
        raise AcquisitionError("index cache paths disagree with the supported layout")
    raw = reader.read(summary.jsonl_path)
    if hashlib.sha256(raw).hexdigest() != summary.content_sha256:
        raise AcquisitionError("index JSONL digest mismatch; rebuild required")
    if reader.digest(summary.sqlite_path).sha256 != summary.sqlite_sha256:
        raise AcquisitionError("index SQLite digest mismatch; rebuild required")
    rows = tuple(CorpusIndexRow.model_validate_json(line) for line in raw.splitlines())
    if len(rows) != summary.catalog_records or len({row.issue_id for row in rows}) != len(rows):
        raise AcquisitionError("index catalog accounting is malformed")
    return summary, rows


def _custody(summary: CorpusIndexSummary, rows: tuple[CorpusIndexRow, ...]) -> None:
    """Require positive and negative custody for each cached current state."""
    bindings = {binding.path: binding.sha256 for binding in summary.source_bindings}
    if (
        len(bindings) != len(summary.source_bindings)
        or "data/manifest/catalog.jsonl" not in bindings
    ):
        raise AcquisitionError("index source custody is incomplete or duplicated")
    for row in rows:
        pdf = f"data/raw/pdf/{row.issue_id}.pdf"
        if row.manifest_member and "data/manifest/issues.jsonl" not in bindings:
            raise AcquisitionError("index manifest membership lacks source custody")
        if row.pdf.actual_sha256 is not None and bindings.get(pdf) != row.pdf.actual_sha256:
            raise AcquisitionError("index PDF state lacks current source custody")
        if row.pdf.integrity == "absent" and pdf not in summary.missing_inputs:
            raise AcquisitionError("index absent PDF lacks negative observation evidence")
        if row.extraction.current and (
            "output/reports/extraction.jsonl" not in bindings
            or bindings.get(f"data/processed/pages/{row.issue_id}.jsonl")
            != row.extraction.page_artifact_sha256
        ):
            raise AcquisitionError("index extraction lacks current source custody")


def _extractions(reader: IndexReader, rows: tuple[CorpusIndexRow, ...]) -> None:
    """Revalidate live extraction seals under current method rules, including older indexes."""
    if not any(row.extraction.current for row in rows):
        return
    extraction = ExtractionSummary.model_validate_json(
        reader.read("output/reports/extraction.jsonl").strip()
    )
    outcomes = {outcome.issue_id: outcome for outcome in extraction.issues}
    if len(outcomes) != len(extraction.issues):
        raise AcquisitionError("index extraction aggregate has duplicate identities")
    for row in rows:
        if row.extraction.current:
            current = reader.extraction(outcomes.get(row.issue_id), row.pdf)
            if (
                not current.current
                or current.page_artifact_sha256 != row.extraction.page_artifact_sha256
            ):
                raise AcquisitionError("index extraction seal or method changed; rebuild required")


def _inputs(reader: IndexReader, summary: CorpusIndexSummary) -> None:
    """Require fresh contents and unchanged negative observations for all retained inputs."""
    for binding in summary.source_bindings:
        if reader.digest(binding.path).sha256 != binding.sha256:
            raise AcquisitionError(f"index source changed; rebuild required: {binding.path}")
    for relative in summary.missing_inputs:
        if reader.path(relative).exists():
            raise AcquisitionError(f"index missing source appeared; rebuild required: {relative}")


def _membership(
    reader: IndexReader, summary: CorpusIndexSummary, rows: tuple[CorpusIndexRow, ...]
) -> None:
    """Invalidate caches when new attempt events or uncataloged local PDFs appear."""
    expected_events = {
        binding.path
        for binding in summary.source_bindings
        if binding.path.startswith("output/data/acquisition-ledger/")
    }
    events = tuple(islice(reader.path("output/data/acquisition-ledger").glob("*.json"), 100_001))
    if (
        len(events) > 100_000
        or {path.relative_to(reader.root).as_posix() for path in events} != expected_events
    ):
        raise AcquisitionError("index acquisition history changed; rebuild required")
    pdfs = tuple(islice(reader.path("data/raw/pdf").glob("*.pdf"), 10_001))
    catalog = {row.issue_id for row in rows}
    unknown = tuple(sorted(path.stem for path in pdfs if path.stem not in catalog))
    if len(pdfs) > 10_000 or unknown != summary.uncataloged_local_pdf_ids:
        raise AcquisitionError("index local PDF inventory changed; rebuild required")


@contextmanager
def current_corpus_index(root: Path) -> Generator[tuple[CorpusIndexRow, ...]]:
    """Hold the project lock through a caller's use of a current validated snapshot."""
    with project_lock(root):
        reader = IndexReader(root)
        summary, rows = _cache(reader)
        _custody(summary, rows)
        _extractions(reader, rows)
        _inputs(reader, summary)
        _membership(reader, summary, rows)
        reader.recheck()
        if summary.implementation_sha256 != index_implementation_sha256():
            raise AcquisitionError("index implementation changed while reading; rebuild required")
        yield rows


def read_corpus_index(root: Path) -> tuple[CorpusIndexRow, ...]:
    """Return a checked snapshot; guarded consumers use current_corpus_index."""
    with current_corpus_index(root) as rows:
        return rows
