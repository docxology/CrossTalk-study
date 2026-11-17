"""Atomic publication of rectangular statistical CSV artifacts."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

CSV_ROW_LENGTH: Final = TypeAdapter(int)


def write_csv(path: Path, headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None:
    """Publish one complete CSV without following terminal symlinks."""
    if path.is_symlink():
        message = "statistical CSV target is a symlink"
        raise ValueError(message)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        writer = csv.writer(stream)
        _ = CSV_ROW_LENGTH.validate_python(writer.writerow(headers))
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    _ = temporary.replace(path)
