"""Current index semantics identity, independent of cache bytes and observation dates."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from crosstalk.extraction_method import EXTRACTION_IMPLEMENTATION_FILES
from crosstalk.models import AcquisitionError

INDEX_IMPLEMENTATION_FILES: Final = (
    "index_implementation.py",
    "corpus_index.py",
    "index_identity.py",
    "index_observe.py",
    "index_history.py",
    "index_store.py",
    "index_records.py",
    "index_read.py",
    "catalog.py",
    "models.py",
    "records.py",
    "acquisition_lock.py",
    "acquisition_ledger.py",
    "acquisition_records.py",
    "source_inventory.py",
    "publisher_records.py",
    *EXTRACTION_IMPLEMENTATION_FILES,
)


def index_implementation_sha256() -> str:
    """Bind every local dependency that validates, derives or publishes index states."""
    digest = hashlib.sha256()
    for filename in INDEX_IMPLEMENTATION_FILES:
        path = Path(__file__).with_name(filename)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise AcquisitionError("index implementation source is unavailable or oversized")
        digest.update(filename.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
