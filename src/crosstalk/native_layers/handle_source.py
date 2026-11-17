"""Reuse independently sealed exact-publication Signposting evidence without network access."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from crosstalk.locator_storage import read_locator_events
from crosstalk.models import AcquisitionError
from crosstalk.native_layers.records import HandleEvidence
from crosstalk.signposting_custody import read_bound_metadata, require_retained_policy
from crosstalk.signposting_parse import requested_item
from crosstalk.signposting_records import LinksetDocument, SignpostingSnapshot

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.catalog import CatalogIssue


def retained_handle(root: Path, row: CatalogIssue, catalog_sha256: str) -> HandleEvidence | None:
    """Require event-sealed envelope, body, robots, UUID, exact anchor and current catalog."""
    candidates = tuple(
        event
        for event in read_locator_events(root)
        if event.issue_id == row.issue_id
        and event.item_id == row.item_id
        and event.catalog_sha256 == catalog_sha256
        and event.stage == "finished"
        and event.outcome == "resolved"
    )
    if not candidates:
        return None
    event = candidates[-1]
    path, seal = event.snapshot_path, event.snapshot_sha256
    if (
        path is None
        or seal is None
        or not re.fullmatch(r"output/data/locator-snapshots/[0-9a-f]{32}\.json", path)
    ):
        raise AcquisitionError("retained handle lacks an independently sealed response envelope")
    snapshot = SignpostingSnapshot.model_validate_json(read_bound_metadata(root, path, seal))
    if requested_item(snapshot) != row.item_id or snapshot.catalog_sha256 != catalog_sha256:
        raise AcquisitionError("retained handle response disagrees with current catalog identity")
    if snapshot.status_code != 200 or snapshot.content_type.split(";", 1)[
        0
    ].strip().casefold() not in {"application/linkset+json", "application/json"}:
        raise AcquisitionError("retained handle response is not an admitted JSON linkset")
    require_retained_policy(root, snapshot)
    raw = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
    document = LinksetDocument.model_validate_json(raw)
    contexts = tuple(context for context in document.linkset if context.anchor == row.landing_url)
    if len(contexts) != 1:
        return None
    handles = {
        target.href
        for target in contexts[0].cite_as
        if re.fullmatch(r"https://hdl\.handle\.net/10945/[0-9]+", target.href)
    }
    if len(handles) != 1:
        return None
    # Recheck the independently bound raw inputs immediately before using their observations.
    _ = read_bound_metadata(root, path, seal)
    _ = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
    require_retained_policy(root, snapshot)
    return HandleEvidence(
        handle_url=next(iter(handles)),
        publication_url=row.landing_url,
        request_url=snapshot.request_url,
        snapshot_path=path,
        snapshot_sha256=seal,
        body_sha256=snapshot.body_sha256,
        catalog_sha256=catalog_sha256,
        robots_sha256=snapshot.robots_sha256,
        provenance="retained-exact-publication-signposting",
    )
