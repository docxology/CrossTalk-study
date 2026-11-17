"""Policy-respecting finite HTTP observations of documented DSpace Signposting."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import httpx2

from crosstalk.acquisition_policy import RobotsPolicy, host_key, parse_robots
from crosstalk.locator_storage import MAX_METADATA_BYTES, publish_metadata, read_metadata
from crosstalk.models import AcquisitionError, require_nps_url, safe_directory
from crosstalk.records import Record
from crosstalk.signposting_records import SignpostingSnapshot

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.acquisition_http import ArchiveReader
    from crosstalk.catalog import CatalogIssue
    from crosstalk.locator_records import LocatorBounds

BODY_SECONDS: Final = 60.0
REQUEST_RESERVE: Final = 70.0


class LocatorBudgetExpiredError(AcquisitionError):
    """A finite batch has insufficient time left to begin another request."""


@dataclass(frozen=True, slots=True)
class LocatorContext:
    """Current project and inventory bindings for one finite network batch."""

    root: Path
    catalog_sha256: str
    bounds: LocatorBounds


class RawResponse(Record):
    """A complete bounded response with independently persisted exact body bytes."""

    url: str
    observed_at: str
    status_code: int
    content_type: str
    body_path: str
    body_sha256: str
    http_version: str


class LocatorReader:
    """Own mutable host pacing and one deadline while keeping all responses immutable."""

    def __init__(self, context: LocatorContext, reader: ArchiveReader) -> None:
        """Share the established sequential archive host clock and HTTP client."""
        self.context: LocatorContext = context
        self.reader: ArchiveReader = reader
        self.deadline: float = time.monotonic() + context.bounds.max_seconds
        self.robots_sha256: str | None = None

    def available(self) -> bool:
        """Reserve one bounded request and any remaining host-policy wait."""
        host = "calhoun.nps.edu"
        policy = self.reader.policies.get(host, RobotsPolicy(()))
        spacing = max(self.context.bounds.delay, self.reader.delay, policy.delay)
        now = time.monotonic()
        waiting = max(0.0, self.reader.last_request.get(host, -spacing) + spacing - now)
        return now + waiting + REQUEST_RESERVE <= self.deadline

    @staticmethod
    def _collect(response: httpx2.Response, content: bytearray, started: float) -> None:
        """Accumulate at most the admitted body bound from the actual streaming parser."""
        for chunk in response.iter_bytes():
            remaining = MAX_METADATA_BYTES - len(content)
            content.extend(chunk[:remaining])
            if len(chunk) > remaining or time.monotonic() - started > BODY_SECONDS:
                raise AcquisitionError("locator response exceeded its byte or time bound")

    def _payload(self, response: httpx2.Response, started: float) -> bytes:
        """Retain an interrupted or over-bound prefix without accepting it as a snapshot."""
        content = bytearray()
        try:
            self._collect(response, content, started)
        except (httpx2.HTTPError, AcquisitionError) as error:
            directory = safe_directory(self.context.root, "data/raw/metadata/failed")
            partial = publish_metadata(directory, f"{uuid4().hex}.part", bytes(content))
            raise AcquisitionError(
                f"{error}; response prefix retained at {partial.name}"
            ) from error
        return bytes(content)

    def _get(self, url: str, relative: str) -> RawResponse:
        """Record redirects and error bodies without following any destination."""
        _ = require_nps_url(url)
        if not self.available():
            raise LocatorBudgetExpiredError("finite locator batch has no request budget remaining")
        self.reader.wait(host_key(url))
        started = time.monotonic()
        with self.reader.client.stream("GET", url) as response:
            raw = self._payload(response, started)
            digest = hashlib.sha256(raw).hexdigest()
            directory = safe_directory(self.context.root, f"data/raw/metadata/{relative}")
            path = publish_metadata(directory, f"{digest}.json", raw)
            observed = RawResponse(
                url=url,
                observed_at=datetime.now(UTC).isoformat(),
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                body_path=str(path.relative_to(self.context.root)),
                body_sha256=digest,
                http_version=response.http_version,
            )
        encoded = observed.model_dump_json().encode() + b"\n"
        directory = safe_directory(self.context.root, "data/raw/metadata/responses")
        _ = publish_metadata(directory, f"{hashlib.sha256(encoded).hexdigest()}.json", encoded)
        return observed

    def refresh_policy(self) -> str:
        """Persist a fresh robots response before admitting any item route."""
        response = self._get("https://calhoun.nps.edu/robots.txt", "robots")
        raw = read_metadata(self.context.root / response.body_path)
        if response.status_code == 404:
            policy = RobotsPolicy(())
        else:
            if response.status_code != 200:
                raise AcquisitionError("fresh robots response is unavailable or redirected")
            policy = parse_robots(raw.decode("utf-8", errors="strict"))
        self.reader.policies["calhoun.nps.edu"] = policy
        self.robots_sha256 = response.body_sha256
        return response.body_sha256

    def fetch(self, row: CatalogIssue) -> SignpostingSnapshot:
        """Resolve only the documented route for one already captured publication UUID."""
        url = f"https://calhoun.nps.edu/server/signposting/linksets/{row.item_id}/json"
        robots_sha256 = self.robots_sha256 or self.refresh_policy()
        if not self.reader.policies["calhoun.nps.edu"].permits(url):
            raise AcquisitionError("fresh robots policy disallows this Signposting route")
        response = self._get(url, "signposting")
        return SignpostingSnapshot(
            request_url=response.url,
            observed_at=response.observed_at,
            status_code=response.status_code,
            content_type=response.content_type,
            body_path=response.body_path,
            body_sha256=response.body_sha256,
            catalog_sha256=self.context.catalog_sha256,
            robots_sha256=robots_sha256,
            final_url=response.url,
            http_version=response.http_version,
        )
