"""Idempotent bounded acquisition with live verification and immutable attempt history."""

from __future__ import annotations

import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import httpx2

from crosstalk.acquisition_http import MAX_PDF_BYTES, ArchiveReader
from crosstalk.acquisition_ledger import AcquisitionLedger, read_events
from crosstalk.acquisition_lock import project_lock
from crosstalk.acquisition_policy import USER_AGENT, RobotsPolicy, parse_robots
from crosstalk.acquisition_records import DownloadRun, read_download_summary
from crosstalk.models import (
    AcquisitionError,
    DownloadReceipt,
    file_digest,
    load_manifest,
    safe_directory,
    write_summary,
)

__all__ = ["MAX_PDF_BYTES", "ArchiveReader", "RobotsPolicy", "download_manifest", "parse_robots"]
LOGGER: Final = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.source_inventory import DownloadSource


@dataclass(frozen=True, slots=True)
class PendingIssue:
    """One source needing work, including a preservation refusal observed locally."""

    issue: DownloadSource
    prior: DownloadReceipt | None
    refusal: str | None = None


def _observe(
    issue: DownloadSource, target: Path, prior: DownloadReceipt | None
) -> DownloadReceipt | None:
    """Resume only when live regular-file bytes match independently recorded evidence."""
    if target.is_symlink():
        raise AcquisitionError("existing PDF is a symlink; preserved")
    if not target.exists():
        return None
    if target.stat().st_size > MAX_PDF_BYTES:
        raise AcquisitionError("existing PDF exceeds the size bound; preserved")
    expected = issue.sha256
    if expected is None and prior is not None and prior.pdf_url == issue.pdf_url:
        expected = prior.sha256 or prior.expected_sha256
    if expected is None or file_digest(target) != expected:
        raise AcquisitionError("existing PDF lacks matching digest evidence; preserved")
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise AcquisitionError("existing payload is not a PDF; preserved")
    return DownloadReceipt(
        issue_id=issue.issue_id,
        pdf_url=issue.pdf_url,
        status="verified",
        path=str(target),
        sha256=expected,
        byte_count=target.stat().st_size,
    )


# Public shared observation seam; the original NPS implementation is unchanged.
observe_source = _observe


def _failure(work: PendingIssue, target: Path, reason: str) -> DownloadReceipt:
    expected = work.issue.sha256 or (
        work.prior.sha256 or work.prior.expected_sha256 if work.prior is not None else None
    )
    return DownloadReceipt(
        issue_id=work.issue.issue_id,
        pdf_url=work.issue.pdf_url,
        status="failed",
        path=str(target),
        expected_sha256=expected,
        error=reason,
    )


def _log_response(response: httpx2.Response) -> None:
    """Avoid query strings and raw request arguments in diagnostics."""
    LOGGER.info(
        "archive_response host=%s status=%s", response.request.url.host, response.status_code
    )


def process_work(
    work: tuple[PendingIssue, ...], reader: ArchiveReader, ledger: AcquisitionLedger
) -> tuple[DownloadReceipt, ...]:
    """Complete and persist each attempt independently of the replaceable batch view."""
    receipts: list[DownloadReceipt] = []
    directory = safe_directory(ledger.root, "data/raw/pdf")
    for candidate in work:
        if not reader.new_work_available():
            break
        issue = candidate.issue
        target = directory / f"{issue.issue_id}.pdf"
        attempt = ledger.begin(issue)
        reader.attempt = attempt
        try:
            if candidate.refusal is not None:
                receipt = _failure(candidate, target, candidate.refusal)
            else:
                receipt = ledger.recover(issue, target) or reader.download(issue, target)
        except httpx2.HTTPStatusError as error:
            receipt = _failure(candidate, target, f"HTTP response {error.response.status_code}")
        except httpx2.HTTPError as error:
            receipt = _failure(candidate, target, type(error).__name__)
        except (AcquisitionError, OSError, UnicodeError) as error:
            reader.record_failure(error)
            receipt = _failure(candidate, target, str(error))
        finally:
            reader.attempt = None
        attempt.finish(receipt, failure_kind=reader.failure_kind(receipt))
        receipts.append(receipt)
    return tuple(receipts)


