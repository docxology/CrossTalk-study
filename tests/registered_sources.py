"""Explicit software-fixture manifest membership for real local generated PDFs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.models import Issue, load_manifest
from crosstalk.records import write_records

if TYPE_CHECKING:
    from pathlib import Path


def register_source(root: Path, issue_id: str) -> None:
    """Register generated fixture identity without claiming an observed journal publication."""
    manifest = root / "data/manifest/issues.jsonl"
    rows = load_manifest(manifest) if manifest.exists() else ()
    assert issue_id not in {row.issue_id for row in rows}
    issue = Issue(
        issue_id=issue_id,
        title=f"Generated software fixture: {issue_id}",
        landing_url="https://calhoun.nps.edu/handle/10945/1",
        pdf_url="https://calhoun.nps.edu/server/api/core/bitstreams/1/content",
    )
    write_records(manifest, (*rows, issue))
