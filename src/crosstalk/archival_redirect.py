"""Explicit one-hop replay after a retained same-resource HTTP Location observation."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import TypeAdapter

from crosstalk.archival_records import (
    ArchivalCandidate,
    ArchivalError,
    ArchivalResponse,
    Digest,
    RedirectWitness,
    archive_url,
)
from crosstalk.case_files import read_bytes

if TYPE_CHECKING:
    from pathlib import Path

DIGEST: Final = TypeAdapter(Digest)


def candidate_sha256(candidate: ArchivalCandidate) -> str:
    """Bind the original typed candidate independently of an optional resolution witness."""
    raw = candidate.model_dump_json(
        exclude={"redirect_witness", "publisher_cdn_witness", "redirect_chain"}
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def original_resource(url: str) -> str:
    """Compare decoded original URLs; only the observed replay timestamp may differ."""
    _ = archive_url(url)
    return unquote(urlsplit(url).path.split("/", 3)[3])


def _response(root: Path, digest: str) -> ArchivalResponse:
    digest = DIGEST.validate_python(digest)
    raw = read_bytes(root / "output/data/archival/responses" / f"{digest}.json", 32_000)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ArchivalError("retained redirect response changed")
    return ArchivalResponse.model_validate_json(raw)


def _target(response: ArchivalResponse, original: str) -> str:
    if (
        not response.complete
        or response.request_url != original
        or response.status_code not in {301, 302, 303, 307, 308}
    ):
        raise ArchivalError("one-hop resolution requires the actual original resource redirect")
    locations = tuple(header.value for header in response.headers if header.name == "location")
    if len(locations) != 1:
        raise ArchivalError("redirect response does not supply one exact Location")
    target = archive_url(urljoin(original, locations[0]))
    if target == original or original_resource(target) != original_resource(original):
        raise ArchivalError(
            "redirect changes the decoded original resource or repeats the same URL"
        )
    return target


def resolve_observed_redirect(
    root: Path, candidate: ArchivalCandidate, response_sha256: str
) -> ArchivalCandidate:
    """Apply the Root-reviewed same-resource rule to one observed response, never a chain."""
    if candidate.redirect_witness is not None:
        raise ArchivalError("a second redirect hop needs separate review and is refused")
    original = urljoin(candidate.source_url, candidate.href)
    if original != candidate.pdf_url:
        raise ArchivalError("original candidate no longer matches its captured anchor")
    target = _target(_response(root, response_sha256), original)
    witness = RedirectWitness(
        source_candidate_sha256=candidate_sha256(candidate),
        response_sha256=response_sha256,
        target_url=target,
    )
    return candidate.model_copy(update={"pdf_url": target, "redirect_witness": witness})


def admit_redirect(root: Path, candidate: ArchivalCandidate, original: str) -> None:
    """Reproduce exact candidate/response/Location bindings before any retrieval or reuse."""
    witness = candidate.redirect_witness
    if witness is None:
        if candidate.pdf_url != original:
            raise ArchivalError("direct PDF URL differs from its actual retained publisher href")
        return
    baseline = candidate.model_copy(update={"pdf_url": original, "redirect_witness": None})
    target = _target(_response(root, witness.response_sha256), original)
    if (
        witness.source_candidate_sha256 != candidate_sha256(baseline)
        or witness.target_url != target
        or candidate.pdf_url != target
    ):
        raise ArchivalError("reviewed one-hop candidate, response or exact Location differs")
