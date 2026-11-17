"""Finite publisher acquisition preserves source family, policy evidence and local originals."""

from __future__ import annotations

import socket
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, assert_never
from uuid import uuid4

import httpx2

from crosstalk.acquire import PendingIssue, observe_source, process_work
from crosstalk.acquisition_ledger import AcquisitionLedger
from crosstalk.acquisition_lock import project_lock
from crosstalk.acquisition_policy import USER_AGENT
from crosstalk.models import (
    AcquisitionError,
    DownloadReceipt,
    safe_directory,
    write_summary,
)
from crosstalk.publisher_acquisition_records import PublisherDownloadRun, PublisherEnvironment
from crosstalk.publisher_history import failed_attempts, publisher_events
from crosstalk.publisher_http import PublisherArchiveReader
from crosstalk.publisher_implementation import publisher_implementation_sha256
from crosstalk.publisher_inventory import prepare_publisher_inventory, read_publisher_inventory
from crosstalk.publisher_limits import validate_publisher_bounds
from crosstalk.publisher_policy import storage_unavailable

if TYPE_CHECKING:
    from crosstalk.publisher_inventory import PublisherInventory
    from crosstalk.source_inventory import PublisherDownloadSource


def _independent_or_prepared(
    target: Path, source: PublisherDownloadSource, ledger: AcquisitionLedger
) -> None:
    """Only a known prepared/final hardlink pair is allowed after publication interruption."""
    if not target.exists() or target.is_symlink():
        return
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise AcquisitionError("publisher existing payload is not a regular file")
    if info.st_nlink == 1:
        return
    for event in ledger.matching(source):
        name = event.partial_name
        if name is None or Path(name).name != name:
            continue
        partial = target.parent / name
        if partial.is_symlink() or not partial.is_file():
            continue
        other = partial.stat()
        if info.st_nlink == 2 and (info.st_dev, info.st_ino) == (other.st_dev, other.st_ino):
            return
    raise AcquisitionError("publisher payload has an unbound hardlink alias; preserved")


def _observations(
    inventory: PublisherInventory,
    ledger: AcquisitionLedger,
    maximum_failures: int,
) -> tuple[tuple[DownloadReceipt, ...], tuple[PendingIssue, ...], tuple[DownloadReceipt, ...]]:
    """Verified local bytes consume no new-work slot and need no policy or PDF request."""
    directory = safe_directory(inventory.root, "data/raw/pdf")
    observed: list[DownloadReceipt] = []
    pending: list[PendingIssue] = []
    for source in inventory.sources:
        prior = ledger.prior(source)
        target = directory / f"{source.issue_id}.pdf"
        try:
            _independent_or_prepared(target, source, ledger)
            receipt = observe_source(source, target, prior)
            for event in ledger.matching(source):
                name = event.partial_name
                if name is not None and Path(name).name == name and not target.exists():
                    partial = directory / name
                    if partial.exists() and (partial.is_symlink() or partial.stat().st_nlink != 1):
                        raise AcquisitionError("publisher prepared payload has an unsafe alias")
        except OSError as error:
            if storage_unavailable(error):
                raise
            pending.append(PendingIssue(source, prior, str(error)))
            continue
        except ValueError as error:
            pending.append(PendingIssue(source, prior, str(error)))
            continue
        if receipt is None:
            pending.append(PendingIssue(source, prior))
        else:
            observed.append(receipt)
            ledger.record_verification(source, receipt)
    pending.sort(key=lambda row: (ledger.last_attempt(row.issue), row.issue.issue_id))
    selected, capped = _bounded_pending(tuple(pending), ledger, directory, maximum_failures)
    return tuple(observed), selected, capped


def _bounded_pending(
    pending: tuple[PendingIssue, ...],
    ledger: AcquisitionLedger,
    directory: Path,
    maximum_failures: int,
) -> tuple[tuple[PendingIssue, ...], tuple[DownloadReceipt, ...]]:
    """Preserve the per-locator retry cap while always admitting verified local reuse first."""
    selected: list[PendingIssue] = []
    capped: list[DownloadReceipt] = []
    for candidate in pending:
        source = candidate.issue
        if failed_attempts(ledger.matching(source)) >= maximum_failures:
            capped.append(
                DownloadReceipt(
                    issue_id=source.issue_id,
                    pdf_url=source.pdf_url,
                    status="failed",
                    path=str(directory / f"{source.issue_id}.pdf"),
                    error="publisher source retry cap reached; prior evidence retained",
                )
            )
        else:
            selected.append(candidate)
    return tuple(selected), tuple(capped)


