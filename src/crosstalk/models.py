"""Typed corpus inventory and acquisition receipt boundaries."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal, override
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SERIES_ID: Final = "fcb7e5ae-3429-46a2-b3b0-c7865552f1fe"
ALLOWED_HOSTS: Final = frozenset({"calhoun.nps.edu", "crosstalk.nps.edu"})
MAX_MANIFEST_BYTES: Final = 20_000_000
MAX_ISSUES: Final = 10_000
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AcquisitionError(ValueError):
    """Typed refusal; exceptions retain mutable traceback state for context managers."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Retain a typed, contextual acquisition refusal reason."""
        self.reason = reason
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        return self.reason


def require_nps_url(value: str) -> str:
    """Accept explicit HTTPS archive URLs without credentials or path ambiguity."""
    parsed = urlsplit(value)
    decoded = unquote(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
        or value != value.strip()
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or any(part in {".", ".."} for part in decoded.split("/"))
    ):
        raise AcquisitionError("URL must be an unambiguous HTTPS URL on an allowed NPS host")
    return value


class Issue(BaseModel):
    """One explicitly inventoried CrossTalk issue; unknown metadata stays null."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    issue_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    issued: str | None = None
    landing_url: str
    pdf_url: str
    series_id: Literal["fcb7e5ae-3429-46a2-b3b0-c7865552f1fe"] = SERIES_ID
    rights: str | None = None
    volume: str | None = None
    number: str | None = None
    item_id: str | None = None
    kind: Literal["issue"] = "issue"
    sha256: Digest | None = None

    @field_validator("landing_url", "pdf_url")
    @classmethod
    def official_url(cls, value: str) -> str:
        """Parse source URLs once at the inventory boundary."""
        return require_nps_url(value)


class DownloadReceipt(BaseModel):
    """A single acquisition observation, never collection completeness proof."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    issue_id: str
    pdf_url: str
    status: Literal["downloaded", "verified", "failed"]
    path: str
    sha256: Digest | None = None
    expected_sha256: Digest | None = None
    byte_count: int = 0
    error: str | None = None


class DownloadSummary(BaseModel):
    """Source-bound selected-run results; all failures remain explicit."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    manifest_sha256: Digest
    observed_at: str
    selected: int
    inventory_count: int
    receipts: tuple[DownloadReceipt, ...]
    retained_receipts: tuple[DownloadReceipt, ...] = ()
    complete: Literal[False] = False


def load_manifest(path: Path) -> tuple[Issue, ...]:
    """Parse bounded JSONL, refusing duplicates and unrelated series rows."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("inventory must be a regular file")
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise AcquisitionError("inventory exceeds the 20 MB bound")
    issues: list[Issue] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            issue = Issue.model_validate_json(line)
        except ValidationError as error:
            raise AcquisitionError(f"invalid inventory row {number}: {error}") from error
        if issue.issue_id in seen:
            raise AcquisitionError(f"duplicate issue_id on inventory row {number}")
        seen.add(issue.issue_id)
        issues.append(issue)
        if len(issues) > MAX_ISSUES:
            raise AcquisitionError("inventory exceeds the 10,000 issue bound")
    return tuple(issues)


def file_digest(path: Path) -> str:
    """Hash a regular file without following a terminal symlink."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("PDF path is not a regular file")
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_directory(root: Path, relative: str) -> Path:
    """Create project-local output directories while refusing symlink parents."""
    if Path(relative).is_absolute():
        raise AcquisitionError("output directory must be project-local")
    current = root.absolute()
    if current.is_symlink() or not current.is_dir():
        raise AcquisitionError("project root must be an existing physical directory")
    for part in Path(relative).parts:
        if part in {"..", "."}:
            raise AcquisitionError("output directory must be project-local")
        current = current / part
        if current.is_symlink():
            raise AcquisitionError("output directory contains a symlink")
        current.mkdir(exist_ok=True)
    return current


def write_summary(path: Path, summary: DownloadSummary) -> None:
    """Publish a complete receipt atomically, preserving an existing file mode."""
    if path.is_symlink():
        raise AcquisitionError("receipt path is a symlink")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".downloads-", dir=path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        _ = stream.write(summary.model_dump_json(indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    _ = Path(temporary).replace(path)
