"""Bounded live file observations used by the rebuildable corpus index."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, assert_never

from crosstalk.extraction_method import current_extraction_producer, page_method_current
from crosstalk.index_records import IndexBinding, IndexedExtraction, IndexedPdf
from crosstalk.models import AcquisitionError
from crosstalk.records import PageRecord

if TYPE_CHECKING:
    from crosstalk.extraction_method import ExtractionProducer
    from crosstalk.records import IssueExtraction

MAX_INPUT_BYTES: Final = 20_000_000
MAX_PDF_BYTES: Final = 250 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileObservation:
    """A regular-file content observation with its initial bytes."""

    sha256: str
    byte_count: int
    prefix: bytes


class IndexReader:
    """Mutable input-binding collection; repeated reads must agree within this build."""

    def __init__(self, root: Path) -> None:
        """Use one physical root and a fresh observation set per rebuild."""
        self.root: Path = root.absolute()
        self.bindings: dict[str, str] = {}
        self.missing: set[str] = set()
        if self.root.is_symlink() or not self.root.is_dir():
            raise AcquisitionError("index root must be an existing physical directory")
        self.producer: ExtractionProducer = current_extraction_producer()

    def path(self, relative: str) -> Path:
        """Refuse source aliases and paths outside the project root."""
        parsed = Path(relative)
        if parsed.is_absolute() or not parsed.parts or ".." in parsed.parts:
            raise AcquisitionError("index source path must remain project-local")
        path = self.root
        for part in parsed.parts:
            path /= part
            if path.is_symlink():
                raise AcquisitionError(f"index source contains a symlink: {relative}")
        return path

    def _remember(self, relative: str, digest: str) -> None:
        if relative in self.missing:
            raise AcquisitionError(f"index source appeared during observation: {relative}")
        if relative in self.bindings and self.bindings[relative] != digest:
            raise AcquisitionError(f"index source changed while being observed: {relative}")
        self.bindings[relative] = digest

    def _open(self, relative: str) -> int:
        try:
            return os.open(self.path(relative), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            self.missing.add(relative)
            raise

    def read(self, relative: str) -> bytes:
        """Read bounded metadata/cache bytes without following terminal symlinks or pipes."""
        descriptor = self._open(relative)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise AcquisitionError("index metadata source is not a regular file")
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise AcquisitionError("index metadata exceeds the 20 MB bound")
        self._remember(relative, hashlib.sha256(raw).hexdigest())
        return raw

    def digest(self, relative: str) -> FileObservation:
        """Stream bounded source bytes and detect mutation during the content read."""
        descriptor = self._open(relative)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PDF_BYTES:
                raise AcquisitionError("index binary source is nonregular or exceeds 250 MiB")
            prefix = stream.read(5)
            _ = stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AcquisitionError("index source changed while hashing")
        self._remember(relative, digest)
        return FileObservation(digest, after.st_size, prefix)

    def pdf(self, relative: str, expected: str | None) -> IndexedPdf:
        """Keep missing, mismatching, unknown and verified states distinct."""
        try:
            actual = self.digest(relative)
        except FileNotFoundError:
            return IndexedPdf(integrity="absent", expected_sha256=expected)
        except (OSError, ValueError) as error:
            return IndexedPdf(integrity="unavailable", expected_sha256=expected, error=str(error))
        valid = actual.prefix == b"%PDF-"
        integrity: Literal["invalid", "unverified", "verified", "mismatch"] = (
            "invalid"
            if not valid
            else "unverified"
            if expected is None
            else "verified"
            if actual.sha256 == expected
            else "mismatch"
        )
        return IndexedPdf(
            integrity=integrity,
            actual_sha256=actual.sha256,
            expected_sha256=expected,
            byte_count=actual.byte_count,
            header_valid=valid,
            error="local bytes lack a PDF header" if not valid else None,
        )

    def extraction(self, outcome: IssueExtraction | None, pdf: IndexedPdf) -> IndexedExtraction:
        """Admit current extraction only after checking its exact PDF, pages and assets."""
        if outcome is None:
            return IndexedExtraction(status="not-run")
        base = IndexedExtraction(
            status="not-run",
            receipt_source_sha256=outcome.source_sha256,
            total_pages=outcome.total_pages,
            extracted_pages=outcome.extracted_pages,
        )
        match outcome.status:
            case "failed":
                return base.model_copy(update={"status": "failed", "error": outcome.error})
            case "complete" | "partial":
                status = outcome.status
            case _:
                assert_never(outcome.status)
        if pdf.actual_sha256 is None or pdf.actual_sha256 != outcome.source_sha256:
            return base.model_copy(
                update={"status": "stale", "error": "PDF differs from extraction receipt"}
            )
        try:
            seal = self._page_seal(outcome, pdf)
        except (OSError, ValueError) as error:
            return base.model_copy(update={"status": "unavailable", "error": str(error)})
        return base.model_copy(
            update={
                "status": status,
                "current": True,
                "page_artifact_sha256": seal,
            }
        )

    def _page_seal(self, outcome: IssueExtraction, pdf: IndexedPdf) -> str:
        """Check page and image custody before a current extraction seal is admitted."""
        raw = self.read(f"data/processed/pages/{outcome.issue_id}.jsonl")
        digest = hashlib.sha256(raw).hexdigest()
        if outcome.page_artifact_sha256 is None or digest != outcome.page_artifact_sha256:
            raise AcquisitionError("page artifact lacks a current independently saved seal")
        pages = tuple(PageRecord.model_validate_json(line) for line in raw.splitlines())
        if (
            not 1 <= len(pages) <= 500
            or len(pages) != outcome.extracted_pages
            or any(
                page.issue_id != outcome.issue_id
                or page.page_index != index
                or page.source_sha256 != pdf.actual_sha256
                or not page_method_current(page, self.producer)
                or page.source_pdf != f"data/raw/pdf/{outcome.issue_id}.pdf"
                for index, page in enumerate(pages)
            )
        ):
            raise AcquisitionError("page cache disagrees with current PDF, scope or extractor")
        for page in pages:
            for image in page.images:
                if image.path is not None and self.digest(image.path).sha256 != image.sha256:
                    raise AcquisitionError("extracted image digest disagrees with page cache")
        return digest

    def source_bindings(self) -> tuple[IndexBinding, ...]:
        """Return deterministic source custody records for the completed observation."""
        return tuple(
            IndexBinding(path=path, sha256=digest) for path, digest in sorted(self.bindings.items())
        )

    def recheck(self) -> None:
        """Refuse publication if any successfully read source changed during this rebuild."""
        if current_extraction_producer() != self.producer:
            raise AcquisitionError("index native runtime or extraction implementation changed")
        for relative, expected in tuple(self.bindings.items()):
            if self.digest(relative).sha256 != expected:
                raise AcquisitionError(f"index source changed before publication: {relative}")
        for relative in self.missing:
            if self.path(relative).exists():
                raise AcquisitionError(
                    f"index missing source appeared before publication: {relative}"
                )
