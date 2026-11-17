"""Bounded source reads and atomic, non-destructive locator artifact publication."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.catalog import CatalogIssue
from crosstalk.index_observe import IndexReader
from crosstalk.models import SERIES_ID, AcquisitionError, Issue

SAFE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")
MAX_OBSERVATIONS: Final = 100_000


@dataclass(frozen=True, slots=True)
class CatalogState:
    """One content-bound current catalog, not an independent historical denominator."""

    sha256: str
    rows: tuple[CatalogIssue, ...]


@dataclass(frozen=True, slots=True)
class ManifestState:
    """Original manifest bytes and parsed rows; append preserves reviewed originals."""

    raw: bytes | None
    rows: tuple[Issue, ...]


def read_catalog(root: Path) -> CatalogState:
    """Admit unique catalog members and exact Calhoun series/publication identities."""
    reader = IndexReader(root)
    raw = reader.read("data/manifest/catalog.jsonl")
    rows = tuple(
        CatalogIssue.model_validate_json(line) for line in raw.splitlines() if line.strip()
    )
    if (
        len(rows) > 10_000
        or len({row.issue_id for row in rows}) != len(rows)
        or len({row.item_id for row in rows}) != len(rows)
    ):
        raise AcquisitionError("locator catalog is oversized or has duplicate identities")
    for row in rows:
        item = str(UUID(row.item_id))
        if (
            not SAFE_ID.fullmatch(row.issue_id)
            or row.item_id != item
            or row.series_id != SERIES_ID
            or row.landing_url != f"https://calhoun.nps.edu/entities/publication/{item}"
        ):
            raise AcquisitionError("locator catalog identity or exact CrossTalk series is invalid")
    reader.recheck()
    return CatalogState(hashlib.sha256(raw).hexdigest(), rows)


def read_manifest(root: Path) -> ManifestState:
    """Parse bounded original bytes without rewriting or normalizing existing rows."""
    reader = IndexReader(root)
    try:
        raw = reader.read("data/manifest/issues.jsonl")
    except FileNotFoundError:
        return ManifestState(None, ())
    rows = tuple(Issue.model_validate_json(line) for line in raw.splitlines() if line.strip())
    if len(rows) > 10_000 or len({row.issue_id for row in rows}) != len(rows):
        raise AcquisitionError("locator manifest is oversized or has duplicate identities")
    reader.recheck()
    return ManifestState(raw, rows)


def atomic_bytes(path: Path, payload: bytes) -> None:
    """Replace one complete local artifact, preserving mode and refusing aliases."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise AcquisitionError("locator output is a symlink or nonregular file")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".locator-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    _ = Path(temporary).replace(path)
    sync_directory(path.parent)


def immutable_bytes(path: Path, payload: bytes) -> None:
    """Publish a content-addressed observation once; mismatching bytes are preserved."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise AcquisitionError("retained locator observation is not a regular independent file")
    if path.exists():
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise AcquisitionError("retained locator observation is not regular")
            original = stream.read(len(payload) + 1)
        if original != payload:
            raise AcquisitionError(
                "retained locator observation bytes disagree; preserve for review"
            )
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".locator-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    Path(temporary).unlink()
    sync_directory(path.parent)
