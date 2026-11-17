"""Physical publisher dataset custody, separate from the NPS project namespace."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from crosstalk.locator_storage import publish_metadata
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.records import Record, write_records

if TYPE_CHECKING:
    from pydantic import BaseModel


class PublisherDatasetMarker(Record):
    """A fixed family marker cannot turn an unrelated pre-existing tree into this dataset."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    schema_version: Literal[1] = 1


def publisher_path(root: Path, relative: str) -> Path:
    """Refuse aliases and traversal in every dataset-local path component."""
    parsed = Path(relative)
    if (
        any(parent.is_symlink() for parent in (root, *root.parents))
        or not root.is_dir()
        or parsed.is_absolute()
        or ".." in parsed.parts
    ):
        raise AcquisitionError("publisher paths require a physical contained dataset root")
    current = root
    for part in parsed.parts:
        current /= part
        if current.is_symlink():
            raise AcquisitionError("publisher dataset path contains a symlink")
    return current


def read_publisher_bytes(root: Path, relative: str, maximum: int = 1_000_000) -> bytes:
    """Admit bounded ordinary metadata, refusing foreign hardlink aliases and special files."""
    if not 1 <= maximum <= 20_000_000:
        raise AcquisitionError("publisher metadata read bound must be between 1 and 20 MB")
    path = publisher_path(root, relative)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AcquisitionError("publisher metadata must be an independent regular file")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > maximum or (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
        after.st_dev,
    ):
        raise AcquisitionError("publisher metadata is oversized or changed while read")
    return raw


def publisher_dataset(project: Path) -> Path:
    """Open one publisher-only root using the core extractor's standard internal layout."""
    root = safe_directory(project, "data/publisher")
    marker = root / "publisher-dataset.json"
    expected = PublisherDatasetMarker().model_dump_json().encode() + b"\n"
    if marker.exists() or marker.is_symlink():
        observed = read_publisher_bytes(root, marker.name)
        _ = PublisherDatasetMarker.model_validate_json(observed)
        if observed != expected:
            raise AcquisitionError("publisher dataset marker has conflicting original bytes")
    else:
        if any(root.iterdir()):
            raise AcquisitionError("unmarked publisher dataset is occupied; originals preserved")
        _ = publish_metadata(root, marker.name, expected)
    return root


def publish_publisher_records(root: Path, relative: str, records: tuple[BaseModel, ...]) -> None:
    """Preserve unchanged complete metadata while refusing aliases before replacement."""
    path = publisher_path(root, relative)
    encoded = b"".join(row.model_dump_json().encode() + b"\n" for row in records)
    try:
        existing = read_publisher_bytes(root, relative, max(len(encoded), 1_000_000))
    except FileNotFoundError:
        existing = None
    if existing != encoded:
        write_records(path, records)
