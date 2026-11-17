"""Finite locator work bounds and immutable per-item observation events."""

from typing import Annotated, Literal

from pydantic import Field

from crosstalk.models import Digest
from crosstalk.records import Record


class LocatorBounds(Record):
    """At most one finite sequential batch, including robots and request waiting."""

    limit: int = Field(default=10, ge=1, le=10_000)
    delay: float = Field(default=10.0, ge=10.0, allow_inf_nan=False)
    max_seconds: float = Field(default=240.0, ge=80.0, le=240.0, allow_inf_nan=False)


class LocatorEvent(Record):
    """One durable attempt stage; historical failures never grant source admission."""

    attempt_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    issue_id: str
    item_id: str
    catalog_sha256: Digest
    observed_at: str
    stage: Literal["started", "response", "finished"]
    snapshot_path: str | None = None
    snapshot_sha256: Digest | None = None
    outcome: Literal["resolved", "failed"] | None = None
    error: str | None = None


class LocatorRun(Record):
    """Current finite catalog-resolution accounting, never archive-completeness proof."""

    run_id: str
    observed_at: str
    catalog_sha256: Digest
    catalog_count: int
    verified_existing: int
    recovered: int
    attempted: int
    resolved: int
    failed: int
    deferred: int
    time_budget_exhausted: bool
    archive_complete: Literal[False] = False
