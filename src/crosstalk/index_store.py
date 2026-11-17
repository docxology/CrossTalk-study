"""Atomic, rebuildable JSONL and SQLite metadata caches, independent of attempt history."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from pydantic import TypeAdapter, ValidationError

from crosstalk.models import AcquisitionError, file_digest, safe_directory

if TYPE_CHECKING:
    from crosstalk.index_records import CorpusIndexRow

METADATA: Final = TypeAdapter(tuple[str, int])
TEXT_ROWS: Final = TypeAdapter(tuple[tuple[str], ...])
MAX_DATABASE_BYTES: Final = 100_000_000


@dataclass(frozen=True, slots=True)
class IndexPublication:
    """Published cache identities, never authoritative acquisition receipts."""

    content_sha256: str
    jsonl_path: str
    sqlite_path: str
    sqlite_sha256: str
    fts5_available: bool


def _existing_database(path: Path, expected: str) -> bool | None:
    """Reuse a database only if ordered stored records reproduce current input bytes."""
    if not path.is_file() or path.stat().st_size > MAX_DATABASE_BYTES:
        return None
    try:
        uri = f"file:{quote(str(path.absolute()))}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            metadata = METADATA.validate_python(
                connection.execute("SELECT content_sha256, fts5_available FROM build").fetchone()
            )
            digest = hashlib.sha256()
            items = TEXT_ROWS.validate_python(
                connection.execute("SELECT record_json FROM issues ORDER BY issue_id").fetchall()
            )
            for item in items:
                text = item[0]
                digest.update(text.encode() + b"\n")
            if metadata[0] == expected and digest.hexdigest() == expected:
                return bool(metadata[1])
    except (sqlite3.DatabaseError, ValidationError):
        return None
    return None


def _atomic_bytes(path: Path, payload: bytes) -> None:
    """Publish complete cache bytes while preserving existing output permissions."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".index-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    _ = Path(temporary).replace(path)


def _database(path: Path, rows: tuple[CorpusIndexRow, ...], digest: str) -> bool:
    """Build a fresh transactional database; metadata-only FTS is optional explicitly."""
    descriptor, name = tempfile.mkstemp(prefix=".index-sqlite-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    with closing(sqlite3.connect(temporary)) as connection, connection:
        _ = connection.execute(
            "CREATE TABLE issues (issue_id TEXT PRIMARY KEY, item_id TEXT UNIQUE NOT NULL, "
            + "title TEXT NOT NULL, issued_metadata TEXT, manifest_member INTEGER NOT NULL, "
            + "pdf_integrity TEXT NOT NULL, extraction_status TEXT NOT NULL, "
            + "duplicate_of_issue_id TEXT, record_json TEXT NOT NULL)"
        )
        _ = connection.executemany(
            "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    row.issue_id,
                    row.item_id,
                    row.title,
                    row.issued_metadata,
                    int(row.manifest_member),
                    row.pdf.integrity,
                    row.extraction.status,
                    row.duplicate_of_issue_id,
                    row.model_dump_json(),
                )
                for row in rows
            ),
        )
        fts = True
        try:
            _ = connection.execute(
                "CREATE VIRTUAL TABLE issue_fts USING fts5(issue_id UNINDEXED, title, context)"
            )
        except sqlite3.OperationalError as error:
            if "no such module: fts5" not in str(error).lower():
                raise
            fts = False
        if fts:
            _ = connection.executemany(
                "INSERT INTO issue_fts VALUES (?, ?, ?)",
                ((row.issue_id, row.title, row.raw_context) for row in rows),
            )
        _ = connection.execute(
            "CREATE TABLE build (content_sha256 TEXT NOT NULL, fts5_available INTEGER NOT NULL)"
        )
        _ = connection.execute("INSERT INTO build VALUES (?, ?)", (digest, int(fts)))
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary.chmod(mode)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    _ = temporary.replace(path)
    return fts


def publish_index(root: Path, rows: tuple[CorpusIndexRow, ...]) -> IndexPublication:
    """Avoid duplicate cache writes when current normalized records are byte-identical."""
    directory = safe_directory(root, "data/processed/index")
    jsonl = directory / "corpus-index.jsonl"
    database = directory / "corpus-index.sqlite"
    if jsonl.is_symlink() or database.is_symlink():
        raise AcquisitionError("index output path is a symlink")
    payload = b"".join(row.model_dump_json().encode() + b"\n" for row in rows)
    digest = hashlib.sha256(payload).hexdigest()
    if not jsonl.exists() or file_digest(jsonl) != digest:
        _atomic_bytes(jsonl, payload)
    fts = _existing_database(database, digest)
    if fts is None:
        fts = _database(database, rows, digest)
    return IndexPublication(
        content_sha256=digest,
        jsonl_path=jsonl.relative_to(root).as_posix(),
        sqlite_path=database.relative_to(root).as_posix(),
        sqlite_sha256=file_digest(database),
        fts5_available=fts,
    )