def _selected_work(
    selected: tuple[PendingIssue, ...],
    reader: PublisherArchiveReader,
    ledger: AcquisitionLedger,
    failure_limit: int,
) -> tuple[tuple[DownloadReceipt, ...], PublisherEnvironment]:
    """Stop explicit environment failures or a bounded consecutive source-failure streak."""
    results: list[DownloadReceipt] = []
    failures = 0
    state: PublisherEnvironment = "batch-finished"
    for candidate in selected:
        if not reader.new_work_available():
            state = "budget-exhausted"
            break
        receipts = process_work((candidate,), reader, ledger)
        if not receipts:
            state = "budget-exhausted"
            break
        receipt = receipts[0]
        results.append(receipt)
        match receipt.status:
            case "downloaded" | "verified":
                failures = 0
            case "failed":
                failures += 1
                match reader.last_failure:
                    case (
                        "network-unavailable"
                        | "policy-unavailable"
                        | "budget-exhausted"
                        | "storage-unavailable"
                    ):
                        state = reader.last_failure
                    case "none" | "source-failed" | "local-refusal":
                        pass
                    case _:
                        assert_never(reader.last_failure)
                if state != "batch-finished":
                    break
                if failures >= failure_limit:
                    state = "failure-cap"
                    break
            case _:
                assert_never(receipt.status)
    return tuple(results), state


def acquire_publisher_with_client(
    inventory: PublisherInventory,
    client: httpx2.Client,
    bounds: tuple[int | None, float, float, int],
    *,
    maximum_source_failures: int = 3,
) -> PublisherDownloadRun:
    """Use a configured real transport; public entry constructs the production client."""
    limit, delay, seconds, failure_limit = bounds
    validate_publisher_bounds(limit, delay, seconds, failure_limit, maximum_source_failures)
    if client.follow_redirects:
        raise AcquisitionError("publisher client must refuse redirects before any work")
    root = inventory.root
    with project_lock(root):
        current = read_publisher_inventory(root)
        if current != inventory:
            raise AcquisitionError("publisher inventory changed before acquisition admission")
        events = publisher_events(root)
        ledger = AcquisitionLedger(root, inventory.proof.sources_sha256, uuid4().hex, events)
        observed, pending, capped = _observations(inventory, ledger, maximum_source_failures)
        selected = pending if limit is None else pending[:limit]
        reader = PublisherArchiveReader(
            client, delay, time.monotonic() + seconds, inventory, ledger.run_id
        )
        attempted, state = _selected_work(selected, reader, ledger, failure_limit)
        if not pending and capped:
            state = "retry-cap"
        if read_publisher_inventory(root) != inventory:
            raise AcquisitionError("publisher inventory changed; per-attempt evidence retained")
        if publisher_implementation_sha256() != inventory.proof.implementation_sha256:
            raise AcquisitionError("publisher implementation changed during acquisition")
        receipts = {row.issue_id: row for row in (*observed, *attempted, *capped)}
        summary = PublisherDownloadRun(
            manifest_sha256=inventory.proof.sources_sha256,
            observed_at=datetime.now(UTC).isoformat(),
            selected=len(selected),
            inventory_count=len(inventory.sources),
            receipts=tuple(
                receipts[row.issue_id] for row in inventory.sources if row.issue_id in receipts
            ),
            run_id=ledger.run_id,
            verified_existing=len(observed),
            attempted=len(attempted),
            deferred=len(pending) - len(attempted) + len(capped),
            time_budget_exhausted=state == "budget-exhausted",
            source_snapshot_sha256=inventory.proof.source_snapshot_sha256,
            captured_cards=inventory.proof.cards,
            public_pdf_candidates=len(inventory.sources),
            contact_only=inventory.proof.contact_only,
            environment_state=state,
            implementation_sha256=inventory.proof.implementation_sha256,
            consecutive_failure_limit=failure_limit,
            maximum_source_failures=maximum_source_failures,
            retry_capped_sources=len(capped),
            requested_new_work_limit=limit,
            minimum_delay_seconds=delay,
            network_budget_seconds=seconds,
            observed_failures=sum(row.status == "failed" for row in attempted),
            policy_observations=tuple(value[1] for value in reader.observations.values()),
        )
        path = safe_directory(root, "output/data") / "publisher-downloads.json"
        write_summary(path, summary)
        return summary


def download_publisher(
    project: Path,
    limit: int | None = 4,
    delay: float = 10.0,
    *,
    max_seconds: float = 240.0,
    consecutive_failure_limit: int = 3,
) -> PublisherDownloadRun:
    """Snapshot only observed public candidates and acquire in their isolated dataset."""
    validate_publisher_bounds(limit, delay, max_seconds, consecutive_failure_limit)
    inventory = prepare_publisher_inventory(project)
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    with httpx2.Client(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        return acquire_publisher_with_client(
            inventory, client, (limit, delay, max_seconds, consecutive_failure_limit)
        )
