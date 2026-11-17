"""Durable per-attempt stages recover publication without another HTTP request."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never
from uuid import uuid4

from crosstalk.acquisition_records import AttemptEvent
from crosstalk.models import AcquisitionError, DownloadReceipt, Issue, file_digest, safe_directory
from crosstalk.source_inventory import (
    PublisherDownloadSource,
    publisher_acquisition_identity,
    publisher_pin,
    source_family,
    source_snapshot,
)

if TYPE_CHECKING:
    from crosstalk.acquisition_records import PublisherFailureKind
    from crosstalk.source_inventory import DownloadSource

MAX_EVENTS: Final = 100_000
MAX_EVENT_BYTES: Final = 32_768
EVENT_NAME: Final = re.compile(r"[0-9a-f]{32}-(?:started|prepared|finished)\.json")


def issue_fingerprint(issue: DownloadSource) -> str:
    """Bind individual evidence to exact typed source metadata independently of peers."""
    match issue:
        case Issue():
            return hashlib.sha256(issue.model_dump_json().encode()).hexdigest()
        case PublisherDownloadSource():
            return hashlib.sha256(publisher_acquisition_identity(issue).encode()).hexdigest()
        case _:
            assert_never(issue)


def read_event_paths(directory: Path, maximum: int = MAX_EVENTS) -> tuple[Path, ...]:
    """Errors from a bounded physical scan cannot become empty acquisition history."""
    if not 1 <= maximum <= MAX_EVENTS:
        raise AcquisitionError("acquisition event scan bound must be within 1-100,000")
    if any(part.is_symlink() for part in (*directory.parents, directory)):
        raise AcquisitionError("acquisition event directory contains an alias")
    with os.scandir(directory) as entries:
        paths = tuple(directory / entry.name for entry in islice(entries, maximum + 1))
    if len(paths) > maximum:
        raise AcquisitionError("acquisition history exceeds its 100,000-event read bound")
    return tuple(sorted(path for path in paths if path.suffix == ".json"))


def read_events(root: Path) -> tuple[AttemptEvent, ...]:
    """Read bounded immutable event files; malformed history stays an explicit error."""
    directory = safe_directory(root, "output/data/acquisition-ledger")
    paths = read_event_paths(directory)
    events: list[AttemptEvent] = []
    for path in sorted(paths):
        if not EVENT_NAME.fullmatch(path.name):
            raise AcquisitionError("unknown file in acquisition event history")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise AcquisitionError("acquisition event is not a regular file")
            if before.st_nlink != 1:
                raise AcquisitionError("acquisition event has a hardlink alias")
            raw = stream.read(MAX_EVENT_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = path.lstat()
        if any(
            (
                facts.st_dev,
                facts.st_ino,
                facts.st_mode,
                facts.st_nlink,
                facts.st_size,
                facts.st_mtime_ns,
                facts.st_ctime_ns,
            )
            != (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            for facts in (after, current)
        ):
            raise AcquisitionError("acquisition event changed during its bounded read")
        if len(raw) > MAX_EVENT_BYTES:
            raise AcquisitionError("acquisition event exceeds its size bound")
        event = AttemptEvent.model_validate_json(raw)
        if path.name != f"{event.attempt_id}-{event.stage}.json":
            raise AcquisitionError("acquisition event filename disagrees with its identity")
        events.append(event)
    return tuple(
        sorted(events, key=lambda event: (event.observed_at, event.attempt_id, event.stage))
    )


def _publish(directory: Path, event: AttemptEvent) -> None:
    """Fsync then publish one unique event without replacing any previous event."""
    target = directory / f"{event.attempt_id}-{event.stage}.json"
    payload = event.model_dump_json().encode() + b"\n"
    if len(payload) > MAX_EVENT_BYTES:
        raise AcquisitionError("acquisition event exceeds its size bound")
    descriptor, temporary = tempfile.mkstemp(prefix=".attempt-", dir=directory)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, target)
    Path(temporary).unlink()
    sync_directory(directory)


def sync_directory(directory: Path) -> None:
    """Persist directory entries for staged payloads, publication and immutable events."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class AcquisitionAttempt:
    """One started attempt with immutable run and source bindings."""

    directory: Path
    started: AttemptEvent

    def prepare(self, partial: Path, receipt: DownloadReceipt) -> None:
        """Durably record complete payload evidence before the final PDF link exists."""
        if (
            receipt.sha256 is None
            or file_digest(partial) != receipt.sha256
            or partial.stat().st_size != receipt.byte_count
        ):
            raise AcquisitionError("prepared payload disagrees with its digest or byte count")
        sync_directory(partial.parent)
        event = self.started.model_copy(
            update={
                "observed_at": datetime.now(UTC).isoformat(),
                "stage": "prepared",
                "partial_name": partial.name,
                "receipt": receipt,
            }
        )
        _publish(self.directory, event)

    def finish(
        self, receipt: DownloadReceipt, *, failure_kind: PublisherFailureKind | None = None
    ) -> None:
        """Append an explicit outcome immediately, independent of batch-summary survival."""
        event = self.started.model_copy(
            update={
                "observed_at": datetime.now(UTC).isoformat(),
                "stage": "finished",
                "receipt": receipt,
                "publisher_failure_kind": failure_kind,
            }
        )
        _publish(self.directory, event)


