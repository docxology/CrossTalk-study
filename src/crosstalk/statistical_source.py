"""Current-source crosschecks for independently recomputed statistical inputs."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import date
from typing import TYPE_CHECKING, Final, Literal, assert_never

from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError
from crosstalk.records import ExtractionSummary
from crosstalk.text_source import MeasurementInputs, TextAdmissionFailure, admit_text_source

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.analysis_records import IssueAnalysis
    from crosstalk.linguistic_records import IssueLinguistics
    from crosstalk.records import IssueExtraction, PageRecord

MAX_ARTIFACT_BYTES: Final = 20_000_000
DATE: Final = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
YEAR: Final = re.compile(r"\b\d{4}\b")
SAFE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")


def read_artifact(path: Path) -> bytes:
    """Read a bounded regular file without following a terminal symlink."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            message = "statistical input must be a regular artifact"
            raise ValueError(message)
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        message = "statistical artifact exceeds the 20 MB input bound"
        raise ValueError(message)
    return raw


def sealed_page_bytes(root: Path, outcome: IssueExtraction) -> bytes:
    """Require the independent extraction receipt's seal, not self-declared row hashes."""
    match outcome.status:
        case "complete" | "partial":
            seal = outcome.page_artifact_sha256
        case "failed":
            message = "failed extraction cannot authorize statistical page inputs"
            raise ValueError(message)
        case _:
            assert_never(outcome.status)
    if not SAFE_ID.fullmatch(outcome.issue_id) or seal is None:
        message = "unsealed or unsafe extraction requires regeneration before statistics"
        raise ValueError(message)
    raw = read_artifact(root / "data/processed/pages" / f"{outcome.issue_id}.jsonl")
    if hashlib.sha256(raw).hexdigest() != seal:
        message = "stale page artifact seal: cache bytes differ from extraction receipt"
        raise ValueError(message)
    return raw


def current_pages(
    root: Path,
    analysis: IssueAnalysis,
    linguistic: IssueLinguistics,
    *,
    reader: IndexReader | None = None,
) -> tuple[PageRecord, ...]:
    """Require both producer observations to match current PDF and page bytes."""
    if analysis.issue_id != linguistic.issue_id or not SAFE_ID.fullmatch(analysis.issue_id):
        message = "statistical producer issue identities disagree"
        raise ValueError(message)
    own_reader = reader is None
    reader = reader if reader is not None else IndexReader(root)
    extraction = ExtractionSummary.model_validate_json(
        reader.read("output/reports/extraction.jsonl").strip()
    )
    matches = tuple(
        outcome for outcome in extraction.issues if outcome.issue_id == analysis.issue_id
    )
    if len(matches) != 1:
        raise AcquisitionError("statistical issue needs one independent current extraction outcome")
    outcome = matches[0]
    source = admit_text_source(root, outcome, None, reader=reader)
    match source:
        case TextAdmissionFailure():
            raise AcquisitionError(f"{source.stage}: {source.reason}")
        case MeasurementInputs():
            pass
        case _:
            assert_never(source)
    pages = source.pages
    if (
        analysis.analysis_method_version != "3"
        or linguistic.total_pdf_pages != source.total_pdf_pages
        or linguistic.extraction_status != outcome.status
        or source.sha256 != analysis.source_sha256
        or source.sha256 != linguistic.source_sha256
        or source.page_artifact_sha256 != linguistic.page_artifact_sha256
        or len(pages) != analysis.pages
        or len(pages) != len(linguistic.measures.pages)
    ):
        raise AcquisitionError(
            "statistical native producer observations disagree with current custody"
        )
    if own_reader:
        reader.recheck()
    return pages


def metadata_date(
    issued: str | None, title: str
) -> tuple[
    Literal["metadata-only", "missing", "invalid", "conflict", "ambiguous"],
    Literal["year", "month", "day", "unknown"],
    int | None,
]:
    """Keep uncertain/conflicting dates outside descriptive metadata-decade groups."""
    if issued is None:
        return "missing", "unknown", None
    found = DATE.fullmatch(issued)
    if found is None:
        return "invalid", "unknown", None
    year = int(found.group(1))
    month, day = found.group(2), found.group(3)
    try:
        _ = date(year, int(month) if month else 1, int(day) if day else 1)
    except ValueError:
        return "invalid", "unknown", None
    precision: Literal["year", "month", "day", "unknown"] = (
        "day" if day else "month" if month else "year"
    )
    title_years = {int(match.group()) for match in YEAR.finditer(title)}
    if len(title_years) > 1:
        return "ambiguous", precision, None
    if title_years and year not in title_years:
        return "conflict", precision, None
    return "metadata-only", precision, year
