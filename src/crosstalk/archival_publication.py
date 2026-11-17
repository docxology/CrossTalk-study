"""Complete only an exact durably prepared payload, preserving unknown aliases and originals."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.archival_records import ArchivalAttempt, ArchivalError, PreparedPayload
from crosstalk.case_files import read_bytes
from crosstalk.models import safe_directory

if TYPE_CHECKING:
    from pathlib import Path

type FileVersion = tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class PayloadFile:
    """A bounded ordinary payload and its independently observed physical file identity."""

    raw: bytes
    device: int
    inode: int
    links: int
    version: FileVersion


def _version(value: os.stat_result) -> FileVersion:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def require_payload_versions(
    target: Path, partial: Path, *, target_version: FileVersion, partial_version: FileVersion
) -> None:
    """Validation only: each current name must equal its own previously checked file version."""
    if _version(target.lstat()) != target_version or _version(partial.lstat()) != partial_version:
        raise ArchivalError("owned archival payload changed after its digest observation")


def _capture(path: Path) -> PayloadFile:
    """Temporarily inspect at most two links; cleanup needs a separate exact owned-pair proof."""
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ArchivalError("prepared archival payload alias refused")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink not in {1, 2}
            or before.st_size > 50_000_000
        ):
            raise ArchivalError("prepared archival payload is nonregular, oversized or aliased")
        raw = stream.read(50_000_001)
        after = os.fstat(stream.fileno())
    if (
        len(raw) > 50_000_000
        or _version(before) != _version(after)
        or (_version(after) != _version(path.lstat()))
    ):
        raise ArchivalError("prepared archival payload changed during observation")
    return PayloadFile(raw, after.st_dev, after.st_ino, after.st_nlink, _version(after))


def _checked(path: Path, bound: PreparedPayload) -> PayloadFile:
    value = _capture(path)
    if len(value.raw) != bound.byte_count or (
        hashlib.sha256(value.raw).hexdigest() != bound.pdf_sha256
    ):
        raise ArchivalError("prepared archival payload digest or byte count changed")
    return value


def stage_payload(root: Path, bound: PreparedPayload, raw: bytes) -> None:
    """Fsync one uniquely named owned partial before its prepared attempt can be committed."""
    if len(raw) != bound.byte_count or hashlib.sha256(raw).hexdigest() != bound.pdf_sha256:
        raise ArchivalError("payload bytes disagree with prepared publication identity")
    directory = safe_directory(root, "output/data/archival/partials")
    partial = root / bound.partial_path
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(directory)
    if _checked(partial, bound).links != 1:
        raise ArchivalError("newly prepared archival partial has an unknown alias")


def _owned_pair(root: Path, bound: PreparedPayload) -> None:
    """Unlink only the exact prepared name after both names prove one two-link inode."""
    partial, target = root / bound.partial_path, root / bound.target_path
    before = _checked(target, bound)
    owned = _checked(partial, bound)
    if (before.device, before.inode, before.links) != (
        owned.device,
        owned.inode,
        owned.links,
    ) or before.links != 2:
        raise ArchivalError("archival target alias is not its exact owned prepared partial")
    require_payload_versions(
        target, partial, target_version=before.version, partial_version=owned.version
    )
    partial.unlink()
    sync_directory(partial.parent)
    sync_directory(target.parent)
    if _checked(target, bound).links != 1:
        raise ArchivalError("completed archival publication still has an unknown alias")


def complete_prepared(root: Path, prepared: ArchivalAttempt) -> bool:
    """Under project_lock, re-read durable provenance before any link or unlink."""
    bound = prepared.publication
    if bound is None or prepared.stage != "prepared":
        raise ArchivalError("owned publication requires an explicit prepared attempt")
    receipt = root / (
        f"output/data/archival/attempts/{prepared.candidate_key}/"
        + f"{prepared.attempt_id}-prepared.json"
    )
    if ArchivalAttempt.model_validate_json(read_bytes(receipt, 32_000)) != prepared:
        raise ArchivalError("durable prepared archival attempt changed")
    partial, target = root / bound.partial_path, root / bound.target_path
    _ = safe_directory(root, "output/data/archival/pdfs")
    if target.is_symlink() or partial.is_symlink():
        raise ArchivalError("owned archival payload alias refused")
    if not target.exists():
        if not partial.exists():
            return False
        if _checked(partial, bound).links != 1:
            raise ArchivalError("unpublished archival partial has an unknown alias")
        os.link(partial, target)
        sync_directory(target.parent)
        _owned_pair(root, bound)
        return True
    observed = _checked(target, bound)
    if observed.links == 2:
        _owned_pair(root, bound)
    elif partial.exists() and _checked(partial, bound).links != 1:
        # An equal independent target grants no authority over another inode.
        raise ArchivalError("retained independent archival partial has an unknown alias")
    return True
