"""Bounded ordinary file custody and single-process atomic output publication."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from crosstalk.ocr_records import BoundFile, OcrError

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel, JsonValue

MAX_INPUT: Final = 100_000_000
MAX_SELECTION: Final = 256 * 1024 * 1024


def ordinary(path: Path) -> Path:
    """Reject every symlink ancestor; isolated paths must be exact and absolute."""
    if not path.is_absolute() or ".." in path.parts:
        raise OcrError("absolute ordinary OCR file paths are required")
    if any(parent.is_symlink() for parent in (*path.parents, path)):
        raise OcrError("OCR symlink paths are refused")
    return path


def read_bytes(path: Path, maximum: int = MAX_INPUT) -> bytes:
    """Read one bounded independent regular file and recheck identity after reading."""
    _ = ordinary(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise OcrError("OCR input is nonregular, linked or oversized")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identities = tuple(
        (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mode,
            item.st_mtime_ns,
            item.st_ctime_ns,
            item.st_nlink,
        )
        for item in (before, after, path.lstat())
    )
    if len(raw) > maximum or len(raw) != before.st_size or len(set(identities)) != 1:
        raise OcrError("OCR input changed during its bounded read")
    return raw


def checked(root: Path, file: BoundFile) -> bytes:
    """Use the independent selected file digest and size, never a row's source claim."""
    raw = read_bytes(root / file.path)
    if len(raw) != file.size or hashlib.sha256(raw).hexdigest() != file.sha256:
        raise OcrError(f"OCR selected bytes disagree with their independent binding: {file.path}")
    return raw


def binding_digest(files: tuple[BoundFile, ...]) -> str:
    """Canonical closure identity, including exact names, sizes and byte digests."""
    raw = "\n".join(file.model_dump_json() for file in sorted(files, key=lambda item: item.path))
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_selection(root: Path, files: tuple[BoundFile, ...]) -> None:
    """Hash a closed finite selection once per run, refusing duplicate or excessive inputs."""
    if not files or len(files) > 10_000 or len({file.path for file in files}) != len(files):
        raise OcrError("OCR selection must be nonempty, unique and bounded")
    if sum(file.size for file in files) > MAX_SELECTION:
        raise OcrError("OCR selected byte total exceeds 256 MiB")
    for file in files:
        _ = checked(root, file)


def canonical_digest(value: JsonValue) -> str:
    """Match the supervisor's JSON content-envelope seal algorithm."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def publish(path: Path, raw: bytes) -> None:
    """Publish once in a private single-producer namespace without hardlinks or overwrite."""
    _ = ordinary(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise OcrError("occupied OCR output is preserved; replacement refused")
    temporary = path.with_name(f".{uuid4().hex}.partial")
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        _ = stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Isolated compute has one nonforking producer and a new private output tree.
    # A failed partial is retained. No link(), overwrite or partial-cache adoption.
    if path.exists() or path.is_symlink():
        raise OcrError("OCR publication target became occupied; partial preserved")
    _ = temporary.rename(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_record(root: Path, relative: str, record: BaseModel) -> BoundFile:
    """Write a distinct derivative; only supervisor output seals later authorize reuse."""
    raw = (record.model_dump_json() + "\n").encode()
    publish(root / relative, raw)
    return BoundFile(path=relative, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
