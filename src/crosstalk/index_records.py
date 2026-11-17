"""Typed current observations for the rebuildable corpus index."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from crosstalk.models import (
    AcquisitionError,
    Digest,
)
from crosstalk.records import Record


class IndexBinding(Record):
    """Exact project-local input bytes observed during one index rebuild."""

    path: str
    sha256: Digest


class IndexedPdf(Record):
    """Live local bytes; stored receipts never substitute for this observation."""

    integrity: Literal["absent", "verified", "unverified", "mismatch", "invalid", "unavailable"]
    actual_sha256: Digest | None = None
    expected_sha256: Digest | None = None
    byte_count: int | None = None
    header_valid: bool | None = None
    error: str | None = None

    @model_validator(mode="after")
    def verified_evidence(self) -> IndexedPdf:
        """A saved verified state requires matching actual and expected content identities."""
        if self.integrity == "verified" and (
            self.actual_sha256 is None
            or self.actual_sha256 != self.expected_sha256
            or self.header_valid is not True
            or self.byte_count is None
            or self.byte_count < 5
        ):
            raise AcquisitionError("verified index PDF lacks matching integrity evidence")
        return self


class IndexedExtraction(Record):
    """Declared extraction scope with current PDF/page/image integrity checks."""

    status: Literal["not-run", "complete", "partial", "failed", "stale", "unavailable"]
    current: bool = False
    receipt_source_sha256: str | None = None
    total_pages: int | None = None
    extracted_pages: int | None = None
    page_artifact_sha256: Digest | None = None
    error: str | None = None


class IndexedAcquisition(Record):
    """A source-matched historical attempt, separate from current PDF integrity."""

    status: Literal["downloaded", "verified", "failed", "interrupted"]
    error: str | None = None
    attempt_id: str | None = None
    stage: Literal["started", "prepared", "finished"] | None = None


class CorpusIndexRow(Record):
    """One catalog identity, including unresolved locators and unavailable evidence."""

    issue_id: str
    item_id: str
    title: str
    raw_context: str
    issued_metadata: str | None
    landing_url: str
    source_snapshot_sha256: Digest
    flags: tuple[str, ...]
    manifest_member: bool
    manifest_binding_valid: bool | None
    pdf_url: str | None
    locator_status: Literal["unresolved", "manifest-resolved", "manifest-mismatch"]
    pdf: IndexedPdf
    extraction: IndexedExtraction
    last_acquisition: IndexedAcquisition | None = None
    duplicate_of_issue_id: str | None = None
    duplicate_group: tuple[str, ...] = ()


class CorpusIndexSummary(Record):
    """Fresh cache-build accounting; the cache never certifies archive completeness."""

    implementation_sha256: Digest
    observed_at: str
    content_sha256: Digest
    jsonl_path: str
    sqlite_path: str
    sqlite_sha256: Digest
    fts5_available: bool
    catalog_records: int
    catalog_reported_total: int | None
    catalog_capture_matches_reported: bool
    unresolved_locators: int
    manifest_members: int
    verified_pdfs: int
    unverified_pdfs: int
    unavailable_pdfs: int
    current_extractions: int
    duplicate_pdf_groups: int
    unmatched_manifest_issue_ids: tuple[str, ...]
    uncataloged_local_pdf_ids: tuple[str, ...]
    input_failures: tuple[str, ...]
    source_bindings: tuple[IndexBinding, ...]
    missing_inputs: tuple[str, ...]
    archive_complete: Literal[False] = False
