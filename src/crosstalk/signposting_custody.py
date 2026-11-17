"""Bounded independently checked retained linkset and crawler-policy source bytes."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from crosstalk.acquisition_policy import parse_robots
from crosstalk.index_observe import IndexReader
from crosstalk.locator_storage import read_metadata
from crosstalk.models import AcquisitionError

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.signposting_records import SignpostingSnapshot


def read_bound_metadata(root: Path, relative: str, expected_sha256: str) -> bytes:
    """Read at most 1 MB from a physical project-local file and check its receipt."""
    try:
        raw = read_metadata(IndexReader(root).path(relative))
    except OSError as error:
        raise AcquisitionError("retained locator metadata is missing or unavailable") from error
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise AcquisitionError("retained locator metadata disagrees with its source receipt")
    return raw


def require_retained_policy(root: Path, snapshot: SignpostingSnapshot) -> None:
    """Verify the recorded crawler policy itself and its permission for this request."""
    relative = f"data/raw/metadata/robots/{snapshot.robots_sha256}.json"
    raw = read_bound_metadata(root, relative, snapshot.robots_sha256)
    policy = parse_robots(raw.decode("utf-8", errors="strict"))
    if not policy.permits(snapshot.request_url):
        raise AcquisitionError("retained robots policy disallows this Signposting request")
