"""A separate official publisher discovery frame, without invented Calhoun membership."""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TC003 -- Pydantic resolves model fields at runtime.
from typing import Annotated, ClassVar, Final, Literal, Self, assert_never
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crosstalk.models import AcquisitionError, Digest

PUBLISHER_PAGE: Final = "https://afscsoftware.dso.mil/crosstalk/"
PDF_PATH: Final = re.compile(r"/crossTalkIssues/[A-Za-z0-9_.-]+\.pdf")
BIBLIOGRAPHY_PAGE: Final = (
    "https://www.sei.cmu.edu/annual-reviews/2025-year-in-review/"
    + "key-publications-and-conference-presentations/"
)


def require_publisher_pdf(value: str) -> str:
    """Admit observed official PDF paths, refusing credentials, queries and aliases."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "afscsoftware.dso.mil"
        or PDF_PATH.fullmatch(parsed.path) is None
        or parsed.query
        or parsed.fragment
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise AcquisitionError("publisher PDF must be an exact official public issue URL")
    return value


class PublisherDateClaim(BaseModel):
    """A verbatim date label with its provenance; never silently a printed publication date."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    origin: Literal["card-label", "filename-label", "bibliography-label"]
    value: Annotated[str, Field(min_length=1, max_length=200)]
    evidence_url: str

    @model_validator(mode="after")
    def primary_evidence(self) -> Self:
        """Require the evidence URL appropriate to the declared kind of observation."""
        match self.origin:
            case "card-label":
                valid = self.evidence_url == PUBLISHER_PAGE
            case "bibliography-label":
                valid = self.evidence_url == BIBLIOGRAPHY_PAGE
            case "filename-label":
                valid = require_publisher_pdf(self.evidence_url) == self.evidence_url
            case _:
                assert_never(self.origin)
        if not valid:
            raise AcquisitionError("publisher date claim does not match its evidence kind")
        return self


class PublisherCard(BaseModel):
    """A stable local card key identifies an observation, not a reconciled historical issue."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    card_key: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    date_claims: Annotated[tuple[PublisherDateClaim, ...], Field(max_length=20)] = ()


class PublicPublisherCard(PublisherCard):
    """An observed public locator; issue identity and printed date still need PDF review."""

    access: Literal["public-pdf"]
    pdf_url: str

    @field_validator("pdf_url")
    @classmethod
    def official_pdf(cls, value: str) -> str:
        """Parse the source host/path at the discovery boundary."""
        return require_publisher_pdf(value)


class ContactPublisherCard(PublisherCard):
    """A displayed contact-only card; no guessed download URL or contact action."""

    access: Literal["contact-only"]


PublisherEntry = Annotated[
    PublicPublisherCard | ContactPublisherCard, Field(discriminator="access")
]


class PublisherSnapshot(BaseModel):
    """A dated public rendered-page capture; not a publisher holdings census."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    source: Literal["https://afscsoftware.dso.mil/crosstalk/"]
    observed_at: datetime
    method: Literal["public-rendered-page-metadata"]
    records: Annotated[tuple[PublisherEntry, ...], Field(min_length=1, max_length=2000)]

    @field_validator("observed_at")
    @classmethod
    def aware_observation(cls, value: datetime) -> datetime:
        """Require an explicit timezone rather than inventing one."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise AcquisitionError("publisher observation must include its timezone")
        return value


class PublisherCatalogRow(BaseModel):
    """One provenance-linked candidate in the separate publisher frame."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    record_id: str
    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    kind: Literal["issue-candidate"] = "issue-candidate"
    source_snapshot_sha256: Digest
    candidate: PublisherEntry
    printed_date: None = None
    pdf_verified: Literal[False] = False


class PublisherCatalogSummary(BaseModel):
    """Selected discovery accounting, without changing the NPS capture denominator."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    source_family: Literal["afsc-publisher"] = "afsc-publisher"
    snapshot_sha256: Digest
    catalog_sha256: Digest
    implementation_sha256: Digest
    observed_at: datetime
    records: int = Field(ge=0)
    public_pdf_locators: int = Field(ge=0)
    contact_only: int = Field(ge=0)
    expected_historical_total: None = None
    archive_complete: Literal[False] = False
