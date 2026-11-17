"""Nonblocking project admission shared by acquisition and index publication."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import contextmanager
from typing import TYPE_CHECKING

from crosstalk.models import AcquisitionError, safe_directory

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@contextmanager
def project_lock(root: Path) -> Generator[None]:
    """Hold a real OS lease; persistent lock files are never removed or replaced."""
    path = safe_directory(root, "output/data") / "project-operation.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, "r+b") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("project operation lock must be a regular file")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AcquisitionError(
                "project is busy with another acquisition or index writer"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
