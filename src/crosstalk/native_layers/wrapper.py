"""Conservative versioned Calhoun wrapper observations, with no text mutation."""

from __future__ import annotations

import hashlib
import re
from typing import Final, Literal

from crosstalk.native_layers.records import (
    LineHash,
    NativeIdentity,
    NativePage,
    Predicate,
    WrapperObservation,
)

LABELS: Final = (
    "Title",
    "Item Type",
    "Citation",
    "URI",
    "Publisher",
    "Date Issued",
    "Rights",
    "Download date",
    "Link to Item",
)
FOOTER: Final = "Downloaded from NPS Archive: Calhoun"
HANDLE: Final = re.compile(r"https://hdl\.handle\.net/10945/[0-9]+")


def _field(lines: tuple[str, ...], label: str) -> tuple[str | None, tuple[int, ...]]:
    """Take one unambiguous standalone label and its immediate next nonblank value."""
    indexes = tuple(index for index, line in enumerate(lines) if line == label)
    if len(indexes) != 1:
        return None, indexes
    following = tuple(
        (index, line) for index, line in enumerate(lines) if index > indexes[0] and line
    )
    if not following or following[0][1] in LABELS:
        return None, indexes
    return following[0][1], (indexes[0], following[0][0])


def observe_wrapper(native: NativePage, identity: NativeIdentity) -> WrapperObservation:
    """Match a complete first-page signature only with independently bound expected identity."""
    page = native.page
    original_lines = tuple(page.text.splitlines(keepends=True))
    lines = tuple(line.strip() for line in original_lines)
    locations = tuple(
        tuple(index for index, line in enumerate(lines) if line == label) for label in LABELS
    )
    label_predicates = tuple(
        Predicate(name=f"standalone-label:{label}", passed=len(indexes) == 1, line_indexes=indexes)
        for label, indexes in zip(LABELS, locations, strict=True)
    )
    ordered = all(len(indexes) == 1 for indexes in locations) and (
        tuple(indexes[0] for indexes in locations)
        == tuple(sorted(indexes[0] for indexes in locations))
    )
    title, title_indexes = _field(lines, "Title")
    uri, uri_indexes = _field(lines, "URI")
    link, link_indexes = _field(lines, "Link to Item")
    item_type, item_indexes = _field(lines, "Item Type")
    footer_indexes = tuple(index for index, line in enumerate(lines) if line == FOOTER)
    nonempty = tuple((index, line) for index, line in enumerate(lines) if line)
    repeated = bool(uri is not None and uri == link and HANDLE.fullmatch(uri))
    evidence = identity.handle_evidence
    independent = evidence is not None and (
        evidence.publication_url == identity.landing_url
        and evidence.catalog_sha256 == identity.catalog_sha256
        and (
            (
                identity.source_kind == "journal"
                and evidence.provenance == "retained-exact-publication-signposting"
            )
            or (
                identity.source_kind == "software-fixture"
                and evidence.provenance == "software-fixture"
            )
        )
    )
    handle_matches = (
        independent and repeated and evidence is not None and evidence.handle_url == uri
    )
    handle_conflict = (
        independent
        and evidence is not None
        and any(value is not None and value != evidence.handle_url for value in (uri, link))
    )
    handle_status: Literal[
        "independent-match",
        "independent-conflict",
        "observed-repeated-only",
        "missing-or-inconsistent",
    ] = (
        "independent-match"
        if handle_matches
        else "independent-conflict"
        if handle_conflict
        else "observed-repeated-only"
        if repeated
        else "missing-or-inconsistent"
    )
    predicates = (
        Predicate(name="first-physical-page", passed=page.page_index == 0),
        *label_predicates,
        Predicate(name="ordered-unique-labels", passed=ordered),
        Predicate(
            name="exact-terminal-calhoun-footer",
            passed=len(footer_indexes) == 1 and bool(nonempty) and nonempty[-1][1] == FOOTER,
            line_indexes=footer_indexes,
        ),
        Predicate(
            name="catalog-title-field", passed=title == identity.title, line_indexes=title_indexes
        ),
        Predicate(
            name="catalog-title-heading",
            passed=bool(nonempty) and nonempty[0][1] == identity.title,
            line_indexes=(nonempty[0][0],) if nonempty else (),
        ),
        Predicate(
            name="journal-item-type", passed=item_type == "Journal", line_indexes=item_indexes
        ),
        Predicate(
            name="same-observed-canonical-handle",
            passed=repeated,
            line_indexes=(*uri_indexes, *link_indexes),
        ),
        Predicate(name="independent-retained-handle", passed=handle_matches),
    )
    matched = all(predicate.passed for predicate in predicates)
    candidate = bool(footer_indexes) or sum(bool(indexes) for indexes in locations) >= 3
    flags = (
        tuple(predicate.name for predicate in predicates if not predicate.passed)
        if candidate
        else ()
    )
    return WrapperObservation(
        page_index=page.page_index,
        record_line_sha256=native.record_line_sha256,
        native_text_sha256=hashlib.sha256(page.text.encode()).hexdigest(),
        line_hashes=tuple(
            LineHash(line_index=index, sha256=hashlib.sha256(line.encode()).hexdigest())
            for index, line in enumerate(original_lines)
        ),
        status="matched-wrapper"
        if matched
        else "candidate-review"
        if candidate
        else "no-signature",
        observed_title=title,
        observed_uri=uri,
        observed_link_to_item=link,
        handle_status=handle_status,
        predicates=predicates,
        review_flags=flags,
    )
