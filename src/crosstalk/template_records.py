"""Typed, standard-library inputs for the native Template manuscript projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    from pathlib import Path

Digest = NewType("Digest", str)


class ProjectionError(ValueError):
    """A concrete source, format or publication refusal preserves its original inputs."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Retain the concrete refusal reason for callers and structured reports."""
        self.reason = reason
        super().__init__(reason)


class RowKind(StrEnum):
    """The complete version-one CSV manifest vocabulary."""

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    INVENTORY = "inventory"
    GA01 = "ga01"
    GA02 = "ga02"
    GA03 = "ga03"
    GA04 = "ga04"
    FIGURE = "figure"
    RECEIPT = "receipt"


class ScalarKind(StrEnum):
    """Only precomputed display scalars belong to manuscript variables."""

    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"


@dataclass(frozen=True, slots=True)
class ManifestSelection:
    """The manifest digest is supplied independently, never calculated as permission."""

    path: Path
    sha256: Digest


@dataclass(frozen=True, slots=True)
class ProjectionRequest:
    """One physical project and one explicitly selected precomputed study manifest."""

    root: Path
    selection: ManifestSelection


@dataclass(frozen=True, slots=True)
class Variable:
    """A precomputed scalar and its declared representation; no result is inferred."""

    key: str
    kind: ScalarKind
    value: str


@dataclass(frozen=True, slots=True)
class Artifact:
    """One current content reference, with source-owned figure text when applicable."""

    kind: RowKind
    key: str
    path: str
    sha256: Digest
    title: str
    caption: str
    alt: str


@dataclass(frozen=True, slots=True)
class Manifest:
    """Variables, one PDF-source inventory, figures and independently retained receipts."""

    variables: tuple[Variable, ...]
    inventory: Artifact
    graphical_abstracts: tuple[Artifact, ...]
    figures: tuple[Artifact, ...]
    receipts: tuple[Artifact, ...]


@dataclass(frozen=True, slots=True)
class Binding:
    """Exact relative-path content identity; this is not a claim of semantic validation."""

    path: str
    sha256: Digest


@dataclass(frozen=True, slots=True)
class ProjectionRun:
    """Measured projection accounting remains separate from article review and OCR accuracy."""

    manifest_sha256: Digest
    projection_sha256: Digest
    inventory_rows: int
    body_figures: int
    bindings: tuple[Binding, ...]
    outputs: tuple[Binding, ...]
