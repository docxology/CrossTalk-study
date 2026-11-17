"""Index a checksum-pinned publisher CD-ROM archive without extracting paths."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from io import BytesIO
from pathlib import Path
from typing import Final, TypedDict, cast

import pymupdf
from PIL import Image
from pydantic import TypeAdapter

from crosstalk.appearance_render import NativePixmap
from crosstalk.pdf_adapter import page_geometry

_MEMBERS = re.compile(
    r"xtalk/(?:Xtalk9[1-9]\.pdf|Xtmain\.pdf|(?:1999|2000)/\d{2}(?:\.pdf|cov\.(?:gif|jpg)))"
)
_DIRECTORIES = {"xtalk/1999/", "xtalk/2000/"}
_MAXIMUM_MEMBER = 32 * 1024 * 1024
_MAXIMUM_TOTAL = 128 * 1024 * 1024
_MAXIMUM_ARCHIVE = 128 * 1024 * 1024
_PLAIN_TEXT: Final = TypeAdapter(str)
_INDEX_SCHEMA = """
CREATE TABLE members(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
                     crc32 TEXT NOT NULL, media_type TEXT NOT NULL, positions INTEGER NOT NULL);
CREATE TABLE positions(path TEXT NOT NULL REFERENCES members(path), ordinal INTEGER NOT NULL,
                       text_sha256 TEXT NOT NULL, tokens INTEGER NOT NULL, width REAL NOT NULL,
                       height REAL NOT NULL, mean_gray REAL NOT NULL, dark_pixels INTEGER NOT NULL,
                       total_pixels INTEGER NOT NULL, raster_sha256 TEXT NOT NULL,
                       PRIMARY KEY(path, ordinal));
