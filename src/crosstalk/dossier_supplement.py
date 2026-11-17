"""Admit a reviewed optional SVG supplement with immutable scientific source bindings."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from crosstalk.case_files import read_bytes, unique_pairs
from crosstalk.dossier_records import DossierFigure, SourceBinding
from crosstalk.models import AcquisitionError
from crosstalk.records import Record

if TYPE_CHECKING:
    from collections.abc import Mapping

type SupplementPath = Literal["manuscript/supplemental-figures.json"]


class SupplementalFigures(Record):
    """The operator supplies reviewed evidence, never a hidden figure-discovery mechanism."""

    schema_version: Literal[1] = 1
    figures: Annotated[tuple[DossierFigure, ...], Field(min_length=1, max_length=12)]
    source_bindings: Annotated[tuple[SourceBinding, ...], Field(min_length=1, max_length=20_000)]


def _physical(root: Path, relative: str, maximum: int = 250_000_000) -> Path:
    """Require canonical relative spelling and physical ordinary single-link source files."""
    parsed = Path(relative)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or parsed.as_posix() != relative
        or ".." in parsed.parts
        or "\\" in relative
    ):
        raise AcquisitionError("supplement source must be a canonical project-relative path")
    path = root.absolute()
    if any(parent.is_symlink() for parent in (*path.parents, path)):
        raise AcquisitionError("supplement project root contains an alias")
    for part in parsed.parts:
        path /= part
        if path.is_symlink():
            raise AcquisitionError("supplement source contains a symlink")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > maximum:
        raise AcquisitionError("supplement source is special, aliased or exceeds its byte bound")
    return path


def _digest(path: Path, maximum: int = 250_000_000) -> str:
    """Bound streamed regular-file bytes and refuse concurrent path/file-version changes."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise AcquisitionError("supplement source is nonregular, aliased or oversized")
        digest = hashlib.sha256()
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise AcquisitionError("supplement source grew beyond its finite byte bound")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    versions = tuple(
        (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        for row in (before, after, path.lstat())
    )
    if len(set(versions)) != 1:
        raise AcquisitionError("supplement source changed during its bounded read")
    return digest.hexdigest()


def _reviewed_scope(bindings: tuple[SourceBinding, ...]) -> None:
    """Require the declared scientific frame and its raw/native, method and immutable evidence."""
    names = {row.path for row in bindings}
    pdfs = {
        name.removeprefix("data/raw/pdf/").removesuffix(".pdf")
        for name in names
        if name.startswith("data/raw/pdf/") and name.endswith(".pdf")
    }
    native = {
        name.removeprefix("data/processed/pages/").removesuffix(".jsonl")
        for name in names
        if name.startswith("data/processed/pages/") and name.endswith(".jsonl")
    }
    if (
        len(names) != len(bindings)
        or not {"data/manifest/catalog.jsonl", "data/manifest/issues.jsonl"} <= names
        or not pdfs
        or pdfs != native
        or not any(
            name.startswith(("src/", "optional/")) and name.endswith(".py") for name in names
        )
        or not any(name.startswith("output/data/") for name in names)
    ):
        raise AcquisitionError(
            "supplement needs unique reviewed catalog/raw/native/method/proof bindings"
        )
    if any(
        name.startswith(
            (
                "data/processed/index/",
                "output/reports/",
            )
        )
        for name in names
    ):
        raise AcquisitionError("supplement cannot depend on mutable index/report pointers")


@dataclass(frozen=True, slots=True)
class DossierSupplement:
    """Only verified figure paths and their full immutable evidence enter the final dossier."""

    figures: tuple[DossierFigure, ...]
    bindings: tuple[SourceBinding, ...]

    def recheck(self, root: Path) -> None:
        """Recheck manifest, figure and source bytes before document publication."""
        for binding in self.bindings:
            path = _physical(root, binding.path)
            if _digest(path) != binding.sha256:
                raise AcquisitionError("supplement source or SVG changed before publication")


def _proposed_bindings(
    manifest: SupplementalFigures,
    relative: SupplementPath,
    raw: bytes,
) -> tuple[SourceBinding, ...]:
    """Unique reviewed identities include an independently measured manifest seal."""
    paths = tuple(figure.path for figure in manifest.figures)
    if len(set(paths)) != len(paths) or len({row.sha256 for row in manifest.figures}) != len(paths):
        raise AcquisitionError("supplement repeats a figure path or identical SVG")
    proposed = {row.path: row.sha256 for row in manifest.source_bindings}
    for figure in manifest.figures:
        if figure.path in proposed and proposed[figure.path] != figure.sha256:
            raise AcquisitionError("supplement SVG conflicts with its source binding")
        proposed[figure.path] = figure.sha256
    if relative in proposed:
        raise AcquisitionError("supplement cannot self-declare its own manifest digest")
    proposed[relative] = hashlib.sha256(raw).hexdigest()
    return tuple(
        SourceBinding(path=name, sha256=digest) for name, digest in sorted(proposed.items())
    )


def supplemental_evidence(
    root: Path,
    relative: SupplementPath | None,
    observed: Mapping[Path, str],
) -> DossierSupplement:
    """Read exactly the configured reviewed manifest, preserving earlier source observations."""
    if relative is None:
        return DossierSupplement((), ())
    manifest_path = _physical(root, relative, 5_000_000)
    raw = read_bytes(manifest_path, 5_000_000)
    if json.loads(raw, object_pairs_hook=unique_pairs) is None:
        raise AcquisitionError("supplement manifest must be an object")
    manifest = SupplementalFigures.model_validate_json(raw)
    _reviewed_scope(manifest.source_bindings)
    paths = tuple(figure.path for figure in manifest.figures)
    if any(root / name in observed for name in paths):
        raise AcquisitionError("supplement figure duplicates an earlier dossier figure")
    bindings = _proposed_bindings(manifest, relative, raw)
    for binding in bindings:
        name, expected = binding.path, binding.sha256
        path = _physical(root, name, 5_000_000 if name in paths else 250_000_000)
        captured = observed.get(root / name)
        if captured is not None and captured != expected:
            raise AcquisitionError("supplement conflicts with an earlier dossier source binding")
        if (captured if captured is not None else _digest(path)) != expected:
            raise AcquisitionError("supplement source or SVG disagrees with its reviewed digest")
    return DossierSupplement(manifest.figures, bindings)
