"""Bounded ordinary reads and duplicate-key rejection for curated case inputs."""

from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING

from crosstalk.case_records import CaseError, Ledger

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue


def read_bytes(path: Path, maximum: int = 1_000_000) -> bytes:
    """Refuse all symlink ancestors and special files before a finite independent read."""
    if not path.is_absolute() or any(part.is_symlink() for part in (*path.parents, path)):
        raise CaseError("case inputs require ordinary absolute paths")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        version = os.fstat(stream.fileno())
        if not stat.S_ISREG(version.st_mode) or version.st_nlink != 1 or version.st_size > maximum:
            raise CaseError("case input is nonregular, aliased or exceeds its byte bound")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise CaseError("case input grew beyond its finite byte bound")
    return raw


def unique_pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """JSON's last-value-wins behavior cannot resolve conflicting curated evidence."""
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise CaseError("duplicate JSON key in case ledger")
        result[key] = value
    return result


def parse_ledger(raw: bytes) -> Ledger:
    """Check duplicate members first, then use strict typed JSON parsing."""
    if json.loads(raw, object_pairs_hook=unique_pairs) is None:
        raise CaseError("case ledger must be an object rather than null")
    return Ledger.model_validate_json(raw)
