"""Bounded physical input reads and append-only content publication for native manuscripts."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Final

from crosstalk.template_records import Binding, Digest, ProjectionError

MAX_FILE_BYTES: Final = 128 * 1024 * 1024


def digest(value: str) -> Digest:
    """Parse one externally supplied SHA-256 without normalizing unknown input."""
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProjectionError("expected a lowercase SHA-256 digest")
    return Digest(value)


def sha256(raw: bytes) -> Digest:
    """Content identity does not by itself establish source or scientific validity."""
    return Digest(hashlib.sha256(raw).hexdigest())


def physical(path: Path) -> None:
    """Reject aliases before reading or publishing a declared project artifact."""
    if not path.is_absolute() or ".." in path.parts:
        raise ProjectionError("input/output path is not an absolute physical pathname")
    if any(parent.is_symlink() for parent in (*path.parents, path)):
        raise ProjectionError("input/output path follows a symlink")


def project_path(root: Path, relative: str) -> Path:
    """Accept only canonical relative spellings inside the selected physical project."""
    name = Path(relative)
    if name.is_absolute() or ".." in name.parts or name.as_posix() != relative or not name.parts:
        raise ProjectionError("artifact path is not an ordinary project-relative name")
    path = root / name
    physical(path)
    return path


def read_file(path: Path, maximum: int = MAX_FILE_BYTES) -> bytes:
    """Read a bounded regular file with descriptor and path identity checks."""
    physical(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ProjectionError("selected input is special or exceeds its byte bound")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    versions = {
        (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        for row in (before, after, current)
    }
    if len(raw) > maximum or len(versions) != 1:
        raise ProjectionError("selected input changed during its bounded read")
    return raw


def selected(root: Path, binding: Binding) -> bytes:
    """A current artifact must match the independently selected manifest content reference."""
    raw = read_file(project_path(root, binding.path))
    if sha256(raw) != binding.sha256:
        raise ProjectionError("selected artifact differs from its pinned SHA-256")
    return raw


def directory(root: Path, relative: str) -> Path:
    """Create only ordinary directories; preserve occupied aliases and special slots."""
    target = project_path(root, relative)
    for path in reversed((target, *target.parents)):
        if not path.is_relative_to(root):
            continue
        try:
            path.mkdir()
        except FileExistsError:
            if not stat.S_ISDIR(path.stat(follow_symlinks=False).st_mode):
                raise ProjectionError("output directory is occupied by a non-directory") from None
        physical(path)
    return target


def immutable(root: Path, relative: str, raw: bytes) -> Binding:
    """Publish only complete bytes and retain failed writes outside the final slot."""
    path = project_path(root, relative)
    binding = Binding(relative, sha256(raw))
    _ = directory(root, path.parent.relative_to(root).as_posix())
    if os.path.lexists(path):
        if read_file(path) != raw:
            raise ProjectionError("occupied immutable output differs; original bytes preserved")
        return binding
    descriptor, temporary = tempfile.mkstemp(prefix=".template-artifact-", dir=path.parent)
    staged = Path(temporary)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(raw)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())
    try:
        os.link(staged, path, follow_symlinks=False)
    except FileExistsError:
        if read_file(path) != raw:
            raise ProjectionError(
                "occupied immutable output differs; original bytes preserved"
            ) from None
    staged.unlink()
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return binding
