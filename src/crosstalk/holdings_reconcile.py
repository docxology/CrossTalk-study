"""Match only explicit period labels; identity requires separately bound review decisions."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import TYPE_CHECKING, Final, assert_never

from crosstalk.holdings_records import (
    HoldingsError,
    HoldingsInputs,
    HoldingsMatch,
    HoldingsRun,
    IssuePeriod,
    YearCoverage,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from crosstalk.holdings_records import (
        CatalogObservation,
        HoldingsDecision,
        IssueAssertion,
        MatchStatus,
    )

MONTHS: Final = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
ALIASES: Final = {
    alias: index
    for index, month in enumerate(MONTHS, 1)
    for alias in (month, month[:3], "sept" if month == "september" else month)
}


def parse_issue_period(label: str) -> IssuePeriod | None:
    """Read listed months, including combined labels, without constructing a monthly grid."""
    cleaned = re.sub(r"(?i)^crosstalk\s*/?\s*", "", label.strip())
    found = re.fullmatch(r"(.+?)\s*(19\d{2}|20\d{2})", cleaned)
    if found is None:
        return None
    prefix, year = found.groups()
    prefix = prefix.strip().casefold()
    if prefix in {"special edition", "special issue"}:
        return IssuePeriod(year=int(year), months=(), kind="special")
    if prefix == "n/d":
        return IssuePeriod(year=int(year), months=(11, 12))
    words = tuple(word for word in re.split(r"[\s/\-\u2013\u2014]+", prefix) if word)
    if not words or any(word not in ALIASES for word in words):
        return None
    return IssuePeriod(year=int(year), months=tuple(sorted(ALIASES[word] for word in words)))


def record_sha256(record: BaseModel) -> str:
    """Seal the complete typed projection used by an explicit identity decision."""
    return hashlib.sha256(record.model_dump_json().encode()).hexdigest()


def _key(period: IssuePeriod | None) -> tuple[int, str, tuple[int, ...]] | None:
    return None if period is None else (period.year, period.kind, tuple(sorted(period.months)))


def _require_unique(inputs: HoldingsInputs) -> None:
    identities = (
        tuple(row.assertion_id for row in inputs.assertions),
        tuple(row.issue_id for row in inputs.catalog),
        tuple(row.source_id for row in inputs.sources),
    )
    if any(len(set(values)) != len(values) for values in identities):
        raise HoldingsError("duplicate assertion, catalog or source identity")
    if any(
        row.period.year < inputs.first_year or row.period.year > inputs.last_year
        for row in inputs.assertions
    ):
        raise HoldingsError("assertion lies outside the explicit study boundary")


def _review(assertion: IssueAssertion, inputs: HoldingsInputs) -> tuple[tuple[str, ...], set[str]]:
    rows = {row.issue_id: row for row in inputs.catalog}
    accepted: list[str] = []
    refused: set[str] = set()
    seen: set[str] = set()
    for decision in inputs.decisions:
        if decision.assertion_id != assertion.assertion_id:
            continue
        row = rows.get(decision.catalog_issue_id)
        if row is None or row.issue_id in seen:
            raise HoldingsError("identity decision is duplicated or names an absent catalog row")
        seen.add(row.issue_id)
        _require_decision(decision, assertion, row)
        match decision.relation:
            case "same-issue":
                accepted.append(row.issue_id)
            case "different-issue":
                refused.add(row.issue_id)
            case _:
                assert_never(decision.relation)
    return tuple(sorted(accepted)), refused


def _require_decision(
    decision: HoldingsDecision, assertion: IssueAssertion, row: CatalogObservation
) -> None:
    if decision.assertion_sha256 != record_sha256(
        assertion
    ) or decision.catalog_row_sha256 != record_sha256(row):
        raise HoldingsError(
            "review decision is stale against its exact assertion/catalog projection"
        )


def _metadata_overlap(assertion: IssueAssertion, row: CatalogObservation) -> bool:
    """Propose ambiguous review when an unparsed title has overlapping issued metadata."""
    issued = row.issued_metadata
    if parse_issue_period(row.title) is not None or issued is None:
        return False
    match = re.match(r"^(\d{4})-(\d{2})(?:-\d{2})?$", issued)
    return (
        match is not None
        and int(match[1]) == assertion.period.year
        and int(match[2]) in assertion.period.months
    )


def _match(assertion: IssueAssertion, inputs: HoldingsInputs) -> HoldingsMatch:
    reviewed, refused = _review(assertion, inputs)
    candidates = tuple(
        row
        for row in inputs.catalog
        if (
            _key(parse_issue_period(row.title)) == _key(assertion.period)
            or _metadata_overlap(assertion, row)
        )
        and row.issue_id not in refused
    )
    identifiers = tuple(sorted(row.issue_id for row in candidates))
    conflicts = tuple(
        "metadata-title-year-conflict:" + row.issue_id
        for row in candidates
        if row.issued_metadata is not None and row.issued_metadata[:4] != str(assertion.period.year)
    )
    shared_period = sum(_key(row.period) == _key(assertion.period) for row in inputs.assertions) > 1
    uncertain = tuple(
        "unparsed-title-metadata-overlap:" + row.issue_id
        for row in candidates
        if _metadata_overlap(assertion, row)
    )
    status: MatchStatus
    if len(reviewed) == 1:
        status = "reviewed-match"
    elif len(reviewed) > 1 or len(candidates) > 1 or shared_period or uncertain:
        status = "ambiguous"
    elif conflicts:
        status = "date-conflict"
    elif candidates:
        status = "title-period-candidate"
    else:
        status = "listed-unmatched"
    return HoldingsMatch(
        assertion_id=assertion.assertion_id,
        year=assertion.period.year,
        status=status,
        candidate_issue_ids=identifiers,
        reviewed_issue_ids=reviewed,
        flags=(
            *conflicts,
            *uncertain,
            *(("shared-period-other-assertions",) if shared_period else ()),
        ),
    )


def _catalog_year(row: CatalogObservation) -> int | None:
    period = parse_issue_period(row.title)
    if period is not None:
        return period.year
    issued = row.issued_metadata
    return int(issued[:4]) if issued is not None and re.match(r"^\d{4}", issued) else None


def reconcile_holdings(inputs: HoldingsInputs) -> HoldingsRun:
    """Retain candidate matches and NPS-only rows without claiming historical completeness."""
    _require_unique(inputs)
    assertion_ids = {row.assertion_id for row in inputs.assertions}
    if any(row.assertion_id not in assertion_ids for row in inputs.decisions):
        raise HoldingsError("identity decision names an absent assertion")
    matches = tuple(_match(row, inputs) for row in inputs.assertions)
    associated = {
        identity
        for row in matches
        for identity in (*row.candidate_issue_ids, *row.reviewed_issue_ids)
    }
    catalog_only = tuple(row for row in inputs.catalog if row.issue_id not in associated)
    years: list[YearCoverage] = []
    for year in range(inputs.first_year, inputs.last_year + 1):
        selected = tuple(row for row in matches if row.year == year)
        counts = Counter(row.status for row in selected)
        keys = {_key(row.period) for row in inputs.assertions if row.period.year == year}
        years.append(
            YearCoverage(
                year=year,
                assertion_observations=len(selected),
                distinct_period_candidates=len(keys),
                reviewed_matches=counts["reviewed-match"],
                title_period_candidates=counts["title-period-candidate"],
                listed_unmatched=counts["listed-unmatched"],
                ambiguous=counts["ambiguous"],
                date_conflicts=counts["date-conflict"],
                catalog_only_unreconciled=sum(_catalog_year(row) == year for row in catalog_only),
                independent_listing_coverage="observed" if selected else "unknown",
            )
        )
    return HoldingsRun(
        assertions=inputs.assertions,
        matches=matches,
        catalog_only=catalog_only,
        years=tuple(years),
        source_bindings=tuple(binding for source in inputs.sources for binding in source.captures),
        catalog_sha256=next(
            (row.sha256 for row in inputs.bindings if row.path == "data/manifest/catalog.jsonl"),
            None,
        ),
        input_bindings=inputs.bindings,
    )
