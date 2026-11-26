"""Publish complete hydrated directories, retaining every prior ordinary generation."""

from __future__ import annotations

import csv
import fcntl
import io
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from crosstalk.template_io import directory, immutable, physical, project_path, read_file, sha256
from crosstalk.template_records import Binding, ProjectionError

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass(frozen=True, slots=True)
class Document:
    """A complete generated file; all names remain beneath the hydrated manuscript directory."""

    name: str
    raw: bytes


@contextmanager
def projection_lock(root: Path) -> Generator[None]:
    """Serialize this projection publisher; corpus preparation keeps its own project admission."""
    _ = directory(root, "output")
    path = project_path(root, "output/.template-projection.lock")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "rb+") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ProjectionError("projection lock is not an ordinary file")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _current(directory_path: Path) -> tuple[Document, ...]:
    """Refuse aliases, special/nested or oversized prior generated namespaces before moving them."""
    physical(directory_path)
    if not directory_path.is_dir():
        raise ProjectionError("prior hydrated manuscript slot is not a directory")
    files: list[Document] = []
    total = 0
    for path in sorted(directory_path.iterdir()):
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise ProjectionError("prior manuscript contains a nested or special entry")
        raw = read_file(path, 16 * 1024 * 1024)
        total += len(raw)
        if len(files) >= 1000 or total > 256 * 1024 * 1024:
            raise ProjectionError("prior manuscript namespace exceeds its finite bound")
        files.append(Document(path.name, raw))
    return tuple(files)


def _sync(path: Path) -> None:
    """Persist a directory rename before the completed projection is reported."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preserve_previous(root: Path, before: tuple[Document, ...]) -> None:
    """Move the exact observed prior directory, including an empty directory, into history."""
    active = project_path(root, "output/manuscript")
    if not os.path.lexists(active):
        if before:
            raise ProjectionError("previous manuscript disappeared before preservation")
        return
    if _current(active) != before:
        raise ProjectionError("previous manuscript changed before preservation")
    history = directory(root, "output/template-history/" + uuid4().hex)
    _ = active.rename(history / "manuscript")
    _sync(history)


def _allow_native_refresh(directory_path: Path, documents: tuple[Document, ...]) -> None:
    """Native Template refreshes these exact derivative files from unchanged authored sources."""
    for row in documents:
        if row.name != "preamble.md" and not row.name.endswith(".bib"):
            continue
        descriptor = os.open(directory_path / row.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ProjectionError("native refresh target is not an independently owned file")
            if not info.st_mode & stat.S_IWUSR:
                os.fchmod(descriptor, stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
        finally:
            os.close(descriptor)


def publish_manuscript(root: Path, documents: tuple[Document, ...]) -> tuple[Binding, ...]:
    """Exact replay leaves file identities/mtimes; changes archive the entire previous directory.

    A crash between the two directory renames leaves the old generation in history and the new
    complete generation in its owned staging slot. No partial source is accepted as a render.
    """
    if len({row.name for row in documents}) != len(documents):
        raise ProjectionError("generated manuscript repeats a destination")
    for row in documents:
        if Path(row.name).name != row.name or row.name in {"", ".", ".."}:
            raise ProjectionError("generated manuscript destination is not a leaf name")
    active = project_path(root, "output/manuscript")
    before = _current(active) if os.path.lexists(active) else ()
    desired = tuple(sorted(documents, key=lambda row: row.name))
    outputs = tuple(Binding("output/manuscript/" + row.name, sha256(row.raw)) for row in desired)
    if before == desired:
        _allow_native_refresh(active, desired)
        return outputs
    staging_relative = "output/.template-manuscript-" + uuid4().hex
    staging = directory(root, staging_relative)
    for row in desired:
        _ = immutable(root, staging_relative + "/" + row.name, row.raw)
    _allow_native_refresh(staging, desired)
    if _current(staging) != desired:
        raise ProjectionError("prepared manuscript differs from its complete input set")
    _preserve_previous(root, before)
    if os.path.lexists(active):
        raise ProjectionError("manuscript publication slot is occupied; no overwrite occurred")
    _ = staging.rename(active)
    _sync(active.parent)
    return outputs


def publish_generated_file(root: Path, relative: str, raw: bytes) -> Binding:
    """Preserve an earlier generated file before publishing its exact replacement."""
    path = project_path(root, relative)
    _ = directory(root, path.parent.relative_to(root).as_posix())
    if os.path.lexists(path):
        previous = read_file(path)
        if previous == raw:
            return Binding(relative, sha256(raw))
        history = directory(root, "output/template-history/" + uuid4().hex)
        if read_file(path) != previous:
            raise ProjectionError("previous generated file changed before preservation")
        _ = path.rename(history / path.name)
        _sync(history)
    return immutable(root, relative, raw)


def bindings_csv(bindings: tuple[Binding, ...]) -> bytes:
    """The generated directory carries an exact readable source/output identity table."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows((("path", "sha256"),))
    _ = writer.writerows((row.path, row.sha256) for row in bindings)
    return stream.getvalue().encode()
