"""Typed official linkset evidence and non-destructive locator admission outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crosstalk.models import Digest  # noqa: TC001 - Pydantic resolves this runtime annotation.


class LocatorRecord(BaseModel):
    """Immutable input/output contracts; no extra executable or transport fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")


class ResponseHeader(LocatorRecord):
    """Small non-secret response metadata set; cookies and authentication are excluded."""

    name: Literal["content-type", "etag", "last-modified", "server", "link", "dspace-version"]
    value: str = Field(max_length=8192)


class SignpostingSnapshot(LocatorRecord):
    """One item-specific HTTP observation; exact body bytes are retained separately."""

    request_url: str = Field(max_length=4096)
    observed_at: str
    status_code: int = Field(ge=100, le=599)
    content_type: str = Field(max_length=256)
    body_path: str = Field(pattern=r"^data/raw/metadata/signposting/[0-9a-f]{64}\.json$")
    body_sha256: Digest
    catalog_sha256: Digest
    robots_sha256: Digest
    final_url: str | None = None
    http_version: str | None = None
    response_headers: tuple[ResponseHeader, ...] = Field(default=(), max_length=16)

    @field_validator("observed_at")
    @classmethod
    def timestamp_has_timezone(cls, value: str) -> str:
        """A retry timestamp must be a comparable instant rather than local wall time."""
        if datetime.fromisoformat(value).tzinfo is None:
            message = "locator observation timestamp requires a timezone"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def content_addressed_body(self) -> SignpostingSnapshot:
        """The declared retained path and exact body digest must identify one object."""
        if self.body_path != f"data/raw/metadata/signposting/{self.body_sha256}.json":
            message = "linkset body path disagrees with its content digest"
            raise ValueError(message)
        return self


class LinkTarget(BaseModel):
    """Parse the RFC linkset target fields needed for typed PDF discrimination."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    href: str = Field(max_length=4096)
    media_type: str | None = Field(default=None, alias="type")


class LinkContext(BaseModel):
    """A response may also contain bitstream and metadata anchors without item links."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    anchor: str = Field(max_length=4096)
    items: tuple[LinkTarget, ...] = Field(default=(), alias="item", max_length=100)
    cite_as: tuple[LinkTarget, ...] = Field(default=(), alias="cite-as", max_length=20)
    licenses: tuple[LinkTarget, ...] = Field(default=(), alias="license", max_length=20)


class LinksetDocument(BaseModel):
    """A bounded JSON linkset, not an issue-title/date metadata response."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    linkset: tuple[LinkContext, ...] = Field(min_length=1, max_length=100)


class LocatorObservation(LocatorRecord):
    """Normalized evidence; a resolved locator does not certify a downloaded PDF."""

    snapshot_sha256: Digest
    body_sha256: Digest
    catalog_sha256: Digest
    robots_sha256: Digest
    observed_at: str
    request_url: str
    item_id: str
    issue_id: str | None
    status: Literal[
        "resolved",
        "no-pdf",
        "ambiguous-pdf",
        "invalid-response",
        "outside-catalog",
        "manifest-conflict",
    ]
    pdf_url: str | None = None
    published_pdf_url: str | None = None
    cite_as: tuple[str, ...] = ()
    license_links: tuple[str, ...] = ()
    reason: str | None = None


class LocatorImportResult(LocatorRecord):
    """Current import effects are separate from the retained discovery observation."""

    observation: LocatorObservation
    added: bool
    manifest_sha256: Digest | None


class DiscoveryTarget(LocatorRecord):
    """An unresolved current-catalog member selected for a bounded future observation."""

    issue_id: str
    item_id: str
    landing_url: str
    request_url: str
    catalog_sha256: Digest
    last_observed_at: str | None
