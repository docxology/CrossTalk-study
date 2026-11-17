"""Rebuild a complete catalog index from fresh local observations, never inferred URLs."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from itertools import islice
from typing import TYPE_CHECKING, Final
from uuid import UUID

from crosstalk.acquisition_lock import project_lock
from crosstalk.catalog import CatalogIssue, CatalogSummary
from crosstalk.index_history import issue_history, read_history
from crosstalk.index_identity import valid_manifest_binding
from crosstalk.index_implementation import index_implementation_sha256
from crosstalk.index_observe import IndexReader
from crosstalk.index_records import CorpusIndexRow, CorpusIndexSummary, IndexedExtraction
from crosstalk.index_store import publish_index
from crosstalk.models import (
    SERIES_ID,
    AcquisitionError,
    load_manifest,
    require_nps_url,
    safe_directory,
)
from crosstalk.records import ExtractionSummary, write_records

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.records import IssueExtraction

SAFE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")
MAX_RECORDS: Final = 10_000


def _catalog(reader: IndexReader) -> tuple[CatalogIssue, ...]:
    """Admit unique series identities before any catalog ID becomes a local file path."""
    rows = tuple(
        CatalogIssue.model_validate_json(line)
        for line in reader.read("data/manifest/catalog.jsonl").splitlines()
        if line.strip()
    )
    if len(rows) > MAX_RECORDS:
        raise AcquisitionError("catalog exceeds the 10,000-record index bound")
    if len({row.issue_id for row in rows}) != len(rows) or len(
        {row.item_id for row in rows}
    ) != len(rows):
        raise AcquisitionError("catalog has duplicate issue or publication identities")
    for row in rows:
        if not SAFE_ID.fullmatch(row.issue_id) or row.series_id != SERIES_ID:
            raise AcquisitionError("catalog issue identity is unsafe or outside CrossTalk")
        item_id = str(UUID(row.item_id))
        if (
            require_nps_url(row.landing_url)
            != f"https://calhoun.nps.edu/entities/publication/{item_id}"
        ):
            raise AcquisitionError("catalog item UUID disagrees with its landing locator")
    return tuple(sorted(rows, key=lambda row: row.issue_id))


def _extraction(reader: IndexReader) -> tuple[tuple[IssueExtraction, ...], str | None]:
    """A failed aggregate read stays unavailable instead of reviving old scope."""
    try:
        raw = reader.read("output/reports/extraction.jsonl")
    except FileNotFoundError:
        return (), None
    except (OSError, ValueError) as error:
        return (), str(error)
    try:
        summary = ExtractionSummary.model_validate_json(raw.strip())
        ids = tuple(row.issue_id for row in summary.issues)
        if len(ids) != len(set(ids)):
            raise AcquisitionError("extraction aggregate contains duplicate issue identities")
    except ValueError as error:
        return (), str(error)
    return summary.issues, None


def _duplicates(rows: tuple[CorpusIndexRow, ...]) -> tuple[CorpusIndexRow, ...]:
    """Annotate identical local PDF bytes without merging publication identities."""
    groups: defaultdict[str, list[str]] = defaultdict(list)
    identities = {row.issue_id: row for row in rows}
    for row in rows:
        if row.pdf.actual_sha256 is not None and row.pdf.header_valid:
            groups[row.pdf.actual_sha256].append(row.issue_id)
    result: list[CorpusIndexRow] = []
    for row in rows:
        group = tuple(sorted(groups.get(row.pdf.actual_sha256 or "", [])))
        current_row = row
        if len(group) > 1:
            representative = min(
                group,
                key=lambda identifier: (
                    not (
                        identities[identifier].pdf.integrity == "verified"
                        and identities[identifier].extraction.current
                    ),
                    identifier,
                ),
            )
            current_row = row.model_copy(
                update={
                    "duplicate_group": group,
                    "duplicate_of_issue_id": representative
                    if row.issue_id != representative
                    else None,
                }
            )
        result.append(current_row)
    return tuple(result)


def build_corpus_index(root: Path) -> CorpusIndexSummary:
    """Rebuild metadata caches under the project lock, retaining all catalog records."""
    root = root.absolute()
    with project_lock(root):
        implementation = index_implementation_sha256()
        reader = IndexReader(root)
        catalog = _catalog(reader)
        failures: list[str] = []
        observation = None
        try:
            observation = CatalogSummary.model_validate_json(
                reader.read("data/manifest/catalog-observation.jsonl").strip()
            )
        except (OSError, ValueError) as error:
            failures.append(f"catalog observation unavailable: {error}")
        capture_matches = observation is not None and (
            observation.records == len(catalog) == observation.reported_total
            and observation.matches_reported_total
            and all(row.source_snapshot_sha256 == observation.snapshot_sha256 for row in catalog)
        )
        _ = safe_directory(root, "data/manifest")
        manifest_path = reader.path("data/manifest/issues.jsonl")
        try:
            _ = reader.read("data/manifest/issues.jsonl")
            inventory = load_manifest(manifest_path)
        except FileNotFoundError:
            inventory = ()
        metadata = {issue.issue_id: issue for issue in inventory}
        outcomes, extraction_error = _extraction(reader)
        if extraction_error is not None:
            failures.append(f"extraction observation unavailable: {extraction_error}")
        extractions = {outcome.issue_id: outcome for outcome in outcomes}
        history = read_history(reader)
        failures.extend(history.failures)
        rows: list[CorpusIndexRow] = []
        for catalog_row in catalog:
            issue = metadata.get(catalog_row.issue_id)
            identity_matches = valid_manifest_binding(catalog_row, issue)
            historical = issue_history(history, issue if identity_matches else None)
            pdf = reader.pdf(f"data/raw/pdf/{catalog_row.issue_id}.pdf", historical.expected_sha256)
            extraction = (
                reader.extraction(extractions.get(catalog_row.issue_id), pdf)
                if extraction_error is None
                else IndexedExtraction(status="unavailable", error=extraction_error)
            )
            rows.append(
                CorpusIndexRow(
                    issue_id=catalog_row.issue_id,
                    item_id=catalog_row.item_id,
                    title=catalog_row.title,
                    raw_context=catalog_row.raw_context,
                    issued_metadata=catalog_row.issued_metadata,
                    landing_url=catalog_row.landing_url,
                    source_snapshot_sha256=catalog_row.source_snapshot_sha256,
                    flags=catalog_row.flags,
                    manifest_member=issue is not None,
                    manifest_binding_valid=identity_matches if issue is not None else None,
                    pdf_url=issue.pdf_url if issue else None,
                    locator_status=(
                        "unresolved"
                        if issue is None
                        else "manifest-resolved"
                        if identity_matches
                        else "manifest-mismatch"
                    ),
                    pdf=pdf,
                    extraction=extraction,
                    last_acquisition=historical.last,
                )
            )
        current = _duplicates(tuple(rows))
        _ = safe_directory(root, "data/raw/pdf")
        local_paths = tuple(islice((root / "data/raw/pdf").glob("*.pdf"), MAX_RECORDS + 1))
        if len(local_paths) > MAX_RECORDS:
            raise AcquisitionError("local PDF directory exceeds the 10,000-file index bound")
        ids = {row.issue_id for row in catalog}
        reader.recheck()
        if index_implementation_sha256() != implementation:
            raise AcquisitionError("index implementation changed during rebuild")
        publication = publish_index(root, current)
        summary = CorpusIndexSummary(
            implementation_sha256=implementation,
            observed_at=datetime.now(UTC).isoformat(),
            content_sha256=publication.content_sha256,
            jsonl_path=publication.jsonl_path,
            sqlite_path=publication.sqlite_path,
            sqlite_sha256=publication.sqlite_sha256,
            fts5_available=publication.fts5_available,
            catalog_records=len(current),
            catalog_reported_total=observation.reported_total if observation else None,
            catalog_capture_matches_reported=capture_matches,
            unresolved_locators=sum(row.locator_status != "manifest-resolved" for row in current),
            manifest_members=sum(row.manifest_member for row in current),
            verified_pdfs=sum(row.pdf.integrity == "verified" for row in current),
            unverified_pdfs=sum(row.pdf.integrity == "unverified" for row in current),
            unavailable_pdfs=sum(
                row.pdf.integrity in {"mismatch", "invalid", "unavailable"} for row in current
            ),
            current_extractions=sum(row.extraction.current for row in current),
            duplicate_pdf_groups=len(
                {row.duplicate_group for row in current if row.duplicate_group}
            ),
            unmatched_manifest_issue_ids=tuple(sorted(set(metadata).difference(ids))),
            uncataloged_local_pdf_ids=tuple(
                sorted(path.stem for path in local_paths if path.stem not in ids)
            ),
            input_failures=tuple(failures),
            source_bindings=reader.source_bindings(),
            missing_inputs=tuple(sorted(reader.missing)),
        )
        if index_implementation_sha256() != implementation:
            raise AcquisitionError("index implementation changed before summary publication")
        write_records(root / "data/processed/index/index-summary.jsonl", (summary,))
        return summary
