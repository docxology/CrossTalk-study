"""Independent native-text custody: optional raster decoding never determines eligibility."""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

import pymupdf

from crosstalk.extraction_method import page_method_current
from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError, Issue
from crosstalk.pdf_adapter import document_info
from crosstalk.records import ExtractionSummary, PageRecord

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.extraction_method import ExtractionProducer
    from crosstalk.records import IssueExtraction


@dataclass(frozen=True, slots=True)
class TextSourceBinding:
    """An actual current input file for a caller's whole-ledger publication guard."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class MeasurementInputs:
    """Current independently sealed native pages; artifact hash is current provenance."""

    sha256: str
    raw_pages: bytes
    pages: tuple[PageRecord, ...]
    page_artifact_sha256: str
    total_pdf_pages: int
    bindings: tuple[TextSourceBinding, ...]
    producer: ExtractionProducer


@dataclass(frozen=True, slots=True)
class TextAdmissionFailure:
    """Expected refusal remains explicit without discarding successful peer issues."""

    issue_id: str
    stage: Literal["extraction", "pdf", "page-cache", "provenance"]
    reason: str


@dataclass(frozen=True, slots=True)
class CurrentContext:
    """Current independently read manifest and extraction report bindings."""

    issue: Issue
    manifest_sha256: str
    extraction_sha256: str


def _eligible(outcome: IssueExtraction) -> bool:
    """Require an explicit nonempty extraction scope and independent current page seal."""
    match outcome.status:
        case "failed":
            return False
        case "complete" | "partial":
            return (
                outcome.page_artifact_sha256 is not None
                and outcome.source_sha256 is not None
                and outcome.total_pages is not None
                and outcome.total_pages > 0
                and 0 < outcome.extracted_pages <= 500
            )
        case _:
            assert_never(outcome.status)


def _pdf(path: Path) -> tuple[str, int]:
    """Inspect an actual bounded regular PDF after hashing the exact bytes being opened."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 100_000_000:
            raise AcquisitionError("native PDF is nonregular or exceeds its 100 MB bound")
        raw = stream.read(100_000_001)
    if len(raw) > 100_000_000:
        raise AcquisitionError("native PDF exceeds its bounded read")
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        metadata = document_info(document)
        if not metadata.is_pdf or metadata.needs_pass or metadata.page_count < 1:
            raise AcquisitionError("native PDF is unavailable, empty or encrypted")
        return hashlib.sha256(raw).hexdigest(), metadata.page_count


def _current_manifest(
    reader: IndexReader, outcome: IssueExtraction, supplied: Issue | None
) -> tuple[Issue, str]:
    """Require actual current manifest membership; an optional supplied record cannot be stale."""
    raw = reader.read("data/manifest/issues.jsonl")
    rows = tuple(Issue.model_validate_json(line) for line in raw.splitlines() if line.strip())
    matches = tuple(row for row in rows if row.issue_id == outcome.issue_id)
    if len(rows) > 10_000 or len({row.issue_id for row in rows}) != len(rows) or len(matches) != 1:
        raise AcquisitionError("native source needs one unique current manifest record")
    issue = matches[0]
    if supplied is not None and supplied != issue:
        raise AcquisitionError("supplied native manifest record is stale")
    return issue, hashlib.sha256(raw).hexdigest()


def _current_context(
    reader: IndexReader, outcome: IssueExtraction, supplied: Issue | None, root: Path
) -> CurrentContext:
    """A supplied outcome cannot authorize text after its actual independent report changes."""
    if reader.root != root.absolute():
        raise AcquisitionError("native reader root disagrees")
    issue, manifest_sha = _current_manifest(reader, outcome, supplied)
    raw = reader.read("output/reports/extraction.jsonl")
    extraction = ExtractionSummary.model_validate_json(raw.strip())
    matches = tuple(row for row in extraction.issues if row.issue_id == outcome.issue_id)
    if (
        len(extraction.issues) > 10_000
        or len({row.issue_id for row in extraction.issues}) != len(extraction.issues)
        or len(matches) != 1
    ):
        raise AcquisitionError(
            "native source needs one unique independent current extraction member"
        )
    if matches[0] != outcome:
        raise AcquisitionError(
            "supplied native extraction outcome is stale against its current report"
        )
    return CurrentContext(issue, manifest_sha, hashlib.sha256(raw).hexdigest())


