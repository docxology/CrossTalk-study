"""Publisher-only request, policy and finite-batch observations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from crosstalk.acquisition_records import DownloadRun
from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves this alias at runtime.
from crosstalk.records import Record

type PublisherEnvironment = Literal[
    "ready",
    "batch-finished",
    "budget-exhausted",
    "network-unavailable",
    "policy-unavailable",
    "storage-unavailable",
    "failure-cap",
    "retry-cap",
]
type PublisherAttemptState = Literal[
    "none",
    "source-failed",
    "network-unavailable",
    "policy-unavailable",
    "budget-exhausted",
    "local-refusal",
    "storage-unavailable",
]
type PublisherPolicyState = Literal[
    "parsed",
    "missing",
    "redirected",
    "http-error",
    "malformed",
    "oversized",
    "network-error",
    "time-exhausted",
]


class PublisherPolicyObservation(Record):
    """Retain the bounded decoded HTTP entity, not a claim about raw wire-transfer bytes."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    source_snapshot_sha256: Digest
    manifest_sha256: Digest
    run_id: str
    request_url: Literal["https://afscsoftware.dso.mil/robots.txt"]
    observed_at: str
    http_status: int | None
    content_type: str | None = None
    body_path: str
    body_sha256: Digest
    body_bytes: int = Field(ge=0, le=1_000_001)
    body_representation: Literal["httpx-decoded-entity"] = "httpx-decoded-entity"
    state: PublisherPolicyState
    error_type: str | None = None


class PublisherPolicyDecision(Record):
    """One exact public PDF path's robots decision under the current run's fresh policy."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    run_id: str
    attempt_id: str
    source_snapshot_sha256: Digest
    source_fingerprint: Digest
    pdf_url: str
    policy_observation_path: str
    policy_observation_sha256: Digest
    permitted: bool


class PublisherDownloadRun(DownloadRun):
    """Batch counters are separate from contact-only access gaps and historical completeness."""

    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    source_snapshot_sha256: Digest
    captured_cards: int
    implementation_sha256: Digest
    public_pdf_candidates: int
    contact_only: int
    dataset_path: Literal["data/publisher"] = "data/publisher"
    environment_state: PublisherEnvironment
    consecutive_failure_limit: int
    maximum_source_failures: int
    retry_capped_sources: int
    requested_new_work_limit: int | None
    minimum_delay_seconds: float
    network_budget_seconds: float
    observed_failures: int
    policy_observations: tuple[str, ...]
    expected_historical_total: None = None
    archive_complete: Literal[False] = False
