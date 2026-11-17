"""Separate archive-family observations; these never assert NPS collection membership."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, ClassVar, Literal, override
from urllib.parse import parse_qsl, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ARCHIVE_PATH = re.compile(
    r"^/web/[0-9]{14}/http://www\.crosstalkonline\.org(?::80)?/"
    + r"(?:back-issues/|storage/issue-archives/[0-9]{4}/[0-9]{6}/[^/?#]+\.pdf)$"
)
CDN_PATH = re.compile(
    r"^/web/[0-9]{14}/http://static1\.1\.sqspcdn\.com/static/f/702523/"
    + r"[0-9]+/[0-9]+/[0-9]{6}-0-Issue\.pdf$"
)


class ArchivalError(ValueError):
    """A typed archive policy, source or publication refusal."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Keep normal mutable traceback semantics."""
        self.reason = reason
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        return self.reason


def archive_url(value: str, *, robots: bool = False) -> str:
    """Admit only the reviewed archival source family, never a general proxy or NPS bypass."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "web.archive.org"
        or parsed.query
        or parsed.fragment
        or not (parsed.path == "/robots.txt" if robots else ARCHIVE_PATH.fullmatch(parsed.path))
    ):
        raise ArchivalError("URL is outside the explicitly reviewed archival source family")
    return value


def archive_fetch_url(value: str) -> str:
    """Admit the reviewed archived CDN family; never a live CDN request or arbitrary query."""
    parsed = urlsplit(value)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme == "https"
        and parsed.netloc == "web.archive.org"
        and not parsed.fragment
        and CDN_PATH.fullmatch(parsed.path)
        and (not query or (len(query) == 1 and query[0][0] == "token" and bool(query[0][1])))
        and len(value) <= 8000
    ):
        return value
    return archive_url(value)


class ArchivalRecord(BaseModel):
    """Strict immutable persistence boundary for independent archival evidence."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class ResponseHeader(ArchivalRecord):
    """A small noncredential response-header projection."""

    name: Literal["content-type", "location", "etag", "last-modified", "date", "server"]
    value: str = Field(max_length=8000)


class ArchivalResponse(ArchivalRecord):
    """Exact bytes/status independently observed by the finite HTTP client."""

    request_url: str
    observed_at: AwareDatetime
    status_code: int | None = None
    headers: tuple[ResponseHeader, ...] = ()
    body_sha256: Digest
    byte_count: int = Field(ge=0, le=50_000_000)
    complete: bool
    error: str | None = None


class RedirectWitness(ArchivalRecord):
    """One actual response bound to the original candidate and its exact same-resource Location."""

    source_candidate_sha256: Digest
    response_sha256: Digest
    target_url: str
    rule: Literal["one-hop-same-decoded-original-resource"] = (
        "one-hop-same-decoded-original-resource"
    )

    @field_validator("target_url")
    @classmethod
    def target(cls, value: str) -> str:
        """A reviewed Location still cannot widen the source family."""
        return archive_url(value)


class PublisherCdnWitness(ArchivalRecord):
    """An explicitly observed publisher-to-CDN relation; a private query stays in its receipt."""

    resolved_candidate_sha256: Digest
    response_sha256: Digest
    target_url_sha256: Digest
    public_target_url: str
    rule: Literal["observed-publisher-to-known-archived-cdn"] = (
        "observed-publisher-to-known-archived-cdn"
    )


class ObservedHop(ArchivalRecord):
    """One actual response and exact Location, bound to an immutable original candidate basis."""

    candidate_basis_sha256: Digest
    response_sha256: Digest
    request_url_sha256: Digest
    target_url_sha256: Digest
    public_target_url: str
    relation: Literal[
        "replay-retiming",
        "publisher-to-reviewed-cdn",
        "reviewed-may-2001-spelling",
        "reviewed-january-2006-spelling",
    ]


