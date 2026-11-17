"""Bounded sequential HTTP and write-ahead publication of archive PDF payloads."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.acquisition_policy import RobotsPolicy, host_key, parse_robots
from crosstalk.models import AcquisitionError, DownloadReceipt, Issue, require_nps_url
from crosstalk.publisher_records import require_publisher_pdf
from crosstalk.source_inventory import PublisherDownloadSource

if TYPE_CHECKING:
    import httpx2

    from crosstalk.acquisition_ledger import AcquisitionAttempt
    from crosstalk.acquisition_records import PublisherFailureKind
    from crosstalk.source_inventory import DownloadSource

MAX_PDF_BYTES: Final = 100_000_000
MAX_ROBOTS_BYTES: Final = 1_000_000
MAX_RESPONSE_SECONDS: Final = 120.0


class ArchiveReader:
    """Mutable host clocks and policy cache for one strictly sequential run."""

    def __init__(self, client: httpx2.Client, delay: float, deadline: float | None = None) -> None:
        """Own one HTTP client and host pacing state without a source-host bypass."""
        self.client: httpx2.Client = client
        self.delay: float = delay
        self.last_request: dict[str, float] = {}
        self.policies: dict[str, RobotsPolicy] = {}
        self.attempt: AcquisitionAttempt | None = None
        self.deadline: float | None = deadline

    def new_work_available(self) -> bool:
        """Keep a final request reserve instead of starting an unbounded batch tail."""
        return self.deadline is None or time.monotonic() + 60.0 <= self.deadline

    def response_expired(self, started: float) -> bool:
        """Bound streaming by both the individual response and the finite batch."""
        now = time.monotonic()
        return now - started > MAX_RESPONSE_SECONDS or (
            self.deadline is not None and now >= self.deadline
        )

    def wait(self, host: str) -> None:
        """Space every request, including policy reads, by the host delay."""
        spacing = max(self.delay, self.policies.get(host, RobotsPolicy(())).delay)
        remaining = self.last_request.get(host, -spacing) + spacing - time.monotonic()
        if self.deadline is not None and time.monotonic() + max(0.0, remaining) >= self.deadline:
            raise AcquisitionError("finite acquisition network budget exhausted")
        if remaining > 0:
            time.sleep(remaining)
        self.last_request[host] = time.monotonic()

    def policy(self, url: str) -> RobotsPolicy:
        """Fetch bounded robots once per host and refuse unavailable policy."""
        host = host_key(url)
        if host not in self.policies:
            self.wait(host)
            started = time.monotonic()
            with self.client.stream("GET", f"https://{host}/robots.txt") as response:
                if response.status_code == 404:
                    policy = RobotsPolicy(())
                else:
                    if response.is_redirect:
                        raise AcquisitionError("redirected robots policy requires review")
                    _ = response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if self.response_expired(started):
                            raise AcquisitionError("robots request exceeded its time bound")
                        content.extend(chunk)
                        if len(content) > MAX_ROBOTS_BYTES:
                            raise AcquisitionError("robots policy exceeds the size bound")
                    policy = parse_robots(content.decode("utf-8", errors="strict"))
            self.policies[host] = policy
        return self.policies[host]

    def record_failure(self, _error: AcquisitionError | OSError | UnicodeError) -> None:
        """NPS failure handling is unchanged; specialized readers may record environment state."""

    def failure_kind(self, _receipt: DownloadReceipt) -> PublisherFailureKind | None:
        """Original NPS events have no publisher failure classification."""
        return None

    @staticmethod
    def _check_pdf_response(response: httpx2.Response) -> None:
        """Reject redirects and invalid advertised sizes before creating a payload file."""
        if response.is_redirect:
            raise AcquisitionError("PDF redirect requires a reviewed final URL in the inventory")
        _ = response.raise_for_status()
        advertised = response.headers.get("content-length")
        if advertised is not None and (
            len(advertised) > 12 or not advertised.isdecimal() or int(advertised) > MAX_PDF_BYTES
        ):
            raise AcquisitionError("advertised PDF size is invalid or exceeds size bound")

    def download(self, issue: DownloadSource, target: Path) -> DownloadReceipt:
        """Stream a PDF, record complete payload evidence, then publish without replacement."""
        match issue:
            case Issue():
                _ = require_nps_url(issue.pdf_url)
            case PublisherDownloadSource():
                _ = require_publisher_pdf(issue.pdf_url)
            case _:
                assert_never(issue)
        if not self.policy(issue.pdf_url).permits(issue.pdf_url):
            raise AcquisitionError("robots policy disallows this PDF URL")
        self.wait(host_key(issue.pdf_url))
        started = time.monotonic()
        with self.client.stream("GET", issue.pdf_url) as response:
            self._check_pdf_response(response)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{issue.issue_id}-", suffix=".part", dir=target.parent
            )
            digest, byte_count, prefix = hashlib.sha256(), 0, bytearray()
            with os.fdopen(descriptor, "wb") as stream:
                for chunk in response.iter_bytes():
                    if self.response_expired(started):
                        raise AcquisitionError(
                            f"PDF exceeded time bound; partial retained at {Path(temporary).name}"
                        )
                    byte_count += len(chunk)
                    if byte_count > MAX_PDF_BYTES:
                        raise AcquisitionError(
                            f"PDF exceeds size bound; partial retained at {Path(temporary).name}"
                        )
                    prefix.extend(chunk[: max(0, 5 - len(prefix))])
                    digest.update(chunk)
                    _ = stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            actual = digest.hexdigest()
            if bytes(prefix) != b"%PDF-" or (issue.sha256 is not None and actual != issue.sha256):
                raise AcquisitionError(
                    f"invalid PDF or digest mismatch; partial retained at {Path(temporary).name}"
                )
            receipt = DownloadReceipt(
                issue_id=issue.issue_id,
                pdf_url=issue.pdf_url,
                status="downloaded",
                path=str(target),
                sha256=actual,
                byte_count=byte_count,
            )
            if self.attempt is not None:
                self.attempt.prepare(Path(temporary), receipt)
            os.link(temporary, target)
            sync_directory(target.parent)
            Path(temporary).unlink()
            sync_directory(target.parent)
        return receipt
