"""Separate publisher candidate-to-PDF/extraction accounting, never an NPS index overlay."""

from __future__ import annotations

import hashlib
import html
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Literal, assert_never

from crosstalk.acquisition_ledger import AcquisitionLedger
from crosstalk.acquisition_lock import project_lock
from crosstalk.extract import extract_corpus
from crosstalk.index_observe import IndexReader
from crosstalk.index_records import IndexedExtraction, IndexedPdf
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.publisher_dataset import publish_publisher_records, read_publisher_bytes
from crosstalk.publisher_history import publisher_events
from crosstalk.publisher_inventory import PublisherInventory, read_publisher_inventory
from crosstalk.publisher_records import (
    ContactPublisherCard,
    PublicPublisherCard,
    PublisherCatalogRow,
)
from crosstalk.records import ExtractionSummary, Record


class PublisherCoverageRow(Record):
    """Candidate labels/dates remain attributed observations even after local byte verification."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    candidate: PublisherCatalogRow
    pdf: IndexedPdf | None
    extraction: IndexedExtraction
    printed_date: None = None
    publication_identity_review: Literal["pending"] = "pending"


class PublisherCoverageSummary(Record):
    """Publisher counts have their own captured denominator and source custody."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    observed_at: str
    source_snapshot_sha256: str
    implementation_sha256: str
    captured_cards: int
    public_pdf_candidates: int
    contact_only: int
    verified_local_pdfs: int
    current_extractions: int
    extracted_pages: int
    unknown_local_pdf_ids: tuple[str, ...]
    rows_sha256: str
    source_bindings: tuple[tuple[str, str], ...]
    expected_historical_total: None = None
    archive_complete: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PublisherCoverage:
    """A typed publisher-only panel and its separate candidate observations."""

    summary: PublisherCoverageSummary
    rows: tuple[PublisherCoverageRow, ...]


def _current_rows(
    inventory: PublisherInventory, reader: IndexReader
) -> tuple[PublisherCoverageRow, ...]:
    """Require independent acquisition evidence before describing extracted publisher content."""
    events = publisher_events(inventory.root)
    for event in events:
        _ = reader.read(f"output/data/acquisition-ledger/{event.attempt_id}-{event.stage}.json")
    for digest in {event.source_snapshot_sha256 for event in events}:
        _ = reader.read(f"data/raw/metadata/publisher/{digest}.json")
    ledger = AcquisitionLedger(inventory.root, inventory.proof.sources_sha256, "0" * 32, events)
    sources = {row.issue_id: row for row in inventory.sources}
    try:
        raw = reader.read("output/reports/extraction.jsonl")
        extraction = ExtractionSummary.model_validate_json(raw)
        outcomes = {row.issue_id: row for row in extraction.issues}
        if len(outcomes) != len(extraction.issues):
            raise AcquisitionError("publisher extraction contains duplicate source identities")
    except FileNotFoundError:
        outcomes = {}
    rows: list[PublisherCoverageRow] = []
    for card in inventory.cards:
        match card.candidate:
            case ContactPublisherCard():
                pdf, measured = None, IndexedExtraction(status="not-run")
            case PublicPublisherCard():
                source = sources[card.record_id]
                prior = ledger.prior(source)
                expected = source.sha256 or (
                    prior.sha256 or prior.expected_sha256 if prior else None
                )
                pdf = reader.pdf(f"data/raw/pdf/{source.issue_id}.pdf", expected)
                measured = (
                    reader.extraction(outcomes.get(source.issue_id), pdf)
                    if pdf.integrity == "verified"
                    else IndexedExtraction(status="not-run")
                )
            case _:
                assert_never(card.candidate)
        rows.append(PublisherCoverageRow(candidate=card, pdf=pdf, extraction=measured))
    return tuple(rows)


def _html_panel(coverage: PublisherCoverage) -> str:
    """Escape source metadata and keep publisher access gaps separate from NPS counts."""
    summary = coverage.summary
    body = "".join(
        "<tr><td>"
        + html.escape(row.candidate.candidate.title)
        + "</td><td>"
        + html.escape(row.candidate.candidate.access)
        + "</td><td>"
        + html.escape(row.pdf.integrity if row.pdf is not None else "contact-only; no request")
        + "</td><td>"
        + html.escape(row.extraction.status)
        + "</td><td>"
        + str(row.extraction.extracted_pages if row.extraction.current else "unavailable")
        + "</td><td>Printed date unreviewed</td></tr>"
        for row in coverage.rows
    )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        + "<title>Publisher acquisition frame</title>"
        + "<h1>Publisher acquisition frame</h1><p>Source family: AFSC publisher. "
        + "This panel is separate from the captured NPS series and is not a historical census.</p>"
        + f"<p>{summary.captured_cards} captured cards; {summary.public_pdf_candidates} public "
        + f"PDF candidates; {summary.contact_only} contact-only cards; "
        + f"{summary.verified_local_pdfs} verified local byte streams; "
        + f"{summary.current_extractions} current extractions; "
        + f"{summary.extracted_pages} extracted pages.</p>"
        + "<table><thead><tr><th>Candidate</th><th>Access</th><th>Local PDF</th>"
        + "<th>Extraction</th><th>Extracted pages</th><th>Date review</th></tr></thead><tbody>"
        + body
        + "</tbody></table><p>Card/filename date claims remain in the JSONL inventory. "
        + "No contact message is sent and no missing PDF URL is inferred.</p></html>"
    )


