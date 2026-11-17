"""A second explicit publisher/CDN relation; exact receipt bytes supply any private query."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from pydantic import TypeAdapter

from crosstalk.archival_records import (
    ArchivalCandidate,
    ArchivalError,
    ArchivalResponse,
    Digest,
    PublisherCdnWitness,
    archive_fetch_url,
)
from crosstalk.case_files import read_bytes

if TYPE_CHECKING:
    from pathlib import Path

DIGEST: Final = TypeAdapter(Digest)


def public_locator(url: str) -> str:
    """Diagnostics omit historical query values; original exact values stay in private receipts."""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _candidate_sha(candidate: ArchivalCandidate) -> str:
    raw = candidate.model_dump_json(exclude={"publisher_cdn_witness", "redirect_chain"}).encode()
    return hashlib.sha256(raw).hexdigest()


def _target(root: Path, candidate: ArchivalCandidate, response_sha256: str) -> str:
    digest = DIGEST.validate_python(response_sha256)
    raw = read_bytes(root / "output/data/archival/responses" / f"{digest}.json", 32_000)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ArchivalError("retained publisher/CDN response changed")
    response = ArchivalResponse.model_validate_json(raw)
    if (
        not response.complete
        or response.request_url != candidate.pdf_url
        or response.status_code not in {301, 302, 303, 307, 308}
    ):
        raise ArchivalError("CDN resolution requires the actual first-hop publisher redirect")
    locations = tuple(header.value for header in response.headers if header.name == "location")
    if len(locations) != 1:
        raise ArchivalError("publisher response does not supply one exact CDN Location")
    target = archive_fetch_url(urljoin(response.request_url, locations[0]))
    parsed = urlsplit(target)
    original = urlsplit(unquote(parsed.path.split("/", 3)[3]))
    if (
        original.hostname != "static1.1.sqspcdn.com"
        or original.path.rsplit("/", 1)[-1]
        != f"{candidate.year:04}{candidate.month:02}-0-Issue.pdf"
    ):
        raise ArchivalError("observed CDN resource is outside the reviewed host/issue relation")
    return target


def resolve_publisher_cdn(
    root: Path, candidate: ArchivalCandidate, response_sha256: str
) -> ArchivalCandidate:
    """Bind the second actual response without treating it as the same original resource."""
    if candidate.redirect_witness is None or candidate.publisher_cdn_witness is not None:
        raise ArchivalError("publisher/CDN resolution requires exactly one prior approved hop")
    target = _target(root, candidate, response_sha256)
    witness = PublisherCdnWitness(
        resolved_candidate_sha256=_candidate_sha(candidate),
        response_sha256=response_sha256,
        target_url_sha256=hashlib.sha256(target.encode()).hexdigest(),
        public_target_url=public_locator(target),
    )
    return candidate.model_copy(update={"publisher_cdn_witness": witness})


def effective_archive_url(root: Path, candidate: ArchivalCandidate) -> str:
    """Recheck both the source candidate and exact response-derived target before a request."""
    witness = candidate.publisher_cdn_witness
    if witness is None:
        return candidate.pdf_url
    if candidate.redirect_witness is None:
        raise ArchivalError("CDN witness lacks its original first-hop source relation")
    baseline = candidate.model_copy(update={"publisher_cdn_witness": None})
    target = _target(root, baseline, witness.response_sha256)
    if (
        witness.resolved_candidate_sha256 != _candidate_sha(baseline)
        or witness.target_url_sha256 != hashlib.sha256(target.encode()).hexdigest()
        or witness.public_target_url != public_locator(target)
    ):
        raise ArchivalError("publisher/CDN candidate or exact retained target changed")
    return target
