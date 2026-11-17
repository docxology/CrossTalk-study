"""Bounded explicit redirect observations; every target comes from an actual retained response."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import TypeAdapter

from crosstalk.archival_cdn import public_locator
from crosstalk.archival_records import (
    ArchivalCandidate,
    ArchivalError,
    ArchivalResponse,
    Digest,
    ObservedHop,
    archive_fetch_url,
)
from crosstalk.archival_redirect import candidate_sha256
from crosstalk.case_files import read_bytes

if TYPE_CHECKING:
    from pathlib import Path

DIGEST: Final = TypeAdapter(Digest)
MAY_RESPONSE: Final = "57402cee25227065046454e3006f795c96bd28c33aedd5e49cb7a065d206e7d0"
MAY_CANDIDATE: Final = "8079ca254de5ab212862941fdb2ad1ff5da683831d1822d1ef0b6ce4168591ff"
MAY_SOURCE: Final = (
    "https://web.archive.org/web/20171218072610/http://www.crosstalkonline.org/"
    "storage/issue-archives/2001/200105/200105-0-Issue.pdf"
)
MAY_TARGET: Final = (
    "https://web.archive.org/web/20170812132712/http://www.crosstalkonline.org/"
    "storage/issue-archives/2001/200105/200105-0-issue.pdf"
)
JANUARY_RESPONSE: Final = "9038da0f39bcd154ac8ec3d56994fc00a459bc715ed335ce9723ecc830c0d1f3"
JANUARY_CANDIDATE: Final = "f56b732a0541690cf473faeeb3e1853dc0f80a38d3f4f4d197a8e1df00d65e56"
JANUARY_SOURCE: Final = (
    "https://web.archive.org/web/20171218072610/http://www.crosstalkonline.org/"
    "storage/issue-archives/2006/200601/200601-0-Issue.pdf"
)
JANUARY_TARGET: Final = (
    "https://web.archive.org/web/20170812132705/http://www.crosstalkonline.org/"
    "storage/issue-archives/2006/200601/200601-0-issue.pdf"
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _original(url: str) -> str:
    """Replay timing can differ; decoded original URI and exact private query must agree."""
    parsed = urlsplit(url)
    original = unquote(parsed.path.split("/", 3)[3])
    return original + ("?" + parsed.query if parsed.query else "")


def _relation(
    source: str, target: str, candidate: ArchivalCandidate, response_sha256: str
) -> Literal[
    "replay-retiming",
    "publisher-to-reviewed-cdn",
    "reviewed-may-2001-spelling",
    "reviewed-january-2006-spelling",
]:
    if (
        response_sha256 == MAY_RESPONSE
        and source == MAY_SOURCE
        and target == MAY_TARGET
        and candidate_sha256(candidate) == MAY_CANDIDATE
    ):
        return "reviewed-may-2001-spelling"
    if (
        response_sha256 == JANUARY_RESPONSE
        and source == JANUARY_SOURCE
        and target == JANUARY_TARGET
        and candidate_sha256(candidate) == JANUARY_CANDIDATE
    ):
        return "reviewed-january-2006-spelling"
    if _original(source) == _original(target):
        return "replay-retiming"
    before, after = urlsplit(_original(source)), urlsplit(_original(target))
    expected = f"{candidate.year:04}{candidate.month:02}-0-Issue.pdf"
    reviewed_alias = (source, candidate_sha256(candidate), response_sha256) in (
        (
            MAY_TARGET,
            MAY_CANDIDATE,
            "4d6c2f02c0f9128c69e0880a35040937ba2f68e186d686afa1b5e55c5dd34053",
        ),
        (
            JANUARY_TARGET,
            JANUARY_CANDIDATE,
            "67004e66d46f71b6f5246320820d8a7602a72c87dd93d365ecded6b159fc2689",
        ),
    )
    if (
        before.hostname == "www.crosstalkonline.org"
        and after.hostname == "static1.1.sqspcdn.com"
        and (before.path.rsplit("/", 1)[-1] == expected or reviewed_alias)
        and after.path.rsplit("/", 1)[-1] == expected
    ):
        return "publisher-to-reviewed-cdn"
    raise ArchivalError(
        "redirect relation changes an unreviewed original host, path, query or issue"
    )


def _observed_target(root: Path, current: str, digest: str) -> str:
    digest = DIGEST.validate_python(digest)
    raw = read_bytes(root / "output/data/archival/responses" / f"{digest}.json", 32_000)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ArchivalError("record-bound chain response changed")
    response = ArchivalResponse.model_validate_json(raw)
    if not response.complete or response.request_url != current or response.status_code != 302:
        raise ArchivalError(
            "redirect chain requires the complete actual302 for its exact current URI"
        )
    locations = tuple(header.value for header in response.headers if header.name == "location")
    if len(locations) != 1:
        raise ArchivalError("redirect response lacks one exact observed Location")
    return archive_fetch_url(urljoin(current, locations[0]))


def _replay(root: Path, candidate: ArchivalCandidate, initial: str) -> tuple[str, frozenset[str]]:
    """Independently reconstruct all approved edges before each retrieval or resume."""
    current = initial
    seen = {initial}
    basis = candidate_sha256(candidate)
    for hop in candidate.redirect_chain:
        target = _observed_target(root, current, hop.response_sha256)
        if target in seen:
            raise ArchivalError("observed archive redirect chain contains a loop")
        relation = _relation(current, target, candidate, hop.response_sha256)
        if (
            hop.candidate_basis_sha256 != basis
            or hop.request_url_sha256 != _hash(current)
            or hop.target_url_sha256 != _hash(target)
            or hop.public_target_url != public_locator(target)
            or hop.relation != relation
        ):
            raise ArchivalError("candidate basis or exact retained redirect-chain edge disagrees")
        seen.add(target)
        current = target
    return current, frozenset(seen)


def effective_chain_url(root: Path, candidate: ArchivalCandidate, initial: str) -> str:
    """Legacy receipts remain readable; new chains cannot mix with legacy resolution fields."""
    if not candidate.redirect_chain:
        return initial
    if candidate.redirect_witness is not None or candidate.publisher_cdn_witness is not None:
        raise ArchivalError("do not mix legacy witness fields and the explicit bounded chain")
    current, _ = _replay(root, candidate, initial)
    return current


def resolve_chain_step(
    root: Path, candidate: ArchivalCandidate, response_sha256: str
) -> ArchivalCandidate:
    """Append at most six independently observed allowed relations; never generate a target."""
    if (
        len(candidate.redirect_chain) >= 6
        or candidate.redirect_witness is not None
        or candidate.publisher_cdn_witness is not None
    ):
        raise ArchivalError("explicit archive chain exceeds six hops or mixes legacy witnesses")
    current, seen = _replay(root, candidate, candidate.pdf_url)
    target = _observed_target(root, current, response_sha256)
    if target in seen:
        raise ArchivalError("observed archive redirect chain would loop")
    hop = ObservedHop(
        candidate_basis_sha256=candidate_sha256(candidate),
        response_sha256=response_sha256,
        request_url_sha256=_hash(current),
        target_url_sha256=_hash(target),
        public_target_url=public_locator(target),
        relation=_relation(current, target, candidate, response_sha256),
    )
    return candidate.model_copy(update={"redirect_chain": (*candidate.redirect_chain, hop)})
