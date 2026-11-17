"""Bounded regular metadata reads and immutable atomic evidence publication."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from itertools import islice
from pathlib import Path
from typing import Final

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.locator_records import LocatorEvent
from crosstalk.models import AcquisitionError, safe_directory

MAX_METADATA_BYTES: Final = 1_000_000
MAX_LOCATOR_EVENTS: Final = 100_000
EVENT_NAME: Final = re.compile(r"[0-9a-f]{32}-(?:started|response|finished)\.json")


def read_metadata(path: Path, maximum: int = MAX_METADATA_BYTES) -> bytes:
    """Refuse special files, symlinks and oversized metadata before parsing."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("locator metadata must be a regular file")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise AcquisitionError("locator metadata exceeds its size bound")
    return raw


def publish_metadata(directory: Path, name: str, raw: bytes) -> Path:
    """Fsync unique bytes before linking; occupied unequal originals remain untouched."""
    if Path(name).name != name or name in {".", ".."}:
        raise AcquisitionError("locator evidence name must be a single path component")
    target = directory / name
    if target.exists() or target.is_symlink():
        if read_metadata(target, len(raw)) != raw:
            raise AcquisitionError("occupied locator evidence disagrees with immutable bytes")
        return target
    descriptor, temporary = tempfile.mkstemp(prefix=".locator-", dir=directory)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, target)
    Path(temporary).unlink()
    sync_directory(directory)
    return target


def publish_event(root: Path, event: LocatorEvent) -> Path:
    """Append one uniquely named durable stage without replacing prior evidence."""
    directory = safe_directory(root, "output/data/locator-ledger")
    return publish_metadata(
        directory,
        f"{event.attempt_id}-{event.stage}.json",
        event.model_dump_json().encode() + b"\n",
    )


def read_locator_events(root: Path) -> tuple[LocatorEvent, ...]:
    """Read a bounded ledger with matching typed stage and filename identities."""
    directory = safe_directory(root, "output/data/locator-ledger")
    paths = tuple(islice(directory.glob("*.json"), MAX_LOCATOR_EVENTS + 1))
    if len(paths) > MAX_LOCATOR_EVENTS:
        raise AcquisitionError("locator history exceeds its event-count bound")
    events: list[LocatorEvent] = []
    for path in paths:
        if not EVENT_NAME.fullmatch(path.name):
            raise AcquisitionError("unknown locator event filename")
        event = LocatorEvent.model_validate_json(read_metadata(path, 32_768))
        if path.name != f"{event.attempt_id}-{event.stage}.json":
            raise AcquisitionError("locator event filename disagrees with its identity")
        events.append(event)
    return tuple(sorted(events, key=lambda row: (row.observed_at, row.attempt_id, row.stage)))
