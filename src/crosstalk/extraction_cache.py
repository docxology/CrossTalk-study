"""Bounded page-cache custody, sealed resume checks and preserved derivative history."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from pydantic import ValidationError

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.extraction_method import ExtractionProducer, page_method_current
from crosstalk.models import AcquisitionError, file_digest, safe_directory
from crosstalk.records import EXTRACTOR_VERSION, ExtractionSummary, IssueExtraction, PageRecord

MAX_CACHE_BYTES: Final = 20_000_000


def read_cache_bytes(path: Path) -> bytes:
    """Admit regular, bounded artifact bytes without following aliases or blocking on FIFOs."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("extraction cache is not a regular file")
        raw = stream.read(MAX_CACHE_BYTES + 1)
    if len(raw) > MAX_CACHE_BYTES:
        raise AcquisitionError("extraction cache exceeds its 20 MB read bound")
    return raw


def preserve_cache_bytes(root: Path, raw: bytes) -> None:
    """Keep exact obsolete/corrupt derived bytes in append-only content-addressed custody."""
    digest = hashlib.sha256(raw).hexdigest()
    directory = safe_directory(root, "data/processed/page-history")
    target = directory / f"{digest}.jsonl"
    if target.exists() or target.is_symlink():
        if target.is_symlink() or file_digest(target) != digest:
            raise AcquisitionError("existing cache history conflicts with its content address")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".page-history-", dir=directory)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, target)
    Path(temporary).unlink()
    sync_directory(directory)


def previous_outcomes(root: Path) -> tuple[IssueExtraction, ...]:
    """Read a prior aggregate once; malformed regular bytes are archived before regeneration."""
    path = root / "output/reports/extraction.jsonl"
    if path.is_symlink():
        raise AcquisitionError("extraction aggregate is a symlink")
    try:
        raw = read_cache_bytes(path)
    except FileNotFoundError:
        return ()
    preserve_cache_bytes(root, raw)
    try:
        summary = ExtractionSummary.model_validate_json(raw.strip())
    except ValidationError:
        preserve_cache_bytes(root, raw)
        return ()
    identifiers = tuple(outcome.issue_id for outcome in summary.issues)
    if len(set(identifiers)) != len(identifiers):
        preserve_cache_bytes(root, raw)
        return ()
    return summary.issues


@dataclass(frozen=True, slots=True)
class CacheIdentity:
    """Exact raw source and requested extraction scope for one resume decision."""

    issue_id: str
    source_sha256: str
    count: int
    total_pages: int
    producer: ExtractionProducer


@dataclass(frozen=True, slots=True)
class PageCache:
    """A single bounded snapshot; self-declared source hashes never establish custody."""

    root: Path
    path: Path
    raw: bytes | None
    sha256: str | None
    pages: tuple[PageRecord, ...]

    @classmethod
    def read(cls, root: Path, issue_id: str) -> PageCache:
        """Capture current regular bytes once, retaining malformed content for history."""
        path = root / "data/processed/pages" / f"{issue_id}.jsonl"
        try:
            raw = read_cache_bytes(path)
        except FileNotFoundError:
            return cls(root, path, None, None, ())
        try:
            pages = tuple(PageRecord.model_validate_json(line) for line in raw.splitlines())
        except ValidationError:
            pages = ()
        return cls(root, path, raw, hashlib.sha256(raw).hexdigest(), pages)

    def resumes(self, identity: CacheIdentity, prior: IssueExtraction | None) -> bool:
        """Require an independently saved seal, current source/version/scope and image bytes."""
        if (
            prior is None
            or prior.page_artifact_sha256 is None
            or self.sha256 != prior.page_artifact_sha256
        ):
            return False
        match prior.status:
            case "failed":
                return False
            case "complete" | "partial":
                valid_scope = (
                    prior.issue_id == identity.issue_id
                    and prior.source_sha256 == identity.source_sha256
                    and prior.extracted_pages == identity.count
                    and prior.total_pages == identity.total_pages
                )
            case _:
                assert_never(prior.status)
        if not valid_scope:
            return False
        return len(self.pages) == identity.count and all(
            page.source_sha256 == identity.source_sha256
            and page.issue_id == identity.issue_id
            and page.source_pdf == f"data/raw/pdf/{identity.issue_id}.pdf"
            and page.extractor_version == EXTRACTOR_VERSION
            and page_method_current(page, identity.producer)
            and page.page_index == index
            and all(self._image_current(image.path, image.sha256) for image in page.images)
            for index, page in enumerate(self.pages)
        )

    def _image_current(self, relative: str | None, digest: str | None) -> bool:
        if relative is None:
            return True
        path = self.root / relative
        try:
            return not path.is_symlink() and file_digest(path) == digest
        except FileNotFoundError:
            return False

    def preserve(self) -> None:
        """Archive obsolete bytes before atomic replacement and refuse concurrent cache edits."""
        if self.raw is not None:
            preserve_cache_bytes(self.root, self.raw)
            if file_digest(self.path) != self.sha256:
                raise AcquisitionError("page cache changed while being preserved")


def reseal_outcomes(
    root: Path, outcomes: tuple[IssueExtraction, ...]
) -> tuple[IssueExtraction, ...]:
    """Recheck actual source/cache hashes immediately before aggregate publication."""
    current: list[IssueExtraction] = []
    for outcome in outcomes:
        current_outcome = outcome
        try:
            if outcome.page_artifact_sha256 is not None and (
                file_digest(root / f"data/processed/pages/{outcome.issue_id}.jsonl")
                != outcome.page_artifact_sha256
                or file_digest(root / f"data/raw/pdf/{outcome.issue_id}.pdf")
                != outcome.source_sha256
            ):
                raise AcquisitionError("source or sealed page artifact changed before publication")
        except (OSError, ValueError) as error:
            current_outcome = outcome.model_copy(
                update={"status": "failed", "page_artifact_sha256": None, "error": str(error)}
            )
        current.append(current_outcome)
    return tuple(current)
