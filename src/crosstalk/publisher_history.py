"""Revalidate historical publisher membership without coupling byte identity to frame growth."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, assert_never

from crosstalk.acquisition_ledger import issue_fingerprint, read_events
from crosstalk.models import AcquisitionError
from crosstalk.publisher_dataset import read_publisher_bytes
from crosstalk.publisher_records import ContactPublisherCard, PublicPublisherCard, PublisherSnapshot
from crosstalk.source_inventory import PublisherDownloadSource

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.acquisition_records import AttemptEvent


def _public_card(
    frame: PublisherSnapshot,
    event: AttemptEvent,
) -> PublicPublisherCard:
    """Only a captured public card with the same local ID and exact locator admits a prior event."""
    candidates: list[PublicPublisherCard] = []
    for card in frame.records:
        match card:
            case PublicPublisherCard():
                if f"ct-afsc-{card.card_key}" == event.issue_id and card.pdf_url == event.pdf_url:
                    candidates.append(card)
            case ContactPublisherCard():
                pass
            case _:
                assert_never(card)
    if len(candidates) != 1:
        raise AcquisitionError("publisher historical attempt lacks captured public membership")
    return candidates[0]


def publisher_events(root: Path) -> tuple[AttemptEvent, ...]:
    """An older attempt remains admissible only with its exact retained public-card capture."""
    events = read_events(root)
    frames: dict[str, PublisherSnapshot] = {}
    for event in events:
        digest = event.source_snapshot_sha256
        if event.source_family != "afsc-publisher" or digest is None:
            raise AcquisitionError("publisher dataset contains another source family's ledger")
        if (
            event.stage == "finished"
            and event.receipt is not None
            and event.receipt.status == "failed"
            and event.publisher_failure_kind is None
        ):
            raise AcquisitionError(
                "publisher failed attempt lacks its source/environment classification"
            )
        if digest not in frames:
            raw = read_publisher_bytes(root, f"data/raw/metadata/publisher/{digest}.json")
            if hashlib.sha256(raw).hexdigest() != digest:
                raise AcquisitionError("publisher historical capture digest changed")
            frames[digest] = PublisherSnapshot.model_validate_json(raw)
        card = _public_card(frames[digest], event)
        source = PublisherDownloadSource(
            issue_id=event.issue_id,
            card_key=card.card_key,
            title=card.title,
            pdf_url=card.pdf_url,
            source_snapshot_sha256=digest,
            sha256=event.source_pinned_sha256,
        )
        if issue_fingerprint(source) != event.issue_sha256:
            raise AcquisitionError("publisher historical acquisition identity disagrees")
    return events


def failed_attempts(events: tuple[AttemptEvent, ...]) -> int:
    """A failed attempt counts once, independently of catalog capture changes."""
    return len(
        {
            event.attempt_id
            for event in events
            if event.stage == "finished"
            and event.publisher_failure_kind == "source"
            and event.receipt is not None
            and event.receipt.status == "failed"
        }
    )
