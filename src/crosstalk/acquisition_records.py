"""Source-bound append-only acquisition events and current run counters."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from crosstalk.models import AcquisitionError, Digest, DownloadReceipt, DownloadSummary

if TYPE_CHECKING:
    from pathlib import Path


type PublisherFailureKind = Literal["source", "environment"]


class AttemptEvent(BaseModel):
    """One immutable stage in an acquisition attempt, not current filesystem proof."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    attempt_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    issue_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")]
    issue_sha256: Digest
    manifest_sha256: Digest
    observed_at: str
    stage: Literal["started", "prepared", "finished"]
    pdf_url: str
    source_family: Literal["nps-calhoun", "afsc-publisher"] = "nps-calhoun"
    source_snapshot_sha256: Digest | None = None
    source_pinned_sha256: Digest | None = None
    publisher_failure_kind: PublisherFailureKind | None = None
    partial_name: str | None = None
    receipt: DownloadReceipt | None = None

    @model_validator(mode="after")
    def family_binding(self) -> AttemptEvent:
        """Legacy NPS rows retain defaults; publisher attempts require their capture identity."""
        match self.source_family:
            case "nps-calhoun":
                valid = (
                    self.source_snapshot_sha256 is None
                    and self.source_pinned_sha256 is None
                    and self.publisher_failure_kind is None
                )
            case "afsc-publisher":
                valid = self.source_snapshot_sha256 is not None
            case _:
                assert_never(self.source_family)
        if not valid:
            raise AcquisitionError("acquisition family and captured-snapshot binding disagree")
        return self


class DownloadRun(DownloadSummary):
    """Current byte observations plus bounded new work; verified files consume no limit."""

    run_id: str
    verified_existing: int
    attempted: int
    deferred: int
    time_budget_exhausted: bool = False
    ledger_directory: str = "output/data/acquisition-ledger"


SUMMARY: Final = TypeAdapter(DownloadRun | DownloadSummary)


def read_download_summary(path: Path) -> DownloadSummary:
    """Parse bounded legacy/current observations without following filesystem aliases."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcquisitionError("download summary is not a regular file")
        raw = stream.read(20_000_001)
    if len(raw) > 20_000_000:
        raise AcquisitionError("download summary exceeds its 20 MB bound")
    return SUMMARY.validate_json(raw)
