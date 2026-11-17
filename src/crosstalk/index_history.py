"""Read historical acquisition observations without substituting them for live integrity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from crosstalk.acquisition_ledger import issue_fingerprint, read_events
from crosstalk.acquisition_records import read_download_summary
from crosstalk.index_records import IndexedAcquisition

if TYPE_CHECKING:
    from crosstalk.acquisition_records import AttemptEvent
    from crosstalk.index_observe import IndexReader
    from crosstalk.models import DownloadSummary, Issue


@dataclass(frozen=True, slots=True)
class AcquisitionHistory:
    """One explicitly available historical source set and any reader failures."""

    events: tuple[AttemptEvent, ...]
    legacy: DownloadSummary | None
    failures: tuple[str, ...]
    ledger_available: bool


@dataclass(frozen=True, slots=True)
class IssueHistory:
    """Source-matched history and an expected digest to recheck against actual bytes."""

    last: IndexedAcquisition | None
    expected_sha256: str | None


def read_history(reader: IndexReader) -> AcquisitionHistory:
    """Bind immutable event inputs; a failed ledger reader cannot revive older success."""
    failures: list[str] = []
    available = True
    try:
        events = read_events(reader.root)
        for event in events:
            _ = reader.read(f"output/data/acquisition-ledger/{event.attempt_id}-{event.stage}.json")
    except (OSError, ValueError) as error:
        failures.append(f"acquisition ledger unavailable: {error}")
        events = ()
        available = False
    legacy = None
    relative = "output/data/downloads.json"
    try:
        _ = reader.read(relative)
        legacy = read_download_summary(reader.path(relative))
    except FileNotFoundError:
        legacy = None
    except (OSError, ValueError) as error:
        failures.append(f"download summary unavailable: {error}")
    return AcquisitionHistory(events, legacy, tuple(failures), available)


def issue_history(history: AcquisitionHistory, issue: Issue | None) -> IssueHistory:
    """Use the newest matching attempt and preserve an unfinished attempt explicitly."""
    if issue is None:
        return IssueHistory(None, None)
    expected = issue.sha256
    if not history.ledger_available:
        return IssueHistory(None, expected)
    fingerprint = issue_fingerprint(issue)
    matching = tuple(
        event
        for event in history.events
        if event.issue_id == issue.issue_id
        and event.issue_sha256 == fingerprint
        and event.pdf_url == issue.pdf_url
    )
    if matching:
        return _event_history(matching, issue, expected)
    if history.legacy is not None:
        receipts = (*history.legacy.retained_receipts, *history.legacy.receipts)
        for receipt in reversed(receipts):
            if receipt.issue_id == issue.issue_id and receipt.pdf_url == issue.pdf_url:
                return IssueHistory(
                    IndexedAcquisition(status=receipt.status, error=receipt.error),
                    expected or receipt.sha256 or receipt.expected_sha256,
                )
    return IssueHistory(None, expected)


def _event_history(
    events: tuple[AttemptEvent, ...], issue: Issue, expected: str | None
) -> IssueHistory:
    """Keep newest attempt status distinct from the newest preserved digest evidence."""
    for event in reversed(events):
        receipt = event.receipt
        if (
            receipt is not None
            and receipt.pdf_url == issue.pdf_url
            and receipt.issue_id == issue.issue_id
        ):
            expected = expected or receipt.sha256 or receipt.expected_sha256
            if expected is not None:
                break
    latest = events[-1]
    match latest.stage:
        case "started" | "prepared":
            observation = IndexedAcquisition(
                status="interrupted",
                attempt_id=latest.attempt_id,
                stage=latest.stage,
                error="latest source-matched attempt has no finished event",
            )
        case "finished":
            receipt = latest.receipt
            if (
                receipt is not None
                and receipt.issue_id == issue.issue_id
                and receipt.pdf_url == issue.pdf_url
            ):
                observation = IndexedAcquisition(
                    status=receipt.status,
                    error=receipt.error,
                    attempt_id=latest.attempt_id,
                    stage=latest.stage,
                )
            else:
                observation = IndexedAcquisition(
                    status="failed",
                    attempt_id=latest.attempt_id,
                    stage=latest.stage,
                    error="finished event has no matching issue receipt",
                )
        case _:
            assert_never(latest.stage)
    return IssueHistory(observation, expected)
