"""Concrete acquisition source families without inventing NPS series membership."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crosstalk.models import AcquisitionError, Digest, Issue
from crosstalk.publisher_records import (
    PUBLISHER_PAGE,
    PublisherDateClaim,
    require_publisher_pdf,
)

type SourceFamily = Literal["nps-calhoun", "afsc-publisher"]


class PublisherDownloadSource(BaseModel):
    """One observed public candidate, not an NPS Issue or a verified printed-date claim."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    source_snapshot_sha256: Digest
    issue_id: Annotated[str, Field(pattern=r"^ct-afsc-[a-z0-9][a-z0-9-]{0,99}$")]
    card_key: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    landing_url: Literal["https://afscsoftware.dso.mil/crosstalk/"] = PUBLISHER_PAGE
    pdf_url: str
    date_claims: Annotated[tuple[PublisherDateClaim, ...], Field(max_length=20)] = ()
    kind: Literal["issue-candidate"] = "issue-candidate"
    printed_date: None = None
    sha256: Digest | None = None

    @field_validator("pdf_url")
    @classmethod
    def publisher_url(cls, value: str) -> str:
        """Keep the exact publisher host and observed PDF path at the source boundary."""
        return require_publisher_pdf(value)

    @model_validator(mode="after")
    def candidate_identity(self) -> PublisherDownloadSource:
        """A local candidate key cannot silently become a separate issue identity."""
        if self.issue_id != f"ct-afsc-{self.card_key}":
            raise AcquisitionError("publisher source ID disagrees with its captured card key")
        return self


type DownloadSource = Issue | PublisherDownloadSource


class PublisherAcquisitionIdentity(BaseModel):
    """Stable acquisition identity; capture changes are retained in attempt observations."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    issue_id: str
    card_key: str
    pdf_url: str
    sha256: Digest | None


def publisher_acquisition_identity(source: PublisherDownloadSource) -> str:
    """Unrelated card/title/date edits cannot discard verified bytes or retry history."""
    return PublisherAcquisitionIdentity(
        issue_id=source.issue_id,
        card_key=source.card_key,
        pdf_url=source.pdf_url,
        sha256=source.sha256,
    ).model_dump_json()


def source_family(source: DownloadSource) -> SourceFamily:
    """The concrete parsed model selects a family; no caller-supplied validator is accepted."""
    match source:
        case Issue():
            return "nps-calhoun"
        case PublisherDownloadSource():
            return "afsc-publisher"
        case _:
            assert_never(source)


def source_snapshot(source: DownloadSource) -> str | None:
    """NPS retains its original typed inventory identity; publisher sources bind their capture."""
    match source:
        case Issue():
            return None
        case PublisherDownloadSource():
            return source.source_snapshot_sha256
        case _:
            assert_never(source)


def publisher_pin(source: DownloadSource) -> str | None:
    """Retain optional publisher pinning while preserving NPS event semantics."""
    match source:
        case Issue():
            return None
        case PublisherDownloadSource():
            return source.sha256
        case _:
            assert_never(source)
