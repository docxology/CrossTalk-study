"""A real host lock and durable request observations pace independent archival clients."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import islice
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from crosstalk.archival_records import ArchivalError, ArchivalRecord, archive_fetch_url, archive_url
from crosstalk.case_files import read_bytes
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import safe_directory

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class HostObservation(ArchivalRecord):
    """An operational request window is not a response, policy grant or payload success."""

    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    stage: Literal["started", "finished"]
    observed_at: AwareDatetime
    request_url_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    delay_seconds: float = Field(ge=10)
    host: Literal["web.archive.org"] = "web.archive.org"


def require_host_lock(path: Path, descriptor: int) -> None:
    """The acquired descriptor and its physical single-link path must still agree."""
    if any(part.is_symlink() for part in (*path.parents, path)):
        raise ArchivalError("archival host lock path contains an alias")
    held = os.fstat(descriptor)
    current = path.lstat()
    if (
        not stat.S_ISREG(held.st_mode)
        or held.st_nlink != 1
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise ArchivalError("archival host lock descriptor and path identity disagree")


@contextmanager
def _host_lock(root: Path) -> Generator[Path]:
    directory = safe_directory(root, "output/data/archival/http-requests")
    descriptor = os.open(
        directory / "host.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    with os.fdopen(descriptor, "rb+", buffering=0) as stream:
        facts = os.fstat(stream.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
            raise ArchivalError("archival host lock must be an ordinary single-link file")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ArchivalError("archival host request window is busy") from error
        try:
            require_host_lock(directory / "host.lock", stream.fileno())
            yield directory
        finally:
            try:
                require_host_lock(directory / "host.lock", stream.fileno())
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_host_observations(directory: Path) -> tuple[HostObservation, ...]:
    """Scan explicitly: unavailable history must propagate rather than look empty."""
    if any(part.is_symlink() for part in (*directory.parents, directory)):
        raise ArchivalError("archival host observations contain a directory alias")
    with os.scandir(directory) as entries:
        paths = tuple(directory / entry.name for entry in islice(entries, 20_002))
    if len(paths) > 20_001:
        raise ArchivalError("archival host observations exceed their bounded ledger")
    rows: list[HostObservation] = []
    for path in paths:
        if path.name == "host.lock":
            continue
        if path.suffix != ".json":
            raise ArchivalError("unknown archival host observation is preserved")
        if len(rows) == 20_000:
            raise ArchivalError("archival host observations exceed their bounded ledger")
        row = HostObservation.model_validate_json(read_bytes(path, 16_000))
        if path.name != f"{row.request_id}-{row.stage}.json":
            raise ArchivalError("archival host observation filename disagrees")
        rows.append(row)
    return tuple(rows)


def _append(directory: Path, row: HostObservation) -> None:
    _ = publish_metadata(
        directory, f"{row.request_id}-{row.stage}.json", row.model_dump_json().encode() + b"\n"
    )


class HostCooldown:
    """Use persisted starts after interruption and finishes after closed request windows."""

    root: Path

    def __init__(self, root: Path) -> None:
        """The state root is explicit and shared across all clients for this source family."""
        self.root = root.absolute()

    @contextmanager
    def request_window(self, url: str, delay: float, deadline: float) -> Generator[None]:
        """Persist before GET and hold the actual host lock through response retention."""
        if url == "https://web.archive.org/robots.txt":
            _ = archive_url(url, robots=True)
        else:
            _ = archive_fetch_url(url)
        with _host_lock(self.root) as directory:
            rows = read_host_observations(directory)
            now = datetime.now(UTC)
            latest = max(rows, key=lambda row: row.observed_at, default=None)
            last = latest.observed_at if latest else None
            if last is not None and (last - now).total_seconds() > 5:
                raise ArchivalError("future archival host observation makes pacing unavailable")
            delay = max(10.0, delay, latest.delay_seconds if latest else 10.0)
            wait = max(0.0, delay - (now - last).total_seconds()) if last else 0.0
            if time.monotonic() + wait + 5 >= deadline:
                raise ArchivalError("archival host cooldown exceeds remaining request budget")
            if wait:
                time.sleep(wait)
            started = HostObservation(
                request_id=uuid4().hex,
                stage="started",
                observed_at=datetime.now(UTC),
                request_url_sha256=hashlib.sha256(url.encode()).hexdigest(),
                delay_seconds=delay,
            )
            _append(directory, started)
            try:
                yield
            finally:
                _append(
                    directory,
                    started.model_copy(
                        update={"stage": "finished", "observed_at": datetime.now(UTC)}
                    ),
                )
