"""Bound actual native distribution bytes, including extension and shared-library files."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Final

from crosstalk.models import AcquisitionError

MAX_RUNTIME_FILES: Final = 1000
MAX_RUNTIME_BYTES: Final = 100_000_000


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """Canonical name/content identity is independent of installation location and mtimes."""

    sha256: str
    files: tuple[str, ...]
    byte_count: int


def _path(site: Path, relative: str) -> Path:
    parsed = Path(relative)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts or "\\" in relative:
        raise AcquisitionError("Native distribution path escapes its installation root")
    path = site
    if site.is_symlink():
        raise AcquisitionError("Native distribution root is an alias")
    for part in parsed.parts:
        path /= part
        if path.is_symlink():
            raise AcquisitionError("Native distribution file contains a symlink")
    return path


def _file_identity(path: Path) -> tuple[str, int]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RUNTIME_BYTES:
            raise AcquisitionError("Native distribution file is nonregular or oversized")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AcquisitionError("Native distribution bytes changed while hashing")
    return digest, after.st_size


def _record(site: Path, metadata: str) -> bytes:
    path = _path(site, metadata + "/RECORD")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("Native distribution RECORD is nonregular")
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise AcquisitionError("Native distribution RECORD exceeds its1MB bound")
    return raw


def _members(raw: bytes, metadata: str) -> tuple[tuple[str, str, int | None], ...]:
    rows: list[tuple[str, str, int | None]] = []
    for row in csv.reader(io.StringIO(raw.decode())):
        if len(row) != 3:
            raise AcquisitionError("Native distribution RECORD row is malformed")
        name, expected, size = row
        if "__pycache__" in Path(name).parts:
            continue
        if not name.startswith(("pymupdf/", metadata + "/")):
            continue
        count = int(size) if size else None
        if count is not None and not 0 <= count <= MAX_RUNTIME_BYTES:
            raise AcquisitionError("Native distribution RECORD size is outside its bound")
        if name != metadata + "/RECORD" and not expected:
            raise AcquisitionError("Native distribution member lacks its recorded digest")
        if expected and not expected.startswith("sha256="):
            raise AcquisitionError("Native distribution RECORD uses an unsupported digest")
        rows.append((name, expected, count))
        if len(rows) > MAX_RUNTIME_FILES:
            raise AcquisitionError("Native distribution exceeds its1000-file bound")
    names = tuple(row[0] for row in rows)
    if not rows or len(set(names)) != len(names) or metadata + "/RECORD" not in names:
        raise AcquisitionError("Native distribution RECORD is empty, duplicated or incomplete")
    return tuple(rows)


def runtime_identity(site: Path, version: str) -> RuntimeIdentity:
    """Verify bounded actual installed files against RECORD, then hash their exact closure."""
    if re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,63}", version) is None:
        raise AcquisitionError("Native distribution version cannot identify safe metadata")
    metadata = f"pymupdf-{version}.dist-info"
    record = _record(site, metadata)
    members = _members(record, metadata)
    _membership(site, metadata, tuple(row[0] for row in members))
    aggregate = hashlib.sha256()
    total = 0
    names: list[str] = []
    for name, expected, expected_size in sorted(members):
        path = _path(site, name)
        if total + path.stat().st_size > MAX_RUNTIME_BYTES:
            raise AcquisitionError("Native distribution closure exceeds its100MB bound")
        digest, size = _file_identity(path)
        if expected:
            encoded = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=")
            if expected != "sha256=" + encoded or size != expected_size:
                raise AcquisitionError("Native distribution member differs from RECORD")
        aggregate.update(
            name.encode() + b"\0" + str(size).encode() + b"\0" + bytes.fromhex(digest) + b"\0"
        )
        total += size
        names.append(name)
    if _record(site, metadata) != record:
        raise AcquisitionError("Native distribution membership changed while hashing")
    return RuntimeIdentity(aggregate.hexdigest(), tuple(names), total)


def _membership(site: Path, metadata: str, expected: tuple[str, ...]) -> None:
    """Unrecorded native/import files cannot silently shadow the recorded runtime closure."""
    observed: set[str] = set()
    for folder in ("pymupdf", metadata):
        root = _path(site, folder)
        paths = tuple(islice(root.rglob("*"), 2 * MAX_RUNTIME_FILES + 1))
        if len(paths) > 2 * MAX_RUNTIME_FILES:
            raise AcquisitionError("Native distribution namespace exceeds its traversal bound")
        for path in paths:
            relative = path.relative_to(site)
            if "__pycache__" in relative.parts:
                continue
            if path.is_symlink():
                raise AcquisitionError("Native distribution namespace contains a symlink")
            if path.is_file():
                observed.add(relative.as_posix())
            elif not path.is_dir():
                raise AcquisitionError("Native distribution namespace contains a nonregular file")
    if observed != set(expected):
        raise AcquisitionError("Native distribution namespace differs from recorded membership")
