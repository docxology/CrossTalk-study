"""Parse one expected-SHA CSV contract without importing the analysis runtime or models."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, assert_never

from crosstalk.template_io import digest
from crosstalk.template_records import (
    Artifact,
    Manifest,
    ProjectionError,
    RowKind,
    ScalarKind,
    Variable,
)

HEADER: Final = ("kind", "key", "path", "sha256", "value", "title", "caption", "alt")
GA_KINDS: Final = (RowKind.GA01, RowKind.GA02, RowKind.GA03, RowKind.GA04)
MAX_BODY_FIGURES: Final = 128


def scalar(key: str, kind: ScalarKind, value: str) -> Variable:
    """Parse finite precomputed display values while preserving their original precision."""
    if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", key) is None or len(value) > 8000:
        raise ProjectionError("invalid scalar key or oversized display value")
    if any(ord(char) < 32 for char in value):
        raise ProjectionError("display variables must be single-line plain text")
    match kind:
        case ScalarKind.TEXT:
            pass
        case ScalarKind.INTEGER:
            if re.fullmatch(r"-?(0|[1-9][0-9]{0,29})", value) is None:
                raise ProjectionError("integer variable has no canonical decimal representation")
        case ScalarKind.DECIMAL:
            try:
                number = Decimal(value)
            except InvalidOperation as exc:
                raise ProjectionError("decimal variable is malformed") from exc
            if not number.is_finite():
                raise ProjectionError("decimal variable is not finite")
        case _:
            assert_never(kind)
    return Variable(key, kind, value)


def artifact(row: list[str], kind: RowKind) -> Artifact:
    """Restrict current references to declared data/figure/report namespaces."""
    _, key, path, expected, value, title, caption, alt = row
    relative = Path(path)
    if (
        re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", key) is None
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != path
        or len(path) > 500
        or value
        or any(len(text) > 8000 or "\n" in text or "\r" in text for text in (title, caption, alt))
    ):
        raise ProjectionError("artifact reference has an invalid name, path or text field")
    match kind:
        case RowKind.GA01 | RowKind.GA02 | RowKind.GA03 | RowKind.GA04 | RowKind.FIGURE:
            if relative.parts[:2] != ("output", "figures"):
                raise ProjectionError(
                    "figures must be generated figure assets, never an old book/PDF"
                )
            if relative.name.startswith("frontmatter-page-"):
                raise ProjectionError(
                    "prior rendered book pages cannot stand in for graphical abstracts"
                )
            if relative.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg"}:
                raise ProjectionError("native figures need precomputed PDF/PNG/JPEG assets")
            if not all(text.strip() for text in (title, caption, alt)):
                raise ProjectionError(
                    "each figure needs source-owned title, caption and alternative text"
                )
        case RowKind.INVENTORY | RowKind.RECEIPT:
            if relative.parts[:2] not in {("output", "data"), ("output", "reports")}:
                raise ProjectionError(
                    "inventory/receipt must be retained beneath output/data or reports"
                )
        case RowKind.TEXT | RowKind.INTEGER | RowKind.DECIMAL:
            raise ProjectionError("scalar cannot be parsed as an artifact")
        case _:
            assert_never(kind)
    return Artifact(kind, key, path, digest(expected), title, caption, alt)


def parse_manifest(raw: bytes) -> Manifest:
    """Require one inventory, four distinct graphical abstracts and explicit ordered figures."""
    if len(raw) > 16 * 1024 * 1024:
        raise ProjectionError("manifest exceeds sixteen MiB")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(next(reader, ())) != HEADER:
        raise ProjectionError("unsupported CSV manifest header")
    variables: list[Variable] = []
    references: list[Artifact] = []
    keys: set[str] = set()
    for index, row in enumerate(reader, 1):
        if index > 25000 or len(row) != len(HEADER) or row[1] in keys:
            raise ProjectionError("manifest exceeds bounds or repeats a key")
        keys.add(row[1])
        try:
            kind = RowKind(row[0])
        except ValueError as exc:
            raise ProjectionError("unknown manifest row kind") from exc
        match kind:
            case RowKind.TEXT | RowKind.INTEGER | RowKind.DECIMAL:
                if any(row[column] for column in (2, 3, 5, 6, 7)):
                    raise ProjectionError("scalar row contains artifact fields")
                variables.append(scalar(row[1], ScalarKind(kind.value), row[4]))
            case (
                RowKind.INVENTORY
                | RowKind.GA01
                | RowKind.GA02
                | RowKind.GA03
                | RowKind.GA04
                | RowKind.FIGURE
                | RowKind.RECEIPT
            ):
                references.append(artifact(row, kind))
            case _:
                assert_never(kind)
    inventories = tuple(row for row in references if row.kind == RowKind.INVENTORY)
    gas = tuple(row for kind in GA_KINDS for row in references if row.kind == kind)
    figures = tuple(row for row in references if row.kind == RowKind.FIGURE)
    receipts = tuple(row for row in references if row.kind == RowKind.RECEIPT)
    if (
        len(inventories) != 1
        or len(gas) != 4
        or {row.kind for row in gas} != set(GA_KINDS)
        or len({row.sha256 for row in gas}) != 4
        or not figures
        or len(figures) > MAX_BODY_FIGURES
        or not receipts
    ):
        raise ProjectionError(
            "need one inventory, four distinct GA assets, "
            + f"1 to {MAX_BODY_FIGURES} body figures, and receipts"
        )
    return Manifest(tuple(variables), inventories[0], gas, figures, receipts)