def _download_locked(
    manifest_path: Path, root: Path, bounds: tuple[int | None, float, float]
) -> DownloadRun:
    limit, delay, max_seconds = bounds
    manifest_sha256 = file_digest(manifest_path)
    issues = load_manifest(manifest_path)
    if file_digest(manifest_path) != manifest_sha256:
        raise AcquisitionError("inventory changed while being parsed")
    directory = safe_directory(root, "data/raw/pdf")
    receipt_path = safe_directory(root, "output/data") / "downloads.json"
    if receipt_path.is_symlink():
        raise AcquisitionError("receipt path is a symlink")
    previous = read_download_summary(receipt_path) if receipt_path.exists() else None
    history = (*previous.retained_receipts, *previous.receipts) if previous is not None else ()
    sources = {issue.issue_id: issue.pdf_url for issue in issues}
    legacy = {
        receipt.issue_id: receipt
        for receipt in history
        if sources.get(receipt.issue_id) == receipt.pdf_url
    }
    ledger = AcquisitionLedger(root, manifest_sha256, uuid4().hex, read_events(root))
    observed: list[DownloadReceipt] = []
    pending: list[PendingIssue] = []
    for issue in issues:
        prior = ledger.prior(issue) or legacy.get(issue.issue_id)
        try:
            receipt = _observe(issue, directory / f"{issue.issue_id}.pdf", prior)
        except (AcquisitionError, OSError) as error:
            pending.append(PendingIssue(issue, prior, str(error)))
            continue
        if receipt is None:
            pending.append(PendingIssue(issue, prior))
        else:
            observed.append(receipt)
            ledger.record_verification(issue, receipt)
    pending.sort(
        key=lambda candidate: (ledger.last_attempt(candidate.issue), candidate.issue.issue_id)
    )
    selected = tuple(pending if limit is None else pending[:limit])
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=httpx2.Limits(
            max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0
        ),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    deadline = time.monotonic() + max_seconds
    with httpx2.Client(
        transport=transport,
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        event_hooks={"response": [_log_response]},
    ) as client:
        attempted = process_work(selected, ArchiveReader(client, delay, deadline), ledger)
    if file_digest(manifest_path) != manifest_sha256:
        raise AcquisitionError(
            "inventory changed during acquisition; per-attempt evidence retained"
        )
    receipts = {receipt.issue_id: receipt for receipt in (*observed, *attempted)}
    retained = tuple(
        legacy[issue.issue_id]
        for issue in issues
        if issue.issue_id not in receipts and issue.issue_id in legacy
    )
    summary = DownloadRun(
        manifest_sha256=manifest_sha256,
        observed_at=datetime.now(UTC).isoformat(),
        selected=len(selected),
        inventory_count=len(issues),
        receipts=tuple(receipts[issue.issue_id] for issue in issues if issue.issue_id in receipts),
        retained_receipts=retained,
        run_id=ledger.run_id,
        verified_existing=len(observed),
        attempted=len(attempted),
        deferred=len(pending) - len(attempted),
        time_budget_exhausted=(len(attempted) < len(selected) or time.monotonic() >= deadline),
    )
    write_summary(receipt_path, summary)
    return summary


def download_manifest(
    manifest_path: Path,
    root: Path,
    limit: int | None = None,
    delay: float = 10.0,
    *,
    max_seconds: float = 240.0,
) -> DownloadRun:
    """Verify all local sources; apply the limit only to fair queued acquisition work."""
    if delay < 10.0 or not float("-inf") < delay < float("inf"):
        raise AcquisitionError("delay must be finite and at least ten seconds")
    if limit is not None and not 1 <= limit <= 10_000:
        raise AcquisitionError("limit must be between 1 and 10,000")
    if not 0 < max_seconds <= 240.0:
        raise AcquisitionError("acquisition network budget must be finite and at most 240 seconds")
    publisher_marker = root / "publisher-dataset.json"
    if publisher_marker.exists() or publisher_marker.is_symlink():
        raise AcquisitionError("NPS download_manifest cannot write a publisher dataset")
    with project_lock(root):
        return _download_locked(manifest_path, root, (limit, delay, max_seconds))
