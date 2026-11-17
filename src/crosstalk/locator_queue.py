"""Current-catalog identity checks and fair deterministic unresolved-item ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.index_identity import valid_manifest_binding
from crosstalk.signposting_store import read_manifest

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.catalog import CatalogIssue
    from crosstalk.locator_records import LocatorEvent
    from crosstalk.signposting_store import CatalogState


def resolved_issue_ids(root: Path, catalog: CatalogState) -> frozenset[str]:
    """Require a current reviewed manifest binding before omitting an archive request."""
    inventory = {issue.issue_id: issue for issue in read_manifest(root).rows}
    return frozenset(
        row.issue_id
        for row in catalog.rows
        if valid_manifest_binding(row, inventory.get(row.issue_id))
    )


def fair_locator_queue(
    catalog: CatalogState, resolved: frozenset[str], events: tuple[LocatorEvent, ...]
) -> tuple[CatalogIssue, ...]:
    """Place never-attempted peers before retries so repeated small batches advance."""
    latest: dict[str, str] = {}
    for event in events:
        if event.catalog_sha256 == catalog.sha256:
            latest[event.issue_id] = max(latest.get(event.issue_id, ""), event.observed_at)
    pending = tuple(row for row in catalog.rows if row.issue_id not in resolved)
    return tuple(sorted(pending, key=lambda row: (latest.get(row.issue_id, ""), row.issue_id)))