class ArchivalCandidate(ArchivalRecord):
    """An actual retained HTML anchor tied to one independent issue assertion."""

    assertion_id: str = Field(pattern=r"^[a-z0-9._-]{1,181}$")
    label: str = Field(min_length=1, max_length=250)
    year: int = Field(ge=1980, le=2100)
    month: int = Field(ge=1, le=12)
    source_url: str
    source_body_sha256: Digest
    source_response_sha256: Digest
    source_assertion_sha256: Digest
    href: str = Field(min_length=1, max_length=4000)
    pdf_url: str
    redirect_witness: RedirectWitness | None = None
    publisher_cdn_witness: PublisherCdnWitness | None = None
    redirect_chain: tuple[ObservedHop, ...] = Field(default=(), max_length=6)

    @field_validator("source_url", "pdf_url")
    @classmethod
    def locators(cls, value: str) -> str:
        """Refuse cross-family locators at the public boundary."""
        return archive_url(value)


def candidate_key(candidate: ArchivalCandidate) -> str:
    """Bind one source assertion and its observed initial locator independently of retiming."""
    raw = f"{candidate.assertion_id}\x00{candidate.source_assertion_sha256}\x00{candidate.pdf_url}"
    return hashlib.sha256(raw.encode()).hexdigest()


class PdfPeriodWitness(ArchivalRecord):
    """Native date strings are review evidence, never automated publication identity."""

    page_index: int = Field(ge=0)
    page_text_sha256: Digest
    matched_text: tuple[str, ...]


class ArchivalInspection(ArchivalRecord):
    """Strong local syntax checks plus explicitly unreviewed issue-identity evidence."""

    pdf_sha256: Digest
    page_count: int = Field(ge=1, le=500)
    native_period_witnesses: tuple[PdfPeriodWitness, ...]
    crosstalk_name_seen: bool
    identity_status: Literal["requires-source-review"] = "requires-source-review"


class PreparedPayload(ArchivalRecord):
    """Exact owned payload custody, persisted in a prepared attempt before publication."""

    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    candidate_key: Digest
    pdf_sha256: Digest
    byte_count: int = Field(ge=1, le=50_000_000)
    partial_path: str
    target_path: str

    @model_validator(mode="after")
    def owned_paths(self) -> PreparedPayload:
        """No caller-chosen path can become cleanup authority."""
        expected = f"output/data/archival/partials/{self.attempt_id}-{self.pdf_sha256}.part"
        if self.partial_path != expected or self.target_path != (
            f"output/data/archival/pdfs/{self.pdf_sha256}.pdf"
        ):
            raise ArchivalError("prepared archival payload paths disagree with owned identity")
        return self


class ArchivalAttempt(ArchivalRecord):
    """Append-only publication stages, with prepared digest persisted before PDF publication."""

    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    candidate_key: Digest
    candidate: ArchivalCandidate
    observed_at: AwareDatetime
    stage: Literal["prepared", "published", "reused", "failed"]
    pdf_sha256: Digest | None = None
    inspection: ArchivalInspection | None = None
    publication: PreparedPayload | None = None
    error: str | None = None
    source_family: Literal["wayback-original-publisher"] = "wayback-original-publisher"
    merged_into_corpus: Literal[False] = False

    @model_validator(mode="after")
    def prepared_identity(self) -> ArchivalAttempt:
        """Legacy records remain readable; new owned custody must agree with the full attempt."""
        bound = self.publication
        if self.candidate_key != candidate_key(self.candidate):
            raise ArchivalError("archival attempt key disagrees with its exact source candidate")
        if bound is not None and (
            bound.attempt_id != self.attempt_id
            or bound.candidate_key != self.candidate_key
            or bound.pdf_sha256 != self.pdf_sha256
            or self.inspection is None
            or self.inspection.pdf_sha256 != bound.pdf_sha256
            or self.stage == "failed"
        ):
            raise ArchivalError("prepared archival payload disagrees with attempt provenance")
        return self
