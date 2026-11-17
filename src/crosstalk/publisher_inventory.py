"""Snapshot-bound public download candidates without synthesizing an NPS inventory."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from crosstalk.acquisition_lock import project_lock
from crosstalk.locator_storage import publish_metadata, read_metadata
from crosstalk.models import AcquisitionError, Digest, safe_directory
from crosstalk.publisher_catalog import read_publisher_catalog
from crosstalk.publisher_dataset import (
    PublisherDatasetMarker,
    publish_publisher_records,
    publisher_dataset,
    read_publisher_bytes,
)
from crosstalk.publisher_implementation import publisher_implementation_sha256
from crosstalk.publisher_records import (
    ContactPublisherCard,
    PublicPublisherCard,
    PublisherCatalogRow,
    PublisherSnapshot,
)
from crosstalk.records import Record
from crosstalk.source_inventory import PublisherDownloadSource

if TYPE_CHECKING:
    from pathlib import Path


class PublisherInventoryProof(Record):
    """One copied discovery frame; printed dates and historical totals remain unresolved."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    source_snapshot_sha256: Digest
    catalog_sha256: Digest
    sources_sha256: Digest
    implementation_sha256: Digest
    cards: int
    public_pdf_candidates: int
    contact_only: int
    archive_complete: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PublisherInventory:
    """Only public sources enter acquisition; all captured cards remain available to accounting."""

    root: Path
    proof: PublisherInventoryProof
    sources: tuple[PublisherDownloadSource, ...]
    cards: tuple[PublisherCatalogRow, ...]


def _sources(cards: tuple[PublisherCatalogRow, ...]) -> tuple[PublisherDownloadSource, ...]:
    """Only explicit public cards project into downloadable source models."""
    rows: list[PublisherDownloadSource] = []
    for row in cards:
        match row.candidate:
            case PublicPublisherCard() as card:
                rows.append(
                    PublisherDownloadSource(
                        issue_id=row.record_id,
                        card_key=card.card_key,
                        title=card.title,
                        pdf_url=card.pdf_url,
                        date_claims=card.date_claims,
                        source_snapshot_sha256=row.source_snapshot_sha256,
                    )
                )
            case ContactPublisherCard():
                pass
            case _:
                assert_never(row.candidate)
    return tuple(rows)


def prepare_publisher_inventory(project: Path) -> PublisherInventory:
    """Capture the guarded frame briefly, then release NPS admission before publisher work."""
    frame = read_publisher_catalog(project)
    raw = read_metadata(
        project / "data/raw/metadata/publisher" / f"{frame.summary.snapshot_sha256}.json"
    )
    if hashlib.sha256(raw).hexdigest() != frame.summary.snapshot_sha256:
        raise AcquisitionError("publisher source capture changed before dataset snapshot")
    root = publisher_dataset(project)
    sources = _sources(frame.rows)
    encoded = b"".join(row.model_dump_json().encode() + b"\n" for row in sources)
    proof = PublisherInventoryProof(
        source_snapshot_sha256=frame.summary.snapshot_sha256,
        catalog_sha256=frame.summary.catalog_sha256,
        sources_sha256=hashlib.sha256(encoded).hexdigest(),
        implementation_sha256=publisher_implementation_sha256(),
        cards=len(frame.rows),
        public_pdf_candidates=len(sources),
        contact_only=frame.summary.contact_only,
    )
    with project_lock(root):
        _ = safe_directory(root, "data/manifest")
        for relative in (
            "data/manifest/publisher-sources.jsonl",
            "data/manifest/publisher-inventory.jsonl",
        ):
            with suppress(FileNotFoundError):
                _ = read_publisher_bytes(root, relative)
        retained = safe_directory(root, "data/raw/metadata/publisher")
        _ = publish_metadata(retained, f"{proof.source_snapshot_sha256}.json", raw)
        publish_publisher_records(root, "data/manifest/publisher-sources.jsonl", sources)
        publish_publisher_records(root, "data/manifest/publisher-inventory.jsonl", (proof,))
    return read_publisher_inventory(root)


def read_publisher_inventory(root: Path) -> PublisherInventory:
    """Reconstruct candidate membership from the immutable capture instead of trusting flags."""
    _ = PublisherDatasetMarker.model_validate_json(
        read_publisher_bytes(root, "publisher-dataset.json")
    )
    proof = PublisherInventoryProof.model_validate_json(
        read_publisher_bytes(root, "data/manifest/publisher-inventory.jsonl")
    )
    if proof.implementation_sha256 != publisher_implementation_sha256():
        raise AcquisitionError("publisher inventory implementation changed; prepare it again")
    encoded = read_publisher_bytes(root, "data/manifest/publisher-sources.jsonl")
    raw = read_publisher_bytes(
        root, f"data/raw/metadata/publisher/{proof.source_snapshot_sha256}.json"
    )
    if (
        hashlib.sha256(encoded).hexdigest() != proof.sources_sha256
        or hashlib.sha256(raw).hexdigest() != proof.source_snapshot_sha256
    ):
        raise AcquisitionError("publisher inventory snapshot or source digest disagrees")
    capture = PublisherSnapshot.model_validate_json(raw)
    cards = tuple(
        PublisherCatalogRow(
            record_id=f"ct-afsc-{card.card_key}",
            source_snapshot_sha256=proof.source_snapshot_sha256,
            candidate=card,
        )
        for card in capture.records
    )
    sources = tuple(
        PublisherDownloadSource.model_validate_json(line) for line in encoded.splitlines()
    )
    expected = _sources(cards)
    if (
        sources != expected
        or len({row.issue_id for row in sources}) != len(sources)
        or len({row.pdf_url for row in sources}) != len(sources)
        or proof.cards != len(cards)
        or proof.public_pdf_candidates != len(sources)
        or proof.contact_only != len(cards) - len(sources)
        or hashlib.sha256(
            b"".join(row.model_dump_json().encode() + b"\n" for row in cards)
        ).hexdigest()
        != proof.catalog_sha256
    ):
        raise AcquisitionError("publisher inventory disagrees with captured candidate membership")
    return PublisherInventory(root, proof, sources, cards)
