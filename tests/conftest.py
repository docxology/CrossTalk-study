"""Real generated software-source fixtures shared across native custody regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from crosstalk.catalog import CatalogIssue
from crosstalk.models import SERIES_ID, Issue
from crosstalk.records import write_records

from .test_layers import TITLE, source_at, wrapper

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def native_source(tmp_path: Path) -> Path:
    identity, _ = source_at(tmp_path, (wrapper(), "Native software text may remain valid.", ""))
    item_id = "00000000-0000-4000-8000-000000000002"
    landing = f"https://calhoun.nps.edu/entities/publication/{item_id}"
    catalog = CatalogIssue(
        issue_id="fixture",
        item_id=item_id,
        title=TITLE,
        issued_metadata="1996-05",
        landing_url=landing,
        series_id=SERIES_ID,
        raw_context="Explicit software fixture, not historical evidence",
        source_snapshot_sha256="a" * 64,
        flags=(),
        acquisition_status="pdf-unresolved",
    )
    issue = Issue(
        issue_id="fixture",
        item_id=item_id,
        title=TITLE,
        issued="1996-05",
        landing_url=landing,
        pdf_url=f"https://calhoun.nps.edu/server/api/core/bitstreams/{item_id}/content",
        sha256=identity.pdf_sha256,
    )
    write_records(tmp_path / "data/manifest/catalog.jsonl", (catalog,))
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    return tmp_path
