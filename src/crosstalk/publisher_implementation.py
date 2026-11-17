"""Exact local implementation identity for publisher inventory, transfer and coverage."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from crosstalk.locator_storage import read_metadata

PUBLISHER_IMPLEMENTATION_FILES: Final = (
    "publisher_implementation.py",
    "source_inventory.py",
    "publisher_records.py",
    "publisher_catalog.py",
    "publisher_dataset.py",
    "publisher_inventory.py",
    "publisher_acquisition_records.py",
    "publisher_http.py",
    "publisher_download.py",
    "publisher_index.py",
    "publisher_history.py",
    "publisher_limits.py",
    "publisher_policy.py",
    "acquire.py",
    "acquisition_http.py",
    "acquisition_ledger.py",
    "acquisition_records.py",
    "acquisition_policy.py",
    "acquisition_lock.py",
    "models.py",
    "records.py",
    "locator_storage.py",
    "index_observe.py",
    "index_records.py",
    "extraction_cache.py",
    "extract.py",
    "pdf_adapter.py",
    "visual_outputs.py",
)


def publisher_implementation_sha256() -> str:
    """Fingerprint the concrete source-family and reader dependencies before/after work."""
    digest = hashlib.sha256()
    for name in PUBLISHER_IMPLEMENTATION_FILES:
        digest.update(name.encode() + b"\0" + read_metadata(Path(__file__).with_name(name)))
    return digest.hexdigest()