def publisher_pdf_paths(directory: Path, maximum: int = 10_000) -> tuple[Path, ...]:
    """Unknown-PDF accounting requires an available bounded physical directory scan."""
    if not 1 <= maximum <= 10_000:
        raise AcquisitionError("publisher PDF scan bound must be within 1-10,000")
    if any(part.is_symlink() for part in (*directory.parents, directory)):
        raise AcquisitionError("publisher PDF directory contains an alias")
    with os.scandir(directory) as entries:
        observed = tuple(islice(entries, 20_001))
    if len(observed) > 20_000:
        raise AcquisitionError("publisher PDF directory exceeds its finite entry bound")
    paths: list[Path] = []
    for entry in observed:
        if not entry.name.endswith(".pdf"):
            continue
        facts = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
            raise AcquisitionError("publisher PDF inventory contains a nonregular or aliased file")
        paths.append(directory / entry.name)
        if len(paths) > maximum:
            raise AcquisitionError("publisher local PDF inventory exceeds its 10,000-file bound")
    return tuple(sorted(paths))


def write_publisher_coverage(root: Path) -> PublisherCoverage:
    """Recheck source bytes under the publisher dataset's own operation lock."""
    with project_lock(root):
        inventory = read_publisher_inventory(root)
        reader = IndexReader(root)
        for relative in (
            "publisher-dataset.json",
            "data/manifest/publisher-sources.jsonl",
            "data/manifest/publisher-inventory.jsonl",
            f"data/raw/metadata/publisher/{inventory.proof.source_snapshot_sha256}.json",
        ):
            _ = reader.read(relative)
        rows = _current_rows(inventory, reader)
        sources = {row.issue_id for row in inventory.sources}
        directory = safe_directory(root, "data/raw/pdf")
        files = publisher_pdf_paths(directory)
        unknown = tuple(sorted(path.stem for path in files if path.stem not in sources))
        reader.recheck()
        raw = b"".join(row.model_dump_json().encode() + b"\n" for row in rows)
        summary = PublisherCoverageSummary(
            observed_at=datetime.now(UTC).isoformat(),
            source_snapshot_sha256=inventory.proof.source_snapshot_sha256,
            implementation_sha256=inventory.proof.implementation_sha256,
            captured_cards=inventory.proof.cards,
            public_pdf_candidates=len(inventory.sources),
            contact_only=inventory.proof.contact_only,
            verified_local_pdfs=sum(
                row.pdf is not None and row.pdf.integrity == "verified" for row in rows
            ),
            current_extractions=sum(row.extraction.current for row in rows),
            extracted_pages=sum(
                row.extraction.extracted_pages or 0 for row in rows if row.extraction.current
            ),
            unknown_local_pdf_ids=unknown,
            rows_sha256=hashlib.sha256(raw).hexdigest(),
            source_bindings=tuple((row.path, row.sha256) for row in reader.source_bindings()),
        )
        _ = safe_directory(root, "data/processed/index")
        _ = safe_directory(root, "output/reports")
        target = root / "output/reports/publisher-coverage.html"
        if target.exists() or target.is_symlink():
            _ = read_publisher_bytes(root, "output/reports/publisher-coverage.html", 20_000_000)
        publish_publisher_records(root, "data/processed/index/publisher-coverage.jsonl", rows)
        publish_publisher_records(root, "output/reports/publisher-coverage.jsonl", (summary,))
        document = _html_panel(PublisherCoverage(summary, rows)).encode()
        target = root / "output/reports/publisher-coverage.html"
        if target.is_symlink():
            raise AcquisitionError("publisher coverage output is a symlink")
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        descriptor, name = tempfile.mkstemp(prefix=".publisher-panel-", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        _ = Path(name).replace(target)
        reader.recheck()
        if read_publisher_inventory(root) != inventory:
            raise AcquisitionError(
                "publisher coverage source or implementation changed during build"
            )
        if publisher_pdf_paths(directory) != files:
            raise AcquisitionError("publisher PDF inventory changed during coverage build")
        return PublisherCoverage(summary, rows)


def extract_publisher(root: Path, max_pages: int | None = None) -> ExtractionSummary:
    """Reuse the generic extractor only in a complete verified publisher raw-input namespace."""
    coverage = write_publisher_coverage(root)
    if coverage.summary.unknown_local_pdf_ids or any(
        row.pdf is not None and row.pdf.integrity not in {"verified", "absent"}
        for row in coverage.rows
    ):
        raise AcquisitionError("publisher raw sources need integrity review before extraction")
    inventory = read_publisher_inventory(root)
    result = extract_corpus(root, max_pages)
    after = write_publisher_coverage(root)
    before_pdfs = tuple((row.candidate.record_id, row.pdf) for row in coverage.rows)
    after_pdfs = tuple((row.candidate.record_id, row.pdf) for row in after.rows)
    if (
        read_publisher_inventory(root) != inventory
        or before_pdfs != after_pdfs
        or after.summary.unknown_local_pdf_ids
    ):
        raise AcquisitionError("publisher inputs changed across extraction; outputs require review")
    return result
