"""Initialism-expansion observations retain local contexts and possible sense ambiguity."""

from __future__ import annotations

import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import Field

from crosstalk.article_records import (
    ArticleError,
    ArticlePage,
    ArticleRecord,
    Passage,
    text_digest,
    witness,
)

_SHORT = re.compile(r"\(([A-Z][A-Z0-9]{1,9})\)")
_WORD = re.compile(r"[A-Za-z]+")
_STOP = frozenset({"and", "of", "the", "for", "to"})


class Initialism(ArticleRecord):
    """An initial-letter-aligned candidate, never an automatically validated semantic sense."""

    abbreviation: str
    long_form_observed: str
    normalized_long_form: str
    match_rule: str
    source: Passage


class ExpansionVariants(ArticleRecord):
    """Distinct observed spellings may be synonyms, errors or different senses."""

    abbreviation: str
    layer: str
    normalized_forms: tuple[str, ...]
    observations: int = Field(ge=1)
    source_issues: int = Field(ge=1)
    physical_pages: int = Field(ge=1)


class InitialismRun(ArticleRecord):
    """Layer-separated source witnesses and matching rules, with no semantic accuracy claim."""

    input_sha256: str
    implementation_sha256: str
    pages: int
    observations: tuple[Initialism, ...]
    variants: tuple[ExpansionVariants, ...]
    scope: str = (
        "ASCII uppercase parenthetical initialisms of 2-10 characters; preceding 240 characters, "
        + "up to 14 alphabetic words, exact initials or declared stopword omission. Hyphens split "
        + "words. Mixed-case abbreviations, inverted definitions and implicit senses "
        + "are outside scope. "
        + "Reading order and semantic precision/recall remain unvalidated."
    )


def _expansion(text: str, start: int, abbreviation: str) -> tuple[int, str] | None:
    """Find the shortest source-word suffix with matching initials, without rewriting source."""
    offset = max(0, start - 240)
    prefix = text[offset:start]
    boundary = max((prefix.rfind(mark) for mark in ".!?;:"), default=-1)
    offset += boundary + 1
    prefix = prefix[boundary + 1 :]
    words = tuple(_WORD.finditer(prefix))[-14:]
    for count in range(2, len(words) + 1):
        selected = words[-count:]
        initials = "".join(word.group()[0].upper() for word in selected)
        if initials == abbreviation:
            return offset + selected[0].start(), "exact-initial-letters"
        significant = tuple(word for word in selected if word.group().casefold() not in _STOP)
        reduced = "".join(word.group()[0].upper() for word in significant)
        if significant and reduced == abbreviation and selected[0] == significant[0]:
            return offset + selected[0].start(), "declared-stopword-initial-omission"
    return None


def initialisms(pages: tuple[ArticlePage, ...]) -> InitialismRun:
    """Measure exact source candidates; duplicate layers/pages and aliased PDFs refuse."""
    identities = {(p.issue_id, p.page_index, p.layer) for p in pages}
    if len(identities) != len(pages) or len(pages) > 30_000:
        raise ArticleError("initialism input repeats source pages or exceeds page capacity")
    issue_sources: dict[str, str] = {}
    pdf_issues: dict[str, str] = {}
    source_digest = hashlib.sha256()
    observations: list[Initialism] = []
    for page in pages:
        if (
            issue_sources.setdefault(page.issue_id, page.pdf_sha256) != page.pdf_sha256
            or pdf_issues.setdefault(page.pdf_sha256, page.issue_id) != page.issue_id
        ):
            raise ArticleError("initialism source aliases require explicit reconciliation")
        binding = (
            page.issue_id,
            page.pdf_sha256,
            page.page_index,
            page.layer,
            page.artifact_path,
            page.artifact_sha256,
            text_digest(page.text),
        )
        source_digest.update(repr(binding).encode() + b"\0")
        for short in _SHORT.finditer(page.text):
            abbreviation = short[1]
            found = _expansion(page.text, short.start(), abbreviation)
            if found is None:
                continue
            start, rule = found
            long = page.text[start : short.start()].rstrip()
            observations.append(
                Initialism(
                    abbreviation=abbreviation,
                    long_form_observed=long,
                    normalized_long_form=" ".join(
                        word.group().casefold() for word in _WORD.finditer(long)
                    ),
                    match_rule=rule,
                    source=witness(page, start, short.end()),
                )
            )
            if len(observations) > 100_000:
                raise ArticleError("initialism observation capacity exhausted")
    grouped: dict[tuple[str, str], list[Initialism]] = defaultdict(list)
    for row in observations:
        grouped[(row.source.layer, row.abbreviation)].append(row)
    variants = tuple(
        ExpansionVariants(
            abbreviation=short,
            layer=layer,
            normalized_forms=tuple(sorted({r.normalized_long_form for r in rows})),
            observations=len(rows),
            source_issues=len({r.source.issue_id for r in rows}),
            physical_pages=len({(r.source.issue_id, r.source.page_index) for r in rows}),
        )
        for (layer, short), rows in sorted(grouped.items())
    )
    directory = Path(__file__).parent
    closure = (
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest())
        for name in ("article_abbreviations.py", "article_records.py")
    )
    method = text_digest(repr((tuple(closure), sys.version)))
    return InitialismRun(
        input_sha256=source_digest.hexdigest(),
        implementation_sha256=method,
        pages=len(pages),
        observations=tuple(observations),
        variants=variants,
    )