CREATE VIRTUAL TABLE text_search USING fts5(path UNINDEXED, ordinal UNINDEXED, content);
"""

type _MemberFields = tuple[str, str, int, str]


class _IndexCounts(TypedDict):
    members: int
    pdfs: int | None
    covers: int | None
    positions: int | None
    pdf_pages: int
    text_pages: int | None


class ArchiveIndexReceipt(_IndexCounts):
    """Source and output byte identities with the index counts."""

    archive_sha256: str
    index_sha256: str


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _member_infos(source: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = source.infolist()
    if len(members) > 64 or sum(info.file_size for info in members) > _MAXIMUM_TOTAL:
        raise ValueError("Archive exceeds the CD-ROM analysis envelope")
    names: set[str] = set()
    for info in members:
        name = info.filename
        name_allowed = (
            name in _DIRECTORIES if info.is_dir() else _MEMBERS.fullmatch(name) is not None
        )
        if (
            name in names
            or name != info.orig_filename
            or info.flag_bits & 1
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.file_size > _MAXIMUM_MEMBER
            or not name_allowed
        ):
            raise ValueError(f"Unsupported or duplicate archive entry: {name!r}")
        names.add(name)
    return sorted((info for info in members if not info.is_dir()), key=lambda info: info.filename)


def _add_position(
    db: sqlite3.Connection,
    loc: tuple[str, int],
    text: str,
    size: tuple[float, float],
    gray: Image.Image,
) -> None:
    path, ordinal = loc
    width, height = size
    histogram = gray.histogram()
    pixels = gray.width * gray.height
    raster = gray.width.to_bytes(4, "big") + gray.height.to_bytes(4, "big") + gray.tobytes()
    _ = db.execute(
        "INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            path,
            ordinal,
            _sha(text.encode()),
            len(re.findall(r"[^\W_]+", text)),
            width,
            height,
            sum(i * count for i, count in enumerate(histogram)) / pixels,
            sum(histogram[:96]),
            pixels,
            _sha(raster),
        ),
    )
    if text.strip():
        _ = db.execute("INSERT INTO text_search VALUES (?, ?, ?)", (path, ordinal, text))


def _index_pdf(db: sqlite3.Connection, fields: _MemberFields, raw: bytes) -> None:
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        _ = db.execute(
            "INSERT INTO members VALUES (?, ?, ?, ?, 'pdf', ?)", (*fields, len(document))
        )
        for page_index in range(len(document)):
            page = document[page_index]
            pix = NativePixmap.model_validate(
                getattr(page, "get_pixmap")(  # noqa: B009 -- Parse the partial native API.
                    dpi=36, colorspace=pymupdf.csGRAY, alpha=False
                )
            )
            text = _PLAIN_TEXT.validate_python(
                getattr(page, "get_text")(sort=True)  # noqa: B009 -- Parse the native text result.
            )
            geometry = page_geometry(page)
            with Image.frombytes("L", (pix.width, pix.height), pix.samples) as gray:
                _add_position(
                    db, (fields[0], page_index + 1), text, (geometry.width, geometry.height), gray
                )


def _index_cover(db: sqlite3.Connection, fields: _MemberFields, raw: bytes) -> None:
    with Image.open(BytesIO(raw)) as cover, cover.convert("L") as gray:
        _ = db.execute("INSERT INTO members VALUES (?, ?, ?, ?, 'cover', 1)", fields)
        _add_position(db, (fields[0], 1), "", (float(gray.width), float(gray.height)), gray)


def _counts(db: sqlite3.Connection) -> _IndexCounts:
    members, pdfs, covers, positions = cast(
        "tuple[int, int | None, int | None, int | None]",
        db.execute("""
            SELECT count(*), sum(media_type='pdf'), sum(media_type='cover'), sum(positions)
            FROM members
            """).fetchone(),
    )
    pdf_pages, text_pages = cast(
        "tuple[int, int | None]",
        db.execute("""
            SELECT count(*), sum(tokens>0) FROM positions JOIN members USING(path)
            WHERE media_type='pdf'
            """).fetchone(),
    )
    return {
        "members": members,
        "pdfs": pdfs,
        "covers": covers,
        "positions": positions,
        "pdf_pages": pdf_pages,
        "text_pages": text_pages,
    }


def _catalogue(db: sqlite3.Connection, archive: bytes) -> _IndexCounts:
    _ = db.executescript(_INDEX_SCHEMA)
    with zipfile.ZipFile(BytesIO(archive)) as source, db:
        for info in _member_infos(source):
            raw = source.read(info)
            path = info.filename
            fields = (path, _sha(raw), len(raw), f"{info.CRC:08x}")
            if path.endswith(".pdf"):
                _index_pdf(db, fields, raw)
            else:
                _index_cover(db, fields, raw)
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    return _counts(db)


def build(archive_path: Path, expected_sha256: str, index: Path) -> ArchiveIndexReceipt:
    """Build and publish an archive index while retaining any conflicting output."""
    with archive_path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size > _MAXIMUM_ARCHIVE:
            raise ValueError("Publisher archive exceeds the raw byte limit")
        archive = stream.read(_MAXIMUM_ARCHIVE + 1)
    if len(archive) > _MAXIMUM_ARCHIVE:
        raise ValueError("Publisher archive exceeds the raw byte limit")
    if _sha(archive) != expected_sha256:
        raise ValueError("Publisher archive checksum does not match the accession")
    with tempfile.TemporaryDirectory(prefix=".ase-index-", dir=index.parent) as temporary:
        candidate = Path(temporary) / index.name
        with closing(sqlite3.connect(candidate)) as db:
            counts = _catalogue(db, archive)
        digest = _sha(candidate.read_bytes())
        try:
            os.link(candidate, index)
        except FileExistsError:
            if index.is_symlink() or _sha(index.read_bytes()) != digest:
                raise ValueError(
                    "Refusing to replace an existing nonmatching archive index"
                ) from None
    return {"archive_sha256": expected_sha256, "index_sha256": digest, **counts}
