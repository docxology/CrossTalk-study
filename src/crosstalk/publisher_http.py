"""Publisher HTTP uses the shared streamer with fresh retained policy and explicit failures."""

from __future__ import annotations

import hashlib
import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never, override

import httpx2

from crosstalk.acquisition_http import MAX_ROBOTS_BYTES, ArchiveReader
from crosstalk.acquisition_policy import RobotsPolicy, host_key
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import AcquisitionError, Issue, safe_directory
from crosstalk.publisher_acquisition_records import (
    PublisherAttemptState,
    PublisherPolicyDecision,
    PublisherPolicyObservation,
    PublisherPolicyState,
)
from crosstalk.publisher_policy import (
    PublisherBudgetError,
    PublisherPolicyError,
    classify_publisher_failure,
    parse_publisher_policy,
    storage_unavailable,
)
from crosstalk.publisher_records import require_publisher_pdf
from crosstalk.source_inventory import PublisherDownloadSource

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.acquisition_records import PublisherFailureKind
    from crosstalk.models import DownloadReceipt
    from crosstalk.publisher_inventory import PublisherInventory
    from crosstalk.source_inventory import DownloadSource


class PublisherArchiveReader(ArchiveReader):
    """Mutable request state belongs to one publisher dataset and one finite acquisition run."""

    def __init__(
        self,
        client: httpx2.Client,
        delay: float,
        deadline: float,
        inventory: PublisherInventory,
        run_id: str,
    ) -> None:
        """Require redirect refusal before any request and retain policy separately per run."""
        if client.follow_redirects:
            raise AcquisitionError("publisher client must refuse redirects")
        if (
            not math.isfinite(delay)
            or delay < 10
            or not math.isfinite(deadline)
            or deadline - time.monotonic() > 240
        ):
            raise AcquisitionError(
                "publisher reader requires finite pacing and a 240-second deadline"
            )
        super().__init__(client, delay, deadline)
        self.inventory: PublisherInventory = inventory
        self.run_id: str = run_id
        self.last_failure: PublisherAttemptState = "none"
        self.observations: dict[str, tuple[PublisherPolicyObservation, str, str]] = {}
        self.content_type: str | None = None

    @override
    def record_failure(self, _error: AcquisitionError | OSError | UnicodeError) -> None:
        """Recovery/local failures also classify storage exhaustion before durable finish."""
        if isinstance(_error, OSError) and storage_unavailable(_error):
            self.last_failure = "storage-unavailable"

    @override
    def failure_kind(self, _receipt: DownloadReceipt) -> PublisherFailureKind | None:
        """Only actual source/local-integrity failures consume a persistent locator retry slot."""
        return classify_publisher_failure(self.last_failure, _receipt)

    @override
    def wait(self, host: str) -> None:
        """Preserve shared pacing while distinguishing an unfittable request from source failure."""
        spacing = max(self.delay, self.policies.get(host, RobotsPolicy(())).delay)
        remaining = self.last_request.get(host, -spacing) + spacing - time.monotonic()
        if self.deadline is not None and time.monotonic() + max(0.0, remaining) >= self.deadline:
            raise PublisherBudgetError(
                "finite publisher network budget cannot fit the next request"
            )
        super().wait(host)

    def _retain(
        self,
        body: bytes,
        status: int | None,
        state: PublisherPolicyState,
        error_type: str | None = None,
    ) -> tuple[PublisherPolicyObservation, str, str]:
        root = self.inventory.root
        digest = hashlib.sha256(body).hexdigest()
        body_path = f"data/raw/metadata/robots/{digest}.txt"
        directory = safe_directory(root, "data/raw/metadata/robots")
        _ = publish_metadata(directory, f"{digest}.txt", body)
        row = PublisherPolicyObservation(
            source_snapshot_sha256=self.inventory.proof.source_snapshot_sha256,
            manifest_sha256=self.inventory.proof.sources_sha256,
            run_id=self.run_id,
            request_url="https://afscsoftware.dso.mil/robots.txt",
            observed_at=datetime.now(UTC).isoformat(),
            http_status=status,
            content_type=self.content_type,
            body_path=body_path,
            body_sha256=digest,
            body_bytes=len(body),
            state=state,
            error_type=error_type,
        )
        encoded = row.model_dump_json().encode() + b"\n"
        path = f"output/data/publisher-policy/{self.run_id}.json"
        directory = safe_directory(root, "output/data/publisher-policy")
        _ = publish_metadata(directory, f"{self.run_id}.json", encoded)
        return row, path, hashlib.sha256(encoded).hexdigest()

    def _fresh_policy(self) -> tuple[RobotsPolicy, tuple[PublisherPolicyObservation, str, str]]:
        host = "afscsoftware.dso.mil"
        self.wait(host)
        started, body, status = time.monotonic(), bytearray(), None
        try:
            with self.client.stream("GET", f"https://{host}/robots.txt") as response:
                status = response.status_code
                declared = response.headers.get("content-type")
                self.content_type = declared[:200] if declared is not None else None
                for chunk in response.iter_bytes():
                    if self.response_expired(started):
                        evidence = self._retain(bytes(body), status, "time-exhausted")
                        self.observations[host] = evidence
                        raise PublisherBudgetError("publisher robots time bound exhausted")
                    body.extend(chunk[: MAX_ROBOTS_BYTES + 1 - len(body)])
                    if len(body) > MAX_ROBOTS_BYTES:
                        evidence = self._retain(bytes(body), status, "oversized")
                        self.observations[host] = evidence
                        raise PublisherPolicyError("publisher robots response exceeds its bound")
                if response.is_redirect:
                    evidence = self._retain(bytes(body), status, "redirected")
                    self.observations[host] = evidence
                    raise PublisherPolicyError("publisher robots redirect requires review")
                if status == 404:
                    return RobotsPolicy(()), self._retain(bytes(body), status, "missing")
                if not 200 <= status < 300:
                    evidence = self._retain(bytes(body), status, "http-error")
                    self.observations[host] = evidence
                    raise PublisherPolicyError(f"publisher robots HTTP response {status}")
        except httpx2.HTTPError as error:
            evidence = self._retain(bytes(body), status, "network-error", type(error).__name__)
            self.observations[host] = evidence
            raise PublisherPolicyError("publisher robots network unavailable") from error
        try:
            policy = parse_publisher_policy(bytes(body), self.content_type)
        except (ValueError, UnicodeError) as error:
            evidence = self._retain(bytes(body), status, "malformed", type(error).__name__)
            self.observations[host] = evidence
            raise PublisherPolicyError("publisher robots policy is malformed") from error
        return policy, self._retain(bytes(body), status, "parsed")

    @override
    def policy(self, url: str) -> RobotsPolicy:
        """A caller cannot prefill the inherited cache to evade fresh publisher policy evidence."""
        _ = require_publisher_pdf(url)
        attempt = self.attempt
        if attempt is None or (
            attempt.started.source_family != "afsc-publisher"
            or attempt.started.source_snapshot_sha256 != self.inventory.proof.source_snapshot_sha256
            or attempt.started.manifest_sha256 != self.inventory.proof.sources_sha256
            or attempt.started.run_id != self.run_id
            or attempt.started.pdf_url != url
        ):
            raise AcquisitionError("publisher policy requires a source-bound acquisition attempt")
        host = host_key(url)
        if host not in self.observations:
            policy, evidence = self._fresh_policy()
            self.policies[host], self.observations[host] = policy, evidence
        observation, path, digest = self.observations[host]
        match observation.state:
            case "parsed" | "missing":
                pass
            case (
                "redirected"
                | "http-error"
                | "malformed"
                | "oversized"
                | "network-error"
                | "time-exhausted"
            ):
                raise PublisherPolicyError("publisher robots policy is unavailable")
            case _:
                assert_never(observation.state)
        policy = self.policies[host]
        decision = PublisherPolicyDecision(
            run_id=self.run_id,
            attempt_id=attempt.started.attempt_id,
            source_snapshot_sha256=self.inventory.proof.source_snapshot_sha256,
            source_fingerprint=attempt.started.issue_sha256,
            pdf_url=url,
            policy_observation_path=path,
            policy_observation_sha256=digest,
            permitted=policy.permits(url),
        )
        directory = safe_directory(self.inventory.root, "output/data/publisher-policy/decisions")
        _ = publish_metadata(
            directory,
            f"{attempt.started.attempt_id}.json",
            decision.model_dump_json().encode() + b"\n",
        )
        return policy

    @override
    def download(self, issue: DownloadSource, target: Path) -> DownloadReceipt:
        """Expose environment failures to the publisher controller without altering NPS behavior."""
        match issue:
            case PublisherDownloadSource():
                pass
            case Issue():
                raise AcquisitionError("publisher reader refuses an NPS source")
            case _:
                assert_never(issue)
        self.last_failure = "none"
        try:
            return super().download(issue, target)
        except PublisherBudgetError:
            self.last_failure = "budget-exhausted"
            raise
        except PublisherPolicyError:
            self.last_failure = "policy-unavailable"
            raise
        except httpx2.HTTPStatusError as error:
            self.last_failure = (
                "network-unavailable"
                if error.response.status_code == 429 or error.response.status_code >= 500
                else "source-failed"
            )
            raise
        except httpx2.HTTPError:
            self.last_failure = "network-unavailable"
            raise
        except AcquisitionError:
            self.last_failure = (
                "budget-exhausted"
                if self.deadline is not None and time.monotonic() >= self.deadline
                else "source-failed"
            )
            raise
        except OSError as error:
            self.last_failure = (
                "storage-unavailable" if storage_unavailable(error) else "local-refusal"
            )
            raise