def _valid_pages(
    pages: tuple[PageRecord, ...],
    outcome: IssueExtraction,
    source: tuple[str, str, int],
    producer: ExtractionProducer,
) -> bool:
    digest, relative, count = source
    return (
        len(pages) == outcome.extracted_pages
        and outcome.total_pages == count
        and (
            len(pages) <= count
            and (outcome.status != "complete" or len(pages) == count)
            and all(
                page.issue_id == outcome.issue_id
                and page.source_sha256 == digest
                and page.source_pdf == relative
                and page_method_current(page, producer)
                and page.page_index == index
                and math.isfinite(page.width)
                and math.isfinite(page.height)
                and min(page.width, page.height) > 0
                for index, page in enumerate(pages)
            )
        )
    )


def admit_text_source(
    root: Path,
    outcome: IssueExtraction,
    issue: Issue | None,
    *,
    reader: IndexReader | None = None,
) -> MeasurementInputs | TextAdmissionFailure:
    """Read/recheck native-only inputs; callers own any composing project_lock, without nesting."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", outcome.issue_id) or not _eligible(outcome):
        return TextAdmissionFailure(
            outcome.issue_id,
            "extraction",
            outcome.error or "unsafe, failed, empty, unsealed or unknown physical extraction scope",
        )
    own_reader = reader is None
    reader = reader if reader is not None else IndexReader(root)
    try:
        context = _current_context(reader, outcome, issue, root)
    except (OSError, ValueError) as error:
        return TextAdmissionFailure(outcome.issue_id, "provenance", str(error))
    relative = f"data/raw/pdf/{outcome.issue_id}.pdf"
    try:
        pdf = reader.path(relative)
        digest, count = _pdf(pdf)
    except (OSError, ValueError, RuntimeError) as error:
        return TextAdmissionFailure(outcome.issue_id, "pdf", str(error))
    try:
        raw = reader.read(f"data/processed/pages/{outcome.issue_id}.jsonl")
        artifact = hashlib.sha256(raw).hexdigest()
        if artifact != outcome.page_artifact_sha256:
            raise AcquisitionError("native page bytes differ from the independent extraction seal")
        pages = tuple(PageRecord.model_validate_json(line) for line in raw.splitlines())
    except (OSError, ValueError) as error:
        return TextAdmissionFailure(outcome.issue_id, "page-cache", str(error))
    try:
        if (
            digest != outcome.source_sha256
            or (context.issue.sha256 is not None and context.issue.sha256 != digest)
            or not _valid_pages(pages, outcome, (digest, relative, count), reader.producer)
        ):
            raise AcquisitionError("native PDF, manifest, page identity/version or scope disagrees")
        if own_reader:
            reader.recheck()
        expected = {
            relative: digest,
            f"data/processed/pages/{outcome.issue_id}.jsonl": artifact,
            "data/manifest/issues.jsonl": context.manifest_sha256,
            "output/reports/extraction.jsonl": context.extraction_sha256,
        }
        bindings = tuple(
            TextSourceBinding(path, reader.digest(path).sha256) for path in sorted(expected)
        )
        if any(binding.sha256 != expected[binding.path] for binding in bindings):
            raise AcquisitionError("native source bytes changed during admission")
    except (OSError, ValueError) as error:
        return TextAdmissionFailure(outcome.issue_id, "provenance", str(error))
    return MeasurementInputs(digest, raw, pages, artifact, count, bindings, reader.producer)
