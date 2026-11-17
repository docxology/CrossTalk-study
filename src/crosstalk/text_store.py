"""Small SQLite adapter for deterministic, private page-text indexing."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from crosstalk.models import AcquisitionError
from crosstalk.search_records import SearchHit

if TYPE_CHECKING:
    from crosstalk.search_records import IndexedPage

HITS: Final = TypeAdapter(tuple[tuple[str, str, str, str, int, str, str], ...])
COUNT: Final = TypeAdapter(tuple[int])


def write_page_database(path: Path, pages: tuple[IndexedPage, ...]) -> bool:
    """Atomically replace a derived database, preserving the existing file mode."""
    if path.is_symlink():
        raise AcquisitionError("page-search database path is a symlink")
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".page-search-", dir=path.parent)
    with os.fdopen(descriptor, "wb"):
        pass
    with closing(sqlite3.connect(temporary)) as database, database:
        _ = database.execute(
            "CREATE TABLE pages (issue_id TEXT NOT NULL, title TEXT NOT NULL, "
            + "source_url TEXT NOT NULL, source_sha256 TEXT NOT NULL, page_index INTEGER NOT NULL, "
            + "page_label TEXT NOT NULL, text TEXT NOT NULL, UNIQUE(issue_id,page_index))"
        )
        _ = database.executemany(
            "INSERT INTO pages VALUES (?,?,?,?,?,?,?)",
            (
                (
                    page.issue_id,
                    page.title,
                    page.source_url,
                    page.source_sha256,
                    page.page_index,
                    page.page_label,
                    page.text,
                )
                for page in pages
            ),
        )
        available = True
        try:
            _ = database.execute(
                "CREATE VIRTUAL TABLE page_fts USING fts5(text, "
                + "content='pages', content_rowid='rowid', "
                + "tokenize='unicode61 remove_diacritics 0')"
            )
        except sqlite3.OperationalError as error:
            if "no such module: fts5" not in str(error).lower():
                raise
            available = False
        if available:
            _ = database.execute("INSERT INTO page_fts(rowid,text) SELECT rowid,text FROM pages")
    with Path(temporary).open("rb") as stream:
        os.fsync(stream.fileno())
    Path(temporary).chmod(mode)
    _ = Path(temporary).replace(path)
    return available


def query_page_database(
    path: Path, expression: str, limit: int
) -> tuple[int, tuple[SearchHit, ...]]:
    """Keep dynamic DB-API returns at one parsed dependency boundary."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        count_cursor = database.execute(
            "SELECT count(*) FROM page_fts WHERE page_fts MATCH ?", (expression,)
        )
        count = COUNT.validate_python(getattr(count_cursor, "fetchone")())[0]  # noqa: B009
        cursor = database.execute(
            """SELECT p.issue_id,p.title,p.source_url,p.source_sha256,p.page_index,p.page_label,
            snippet(page_fts,0,'','',' ... ',22) FROM page_fts JOIN pages p
            ON p.rowid=page_fts.rowid WHERE page_fts MATCH ?
            ORDER BY bm25(page_fts),p.issue_id,p.page_index LIMIT ?""",
            (expression, limit),
        )
        rows = HITS.validate_python(getattr(cursor, "fetchall")())  # noqa: B009
    return count, tuple(
        SearchHit(
            issue_id=row[0],
            title=row[1],
            source_url=row[2],
            source_sha256=row[3],
            page_index=row[4],
            page_label=row[5],
            excerpt=row[6],
        )
        for row in rows
    )
