"""Crash-recoverable finite Signposting batches for the current captured catalog."""

from __future__ import annotations

import hashlib
import logging
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never
from uuid import uuid4

import httpx2
from pydantic import ValidationError

from crosstalk.acquisition_http import ArchiveReader
from crosstalk.acquisition_lock import project_lock
from crosstalk.acquisition_policy import USER_AGENT
from crosstalk.locator_http import LocatorBudgetExpiredError, LocatorContext, LocatorReader
from crosstalk.locator_queue import fair_locator_queue, resolved_issue_ids
from crosstalk.locator_records import LocatorBounds, LocatorEvent, LocatorRun
from crosstalk.locator_storage import (
    publish_event,
    publish_metadata,
    read_locator_events,
    read_metadata,
)
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.signposting_import import admit_signposting_snapshot_locked
from crosstalk.signposting_records import LocatorImportResult, SignpostingSnapshot
from crosstalk.signposting_store import CatalogState, read_catalog

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.catalog import CatalogIssue

LOGGER: Final = logging.getLogger(__name__)
SNAPSHOT_PATH: Final = re.compile(r"output/data/locator-snapshots/[0-9a-f]{32}\.json")


@dataclass(frozen=True, slots=True)
class ResolutionSession:
    """Current source bindings and historical attempt snapshot for a finite batch."""

    context: LocatorContext
    catalog: CatalogState
    run_id: str
    events: tuple[LocatorEvent, ...]


def _accepted(result: LocatorImportResult) -> bool:
    """Keep every import refusal state distinct from successful source admission."""
    status = result.observation.status
    match status:
        case "resolved":
            return True
        case (
            "no-pdf"
            | "ambiguous-pdf"
            | "invalid-response"
            | "outside-catalog"
            | "manifest-conflict"
        ):
            return False
        case _:
            assert_never(status)


def _finish(root: Path, event: LocatorEvent, result: tuple[bool, str | None]) -> None:
    """Durably close one attempt without depending on the aggregate run view."""
    accepted, error = result
    _ = publish_event(
        root,
        event.model_copy(
            update={
                "stage": "finished",
                "observed_at": datetime.now(UTC).isoformat(),
                "outcome": "resolved" if accepted else "failed",
                "error": error,
            }
        ),
    )


def _recovery_candidates(session: ResolutionSession) -> tuple[LocatorEvent, ...]:
    """Select current-catalog response evidence without reviving explicit failed attempts."""
    latest: dict[str, LocatorEvent] = {}
    failed = {event.attempt_id for event in session.events if event.outcome == "failed"}
    catalog_ids = {row.issue_id: row.item_id for row in session.catalog.rows}
    for event in session.events:
        if (
            event.catalog_sha256 == session.catalog.sha256
            and catalog_ids.get(event.issue_id) == event.item_id
            and event.snapshot_sha256 is not None
            and event.attempt_id not in failed
        ):
            latest[event.issue_id] = event
    return tuple(latest.values())


def _replay_event(session: ResolutionSession, event: LocatorEvent) -> None:
    """Admit only live body and envelope bytes matching the independent response seal."""
    path = event.snapshot_path
    if path is None or not SNAPSHOT_PATH.fullmatch(path):
        return
    raw = read_metadata(session.context.root / path)
    if hashlib.sha256(raw).hexdigest() != event.snapshot_sha256:
        return
    snapshot = SignpostingSnapshot.model_validate_json(raw)
    expected_url = f"https://calhoun.nps.edu/server/signposting/linksets/{event.item_id}/json"
    if snapshot.catalog_sha256 != session.catalog.sha256 or snapshot.request_url != expected_url:
        return
    result = admit_signposting_snapshot_locked(session.context.root, snapshot)
    if not any(
        prior.attempt_id == event.attempt_id and prior.stage == "finished"
        for prior in session.events
    ):
        _finish(session.context.root, event, (_accepted(result), result.observation.reason))


def _recover(session: ResolutionSession, resolved: frozenset[str]) -> None:
    """Replay independently sealed response evidence after a lost manifest publication."""
    for event in _recovery_candidates(session):
        if event.issue_id in resolved:
            continue
        try:
            _replay_event(session, event)
        except (AcquisitionError, OSError, UnicodeError, ValidationError) as error:
            LOGGER.warning("locator_recovery_refused issue_id=%s error=%s", event.issue_id, error)


