"""Normalize independently captured publisher metadata with idempotent output bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

from crosstalk.acquisition_lock import project_lock
from crosstalk.locator_storage import publish_metadata, read_metadata
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.publisher_records import (
    ContactPublisherCard,
    PublicPublisherCard,
    PublisherCatalogRow,
    PublisherCatalogSummary,
    PublisherSnapshot,
)
from crosstalk.records import write_records

if TYPE_CHECKING:
    from pydantic import BaseModel

OUTPUT_NAMES: Final = ("publisher-catalog.jsonl", "publisher-observation.jsonl")
PRODUCERS: Final = (
    "publisher_catalog.py",
    "publisher_records.py",
    "models.py",
    "records.py",
    "acquisition_lock.py",
    "locator_storage.py",
    "acquisition_ledger.py",
    "acquisition_records.py",
    "source_inventory.py",
)


@dataclass(frozen=True, slots=True)
class PublisherCatalog:
    """An independently checked current discovery index and its scope receipt."""

    summary: PublisherCatalogSummary
    rows: tuple[PublisherCatalogRow, ...]


def _implementation() -> str:
    """Bind all local producer modules involved in this metadata import."""
    digest = hashlib.sha256()
    for name in PRODUCERS:
        digest.update(name.encode() + b"\0" + read_metadata(Path(__file__).with_name(name)))
    return digest.hexdigest()


def _publish_changed(path: Path, records: tuple[BaseModel, ...]) -> None:
    """Preserve timestamps for unchanged catalog artifacts; never follow an output link."""
    encoded = "".join(record.model_dump_json() + "\n" for record in records).encode()
    try:
        existing = read_metadata(path)
    except FileNotFoundError:
        existing = None
    if existing != encoded:
        write_records(path, records)


def import_publisher_catalog(snapshot_path: Path, root: Path) -> PublisherCatalogSummary:
    """Retain every displayed card and access state separately from the Calhoun series."""
    with project_lock(root):
        return _import(snapshot_path, root)


def _preflight(snapshot_path: Path, directory: Path) -> None:
    """Reject unsafe output targets or input aliases before modifying either artifact."""
    identity = snapshot_path.stat()
    for name in OUTPUT_NAMES:
        target = directory / name
        try:
            _ = read_metadata(target)
        except FileNotFoundError:
            continue
        target_identity = target.stat()
        if (identity.st_dev, identity.st_ino) == (target_identity.st_dev, target_identity.st_ino):
            raise AcquisitionError("publisher input must not alias a normalized output")


def _import(snapshot_path: Path, root: Path) -> PublisherCatalogSummary:
    """Publish only after source binding and both output targets pass admission."""
    raw = read_metadata(snapshot_path)
    snapshot = PublisherSnapshot.model_validate_json(raw)
    digest = hashlib.sha256(raw).hexdigest()
    implementation = _implementation()
    directory = safe_directory(root, "data/manifest")
    _preflight(snapshot_path, directory)
    rows: list[PublisherCatalogRow] = []
    keys: set[str] = set()
    pdfs: set[str] = set()
    contact_only = 0
    for card in snapshot.records:
        if card.card_key in keys:
            raise AcquisitionError("duplicate publisher card key")
        keys.add(card.card_key)
        match card:
            case PublicPublisherCard(pdf_url=pdf_url):
                if pdf_url in pdfs:
                    raise AcquisitionError(
                        "duplicate publisher PDF locator requires reconciliation"
                    )
                pdfs.add(pdf_url)
            case ContactPublisherCard():
                contact_only += 1
            case _:
                assert_never(card)
        rows.append(
            PublisherCatalogRow(
                record_id=f"ct-afsc-{card.card_key}",
                source_snapshot_sha256=digest,
                candidate=card,
            )
        )
    summary = PublisherCatalogSummary(
        snapshot_sha256=digest,
        catalog_sha256=hashlib.sha256(
            "".join(row.model_dump_json() + "\n" for row in rows).encode()
        ).hexdigest(),
        implementation_sha256=implementation,
        observed_at=snapshot.observed_at,
        records=len(rows),
        public_pdf_locators=len(pdfs),
        contact_only=contact_only,
    )
    if hashlib.sha256(read_metadata(snapshot_path)).hexdigest() != digest:
        raise AcquisitionError("publisher snapshot changed during normalization")
    retained = safe_directory(root, "data/raw/metadata/publisher")
    _ = publish_metadata(retained, f"{digest}.json", raw)
    _publish_changed(directory / "publisher-catalog.jsonl", tuple(rows))
    _publish_changed(directory / "publisher-observation.jsonl", (summary,))
    if _implementation() != implementation:
        raise AcquisitionError("publisher implementation changed during publication")
    return summary


def read_publisher_catalog(root: Path) -> PublisherCatalog:
    """Refuse stale or mismatched frames rather than trusting saved metadata counts."""
    with project_lock(root):
        directory = safe_directory(root, "data/manifest")
        summary_raw = read_metadata(directory / OUTPUT_NAMES[1])
        summary = PublisherCatalogSummary.model_validate_json(summary_raw)
        raw = read_metadata(directory / OUTPUT_NAMES[0])
        snapshot = read_metadata(
            root / "data/raw/metadata/publisher" / f"{summary.snapshot_sha256}.json"
        )
        if (
            hashlib.sha256(raw).hexdigest() != summary.catalog_sha256
            or hashlib.sha256(snapshot).hexdigest() != summary.snapshot_sha256
            or _implementation() != summary.implementation_sha256
        ):
            raise AcquisitionError("publisher frame is stale or its source bindings disagree")
        rows = tuple(PublisherCatalogRow.model_validate_json(line) for line in raw.splitlines())
        captured = PublisherSnapshot.model_validate_json(snapshot)
        expected = tuple(
            PublisherCatalogRow(
                record_id=f"ct-afsc-{card.card_key}",
                source_snapshot_sha256=summary.snapshot_sha256,
                candidate=card,
            )
            for card in captured.records
        )
        public = sum(row.candidate.access == "public-pdf" for row in rows)
        if (
            len(rows) != summary.records
            or len({row.record_id for row in rows}) != len(rows)
            or any(row.source_snapshot_sha256 != summary.snapshot_sha256 for row in rows)
            or rows != expected
            or captured.observed_at != summary.observed_at
            or summary.public_pdf_locators != public
            or summary.contact_only != len(rows) - public
        ):
            raise AcquisitionError("publisher frame is stale or its source bindings disagree")
        return PublisherCatalog(summary, rows)
