"""Independent historical assertions, conservative matches and explicit unknown coverage."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self, override
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,180}$")]
MatchStatus = Literal[
    "reviewed-match", "title-period-candidate", "listed-unmatched", "ambiguous", "date-conflict"
]


class HoldingsError(ValueError):
    """A historical input cannot support the requested evidence-bound observation."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Keep ordinary mutable exception traceback semantics."""
        self.reason = reason
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        return self.reason


class HoldingsRecord(BaseModel):
    """Strict immutable boundary for retained research data."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


def source_url(value: str) -> str:
    """Describe an observed locator; this does not authorize a network request."""
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or len(value) > 4000
    ):
        raise HoldingsError("source locator must be an ordinary observed HTTP(S) URL")
    return value


class CaptureFile(HoldingsRecord):
    """Hash of retained tool text, explicitly distinct from original HTTP response bytes."""

    path: Annotated[
        str, Field(pattern=r"^data/source-observations/web-tool/[a-z0-9._-]+\.(txt|json)$")
    ]
    sha256: Digest


class SourceObservation(HoldingsRecord):
    """An archived publisher representation observed through the web tool."""

    source_id: Identifier
    original_url: str
    capture_url: str
    observed_at: AwareDatetime
    representation: Literal["web-tool-extracted-text"] = "web-tool-extracted-text"
    captures: tuple[CaptureFile, ...] = Field(min_length=1, max_length=12)
    total_tool_lines: int = Field(ge=1, le=10000)
    complete_tool_line_capture: Literal[True] = True
    publication_census_complete: Literal[False] = False
    format: Literal["online-back-issues", "stsc-back-issues", "online-current", "article-index"]

    @field_validator("original_url", "capture_url")
    @classmethod
    def locators(cls, value: str) -> str:
        """Retain ordinary observed locators without granting network permission."""
        return source_url(value)


class IssuePeriod(HoldingsRecord):
    """An explicit source label; a period is neither a guessed schedule nor an issue ID."""

    year: int = Field(ge=1980, le=2100)
    months: tuple[int, ...] = Field(max_length=12)
    kind: Literal["dated", "special"] = "dated"

    @model_validator(mode="after")
    def period(self) -> Self:
        """Combined labels retain their actual months without generating intervening issues."""
        if len(set(self.months)) != len(self.months) or any(
            month < 1 or month > 12 for month in self.months
        ):
            raise HoldingsError("issue period has repeated or invalid months")
        if (self.kind == "dated") != bool(self.months):
            raise HoldingsError("dated periods require months; special labels retain no month")
        return self


class IssueAssertion(HoldingsRecord):
    """One explicitly listed issue, independent of Calhoun identity or successful acquisition."""

    assertion_id: Identifier
    source_id: Identifier
    source_lines: tuple[int, ...] = Field(min_length=1, max_length=12)
    raw_label: str = Field(min_length=1, max_length=250)
    period: IssuePeriod
    evidence_kind: Literal["issue-listing", "current-issue"]
    theme: str | None = Field(default=None, max_length=500)
    web_tool_link_id: int | None = Field(default=None, ge=0)
    observed_pdf_url: str | None = None

    @field_validator("observed_pdf_url")
    @classmethod
    def pdf_locator(cls, value: str | None) -> str | None:
        """Missing link targets remain missing instead of being inferred from filenames."""
        return None if value is None else source_url(value)


class ArticleIndexEntry(HoldingsRecord):
    """A publisher-listed entry, potentially a column or notice, without inferred article bounds."""

    entry_id: Identifier
    source_id: Identifier
    source_url: str
    source_lines: tuple[int, ...] = Field(min_length=1, max_length=12)
    raw_lines: tuple[str, ...] = Field(min_length=1, max_length=12)
    category: str
    title: str
    byline: str
    issued_label: str
    period: IssuePeriod | None
    printed_page: str | None = None
    genre: None = None
    web_tool_link_id: int = Field(ge=0)
    boundary_status: Literal["publisher-listed-entry-unreviewed"] = (
        "publisher-listed-entry-unreviewed"
    )

    @field_validator("source_url")
    @classmethod
    def locator(cls, value: str) -> str:
        """Keep the exact attributed source page locator."""
        return source_url(value)


class CatalogObservation(HoldingsRecord):
    """Minimal dated catalog projection; original catalog values remain unchanged."""

    issue_id: str
    title: str
    issued_metadata: str | None
    landing_url: str


class HoldingsDecision(HoldingsRecord):
    """An explicit identity decision bound to both exact records, never a fuzzy title merge."""

    assertion_id: Identifier
    catalog_issue_id: str
    assertion_sha256: Digest
    catalog_row_sha256: Digest
    relation: Literal["same-issue", "different-issue"]
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=3000)
    evidence_receipts: tuple[InputBinding, ...] = Field(min_length=1, max_length=10)
    review_mode: Literal["AI-assisted-native-text"] = "AI-assisted-native-text"


class HoldingsMatch(HoldingsRecord):
    """One assertion's present relation to a captured catalog, with uncertainty retained."""

    assertion_id: Identifier
    year: int
    status: MatchStatus
    candidate_issue_ids: tuple[str, ...]
    reviewed_issue_ids: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


class YearCoverage(HoldingsRecord):
    """Counts of evidence observations, not a monthly expected-issues denominator."""

    year: int
    assertion_observations: int
    distinct_period_candidates: int
    reviewed_matches: int
    title_period_candidates: int
    listed_unmatched: int
    ambiguous: int
    date_conflicts: int
    catalog_only_unreconciled: int
    independent_listing_coverage: Literal["observed", "unknown"]


class HoldingsRun(HoldingsRecord):
    """A bounded reconciliation whose unknown historical denominator remains explicit."""

    assertions: tuple[IssueAssertion, ...]
    matches: tuple[HoldingsMatch, ...]
    catalog_only: tuple[CatalogObservation, ...]
    years: tuple[YearCoverage, ...]
    source_bindings: tuple[CaptureFile, ...] = ()
    catalog_sha256: Digest | None = None
    input_bindings: tuple[InputBinding, ...] = ()
    archive_complete: Literal[False] = False
    expected_historical_issue_total: None = None


class HoldingsPublication(HoldingsRecord):
    """Immutable report bundle and method/input identities for one finite reconciliation."""

    directory: str
    run_sha256: Digest
    implementation_sha256: Digest
    artifacts: tuple[InputBinding, ...]


class InputBinding(HoldingsRecord):
    """Exact local metadata input; the reader independently confines the physical path."""

    path: str
    sha256: Digest


class HoldingsInputs(HoldingsRecord):
    """One explicit study boundary and all inputs of a pure reconciliation."""

    assertions: tuple[IssueAssertion, ...]
    catalog: tuple[CatalogObservation, ...]
    decisions: tuple[HoldingsDecision, ...] = ()
    sources: tuple[SourceObservation, ...] = ()
    article_entries: tuple[ArticleIndexEntry, ...] = ()
    bindings: tuple[InputBinding, ...] = ()
    first_year: int = Field(default=1988, ge=1980, le=2100)
    last_year: int = Field(default=2026, ge=1980, le=2100)

    @model_validator(mode="after")
    def boundary(self) -> Self:
        """Display years declare the study boundary rather than an assumed issue schedule."""
        if self.first_year > self.last_year:
            raise HoldingsError("study boundary is reversed")
        return self
