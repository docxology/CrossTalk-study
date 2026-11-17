"""Finite sequential archival reads, independently gated by observed robots policy."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx2

from crosstalk.acquisition_policy import RobotsPolicy, parse_robots
from crosstalk.archival_cooldown import HostCooldown
from crosstalk.archival_records import (
    ArchivalError,
    ArchivalResponse,
    ResponseHeader,
    archive_fetch_url,
    archive_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchivalBody:
    """Actual retained response bytes and their independently measured metadata."""

    response: ArchivalResponse
    raw: bytes


def _append_chunk(raw: bytearray, chunk: bytes, maximum: int, deadline: float) -> None:
    """Preserve a bounded prefix before refusing an oversized or overlong response."""
    if time.monotonic() > deadline:
        raise ArchivalError("archival response exceeded its elapsed-time bound")
    if len(raw) + len(chunk) > maximum:
        raw.extend(chunk[: maximum - len(raw)])
        raise ArchivalError("archival response exceeded its streamed-byte bound")
    raw.extend(chunk)


class ArchivalHttp:
    """Mutable single-host pacing, cached policy and response evidence for one finite batch."""

    client: httpx2.Client
    deadline: float
    last_request: float | None
    policy_value: RobotsPolicy | None
    responses: list[ArchivalBody]
    observe: Callable[[ArchivalBody], None]
    cooldown: HostCooldown

    def __init__(
        self,
        client: httpx2.Client,
        observe: Callable[[ArchivalBody], None],
        *,
        state_root: Path,
        max_seconds: float = 120.0,
    ) -> None:
        """Use a genuine supplied client and durable response observer; no transport is bypassed."""
        if not 1 <= max_seconds <= 240:
            raise ArchivalError("archival batch duration must be within1-240 seconds")
        self.client = client
        self.observe = observe
        self.deadline = time.monotonic() + max_seconds
        self.last_request = None
        self.policy_value = None
        self.responses = []
        self.cooldown = HostCooldown(state_root)

    def _pace(self) -> None:
        """Honor ten seconds or the source's larger declared delay before another request."""
        delay = max(10.0, self.policy_value.delay if self.policy_value else 10.0)
        wait = (
            max(0.0, delay - (time.monotonic() - self.last_request)) if self.last_request else 0.0
        )
        if time.monotonic() + wait + 5 >= self.deadline:
            raise ArchivalError("archival batch has insufficient remaining request budget")
        if wait:
            time.sleep(wait)
        self.last_request = time.monotonic()

    def _read(self, url: str, maximum: int) -> ArchivalBody:
        """Retain complete or failed response evidence, with bounded bytes and elapsed time."""
        self._pace()
        delay = max(10.0, self.policy_value.delay if self.policy_value else 10.0)
        with self.cooldown.request_window(url, delay, self.deadline):
            return self._read_admitted(url, maximum)

    def _read_admitted(self, url: str, maximum: int) -> ArchivalBody:
        """Observe an actual response only while the persistent host request window is held."""
        began = time.monotonic()
        raw = bytearray()
        status: int | None = None
        headers: tuple[ResponseHeader, ...] = ()
        error: str | None = None
        try:
            remaining = min(30.0, self.deadline - began)
            timeout = httpx2.Timeout(
                connect=min(5.0, remaining),
                read=remaining,
                write=min(10.0, remaining),
                pool=min(10.0, remaining),
            )
            with self.client.stream(
                "GET", url, timeout=timeout, follow_redirects=False
            ) as response:
                status = response.status_code
                headers = tuple(
                    ResponseHeader(name=name, value=response.headers[name])
                    for name in (
                        "content-type",
                        "location",
                        "etag",
                        "last-modified",
                        "date",
                        "server",
                    )
                    if name in response.headers
                )
                for chunk in response.iter_bytes():
                    _append_chunk(raw, chunk, maximum, min(self.deadline, began + 60.0))
        except (httpx2.HTTPError, ArchivalError) as caught:
            error = str(caught)[:1000]
        result = ArchivalBody(
            ArchivalResponse(
                request_url=url,
                observed_at=datetime.now(UTC),
                status_code=status,
                headers=headers,
                body_sha256=hashlib.sha256(raw).hexdigest(),
                byte_count=len(raw),
                complete=error is None,
                error=error,
            ),
            bytes(raw),
        )
        self.observe(result)
        self.responses.append(result)
        return result

    def policy(self) -> RobotsPolicy:
        """Match existing production semantics:404 means absent policy;200 must be robots text."""
        if self.policy_value is not None:
            return self.policy_value
        body = self._read(archive_url("https://web.archive.org/robots.txt", robots=True), 1_000_000)
        if not body.response.complete:
            raise ArchivalError(body.response.error or "robots response is incomplete")
        if body.response.status_code == 404:
            self.policy_value = RobotsPolicy(())
            return self.policy_value
        if body.response.status_code != 200:
            raise ArchivalError(
                "robots status is unavailable or redirected; no archive resource requested"
            )
        try:
            text = body.raw.decode("utf-8-sig")
        except UnicodeError as error:
            raise ArchivalError("robots response is not UTF-8 text") from error
        if (
            "<html" in text.lower()
            or "<!doctype" in text.lower()
            or not re.search(r"^\s*user-agent\s*:", text, re.IGNORECASE | re.MULTILINE)
        ):
            raise ArchivalError("successful robots response is not a verifiable policy document")
        self.policy_value = parse_robots(text)
        return self.policy_value

    def fetch(self, url: str, *, maximum: int = 50_000_000) -> ArchivalBody:
        """Request one reviewed source-family resource after current policy admission."""
        _ = archive_fetch_url(url)
        if not 1 <= maximum <= 50_000_000:
            raise ArchivalError("resource byte bound must be within1-50MB")
        if not self.policy().permits(url):
            raise ArchivalError("observed robots policy disallows this exact archive path")
        body = self._read(url, maximum)
        if not body.response.complete or body.response.status_code != 200:
            raise ArchivalError(body.response.error or "archive resource unavailable or redirected")
        return body