@dataclass(frozen=True, slots=True)
class AcquisitionLedger:
    """A snapshot of historical attempts; only live digest checks admit byte reuse."""

    root: Path
    manifest_sha256: str
    run_id: str
    events: tuple[AttemptEvent, ...]

    def matching(self, issue: DownloadSource) -> tuple[AttemptEvent, ...]:
        """Exclude events from a changed locator or issue metadata revision."""
        digest = issue_fingerprint(issue)
        return tuple(
            event
            for event in self.events
            if event.issue_sha256 == digest
            and event.pdf_url == issue.pdf_url
            and event.source_family == source_family(issue)
        )

    def prior(self, issue: DownloadSource) -> DownloadReceipt | None:
        """Return the newest content evidence, retaining explicit failures separately."""
        receipts = tuple(
            event.receipt for event in self.matching(issue) if event.receipt is not None
        )
        evidence = tuple(
            receipt for receipt in receipts if receipt.sha256 or receipt.expected_sha256
        )
        return evidence[-1] if evidence else (receipts[-1] if receipts else None)

    def record_verification(self, issue: DownloadSource, receipt: DownloadReceipt) -> None:
        """Close recovered publication with a fresh immutable verification attempt."""
        events = self.matching(issue)
        if events and any(event.stage != "finished" for event in events[-1:]):
            self.begin(issue).finish(receipt)

    def last_attempt(self, issue: DownloadSource) -> str:
        """Unattempted work sorts before retried failures so small batches make progress."""
        events = self.matching(issue)
        return events[-1].observed_at if events else ""

    def begin(self, issue: DownloadSource) -> AcquisitionAttempt:
        """Append admission before any new local publication or archive request."""
        event = AttemptEvent(
            attempt_id=uuid4().hex,
            run_id=self.run_id,
            issue_id=issue.issue_id,
            issue_sha256=issue_fingerprint(issue),
            manifest_sha256=self.manifest_sha256,
            observed_at=datetime.now(UTC).isoformat(),
            stage="started",
            pdf_url=issue.pdf_url,
            source_family=source_family(issue),
            source_snapshot_sha256=source_snapshot(issue),
            source_pinned_sha256=publisher_pin(issue),
        )
        directory = safe_directory(self.root, "output/data/acquisition-ledger")
        _publish(directory, event)
        return AcquisitionAttempt(directory, event)

    def recover(self, issue: DownloadSource, target: Path) -> DownloadReceipt | None:
        """Link a verified prepared payload after interruption, never overwrite a final file."""
        for event in reversed(self.matching(issue)):
            receipt = event.receipt
            name = event.partial_name
            if name is None or receipt is None or receipt.sha256 is None:
                continue
            if (
                Path(name).name != name
                or not name.startswith(f".{issue.issue_id}-")
                or not name.endswith(".part")
            ):
                raise AcquisitionError("prepared payload path is unsafe")
            partial = target.parent / name
            if not partial.exists() or partial.is_symlink():
                continue
            if file_digest(partial) != receipt.sha256:
                continue
            if issue.sha256 is not None and receipt.sha256 != issue.sha256:
                continue
            os.link(partial, target)
            sync_directory(target.parent)
            partial.unlink()
            sync_directory(target.parent)
            return receipt.model_copy(update={"status": "verified", "path": str(target)})
        return None