def _attempt(
    row: CatalogIssue, session: ResolutionSession, reader: LocatorReader
) -> tuple[bool, bool]:
    """Persist admission, complete response evidence and outcome as independent stages."""
    root = session.context.root
    event = LocatorEvent(
        attempt_id=uuid4().hex,
        run_id=session.run_id,
        issue_id=row.issue_id,
        item_id=row.item_id,
        catalog_sha256=session.catalog.sha256,
        observed_at=datetime.now(UTC).isoformat(),
        stage="started",
    )
    _ = publish_event(root, event)
    try:
        snapshot = reader.fetch(row)
        encoded = snapshot.model_dump_json().encode() + b"\n"
        directory = safe_directory(root, "output/data/locator-snapshots")
        path = publish_metadata(directory, f"{event.attempt_id}.json", encoded)
        event = event.model_copy(
            update={
                "stage": "response",
                "observed_at": datetime.now(UTC).isoformat(),
                "snapshot_path": str(path.relative_to(root)),
                "snapshot_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
        _ = publish_event(root, event)
        result = admit_signposting_snapshot_locked(root, snapshot)
        accepted = _accepted(result)
        _finish(root, event, (accepted, result.observation.reason))
    except LocatorBudgetExpiredError as error:
        _finish(root, event, (False, str(error)))
        return False, True
    except (httpx2.HTTPError, AcquisitionError, OSError, UnicodeError, ValidationError) as error:
        _finish(root, event, (False, str(error)))
        LOGGER.warning("locator_attempt_failed issue_id=%s error=%s", row.issue_id, error)
        return False, False
    else:
        return accepted, False


def resolve_with_reader(network: LocatorReader) -> LocatorRun:
    """Internal orchestration seam; caller holds the actual project lock throughout."""
    context = network.context
    root, bounds = context.root, context.bounds
    catalog = read_catalog(root)
    if catalog.sha256 != context.catalog_sha256:
        raise AcquisitionError("locator HTTP context does not match the current catalog")
    session = ResolutionSession(context, catalog, uuid4().hex, read_locator_events(root))
    existing = resolved_issue_ids(root, catalog)
    _recover(session, existing)
    recovered = resolved_issue_ids(root, catalog) - existing
    queue = fair_locator_queue(catalog, existing | recovered, session.events)
    attempted, failures, exhausted = 0, 0, False
    for row in queue[: bounds.limit]:
        if not network.available():
            exhausted = True
            break
        accepted, exhausted = _attempt(row, session, network)
        attempted += 1
        failures += int(not accepted)
        if exhausted or network.robots_sha256 is None:
            break
    if read_catalog(root).sha256 != catalog.sha256:
        raise AcquisitionError("catalog changed during resolution; immutable evidence retained")
    resolved = resolved_issue_ids(root, catalog)
    summary = LocatorRun(
        run_id=session.run_id,
        observed_at=datetime.now(UTC).isoformat(),
        catalog_sha256=catalog.sha256,
        catalog_count=len(catalog.rows),
        verified_existing=len(existing),
        recovered=len(recovered),
        attempted=attempted,
        resolved=len(resolved),
        failed=failures,
        deferred=len(queue) - attempted,
        time_budget_exhausted=exhausted,
    )
    directory = safe_directory(root, "output/data/locator-runs")
    _ = publish_metadata(
        directory, f"{session.run_id}.json", summary.model_dump_json().encode() + b"\n"
    )
    return summary


def _log_response(response: httpx2.Response) -> None:
    """Log bounded host/status facts without query strings or credentials."""
    LOGGER.info(
        "locator_response host=%s status=%s", response.request.url.host, response.status_code
    )


def resolve_catalog_locators(root: Path, bounds: LocatorBounds | None = None) -> LocatorRun:
    """Resolve a finite fair batch automatically; never traverse unrelated holdings."""
    selected = bounds or LocatorBounds()
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=httpx2.Limits(
            max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0
        ),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    with (
        project_lock(root),
        httpx2.Client(
            transport=transport,
            timeout=httpx2.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            event_hooks={"response": [_log_response]},
        ) as client,
    ):
        context = LocatorContext(root, read_catalog(root).sha256, selected)
        return resolve_with_reader(LocatorReader(context, ArchiveReader(client, selected.delay)))
