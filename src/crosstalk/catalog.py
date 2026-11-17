"""Normalize rendered archive metadata without inventing missing PDF locators."""

import hashlib
import re
from pathlib import Path
from typing import ClassVar, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from crosstalk.models import SERIES_ID, AcquisitionError, require_nps_url, safe_directory
from crosstalk.records import Record, write_records

ISSUED: Final = re.compile(r", (\d{4}(?:-\d{2})?(?:-\d{2})?)\) Show more$")
YEAR: Final = re.compile(r"\b\d{4}\b")


class CatalogLink(BaseModel):
    """Exactly the metadata displayed for one series search result."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    title: str
    url: str
    context: str


class CatalogSnapshot(BaseModel):
    """A dated rendered series observation, not an independent holdings census."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    observed_at: str
    source: str
    reported_total: int
    method: str
    records: tuple[CatalogLink, ...]


class CatalogIssue(Record):
    """Discovered issue metadata; download URLs remain unresolved explicitly."""

    issue_id: str
    item_id: str
    title: str
    issued_metadata: str | None
    landing_url: str
    series_id: str = SERIES_ID
    raw_context: str
    source_snapshot_sha256: str
    flags: tuple[str, ...]
    acquisition_status: str = "pdf-unresolved"


class CatalogSummary(Record):
    """Accounting for one normalized catalog snapshot."""

    records: int
    reported_total: int
    matches_reported_total: bool
    snapshot_sha256: str
    flagged_issue_ids: tuple[str, ...]
    archive_complete: bool = False


def import_catalog(snapshot_path: Path, root: Path) -> CatalogSummary:
    """Keep original context and uncertainty while normalizing the series links."""
    if snapshot_path.stat().st_size > 20_000_000:
        raise AcquisitionError("catalog snapshot exceeds the 20 MB bound")
    raw = snapshot_path.read_bytes()
    snapshot = CatalogSnapshot.model_validate_json(raw)
    if require_nps_url(snapshot.source).split("?", 1)[0] != (
        f"https://calhoun.nps.edu/entities/series/{SERIES_ID}"
    ):
        raise AcquisitionError("catalog snapshot must name the exact CrossTalk series")
    digest = hashlib.sha256(raw).hexdigest()
    rows: list[CatalogIssue] = []
    seen: set[str] = set()
    for link in snapshot.records:
        url = require_nps_url(link.url)
        prefix = "https://calhoun.nps.edu/entities/publication/"
        if not url.startswith(prefix):
            raise AcquisitionError("catalog link must be a Calhoun publication")
        item_id = str(UUID(url.removeprefix(prefix)))
        if item_id in seen:
            raise AcquisitionError("duplicate catalog item UUID")
        seen.add(item_id)
        found = ISSUED.search(link.context)
        issued = found.group(1) if found else None
        title_years = [match.group() for match in YEAR.finditer(link.title)]
        flags: list[str] = []
        if issued is None:
            flags.append("issued-date-unavailable")
        if issued and title_years and issued[:4] != title_years[-1]:
            flags.append("title-metadata-year-conflict")
        rows.append(
            CatalogIssue(
                issue_id=f"ct-{item_id}",
                item_id=item_id,
                title=link.title,
                issued_metadata=issued,
                landing_url=url,
                raw_context=link.context,
                source_snapshot_sha256=digest,
                flags=tuple(flags),
            )
        )
    summary = CatalogSummary(
        records=len(rows),
        reported_total=snapshot.reported_total,
        matches_reported_total=len(rows) == snapshot.reported_total,
        snapshot_sha256=digest,
        flagged_issue_ids=tuple(row.issue_id for row in rows if row.flags),
    )
    directory = safe_directory(root, "data/manifest")
    write_records(directory / "catalog.jsonl", tuple(rows))
    write_records(directory / "catalog-observation.jsonl", (summary,))
    return summary
