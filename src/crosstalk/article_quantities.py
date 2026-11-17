"""Retrieve exact quantitative forms and local cue words without inventing claim support."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from crosstalk.article_quantities_records import (
    NearbyCue,
    QuantityForm,
    QuantityFormCount,
    QuantityLayerSummary,
    QuantityMention,
    QuantityRun,
    QuantitySettings,
    QuantitySource,
)
from crosstalk.article_quantities_rules import (
    CUES,
    EXPONENT_NOTATION,
    EXPRESSION,
    FORMS,
    GROUPS,
    SCOPE,
)
from crosstalk.article_records import ArticleError, ArticlePage, Passage, text_digest, witness
from crosstalk.article_validation import validate_evidence

if TYPE_CHECKING:
    import re

    from crosstalk.article_quantities_records import CueForm

_METHOD_FILES = (
    "article_quantities.py",
    "article_quantities_records.py",
    "article_quantities_rules.py",
    "article_quantities_validation.py",
    "article_records.py",
    "article_validation.py",
)


def implementation_digest() -> str:
    """Bind the exact small source closure and Python runtime, without touching corpus inputs."""
    rows: list[tuple[str, str]] = []
    for name in _METHOD_FILES:
        path = Path(__file__).absolute().parent / name
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 500_000:
                raise ArticleError("quantitative method source is nonregular, aliased or oversized")
            raw = stream.read(500_001)
            after = os.fstat(stream.fileno())
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(value, key)
            for value in (after, path.lstat())
            for key in fields
        ):
            raise ArticleError("quantitative method source changed during bounded observation")
        rows.append((name, hashlib.sha256(raw).hexdigest()))
    return text_digest(json.dumps((rows, sys.version), separators=(",", ":")))


def _sources(
    pages: tuple[ArticlePage, ...], settings: QuantitySettings
) -> tuple[QuantitySource, ...]:
    if (
        len(pages) > settings.maximum_pages
        or sum(len(page.text) for page in pages) > settings.maximum_characters
    ):
        raise ArticleError("quantitative input exceeds declared page or character capacity")
    _ = validate_evidence(pages, ())
    artifacts: dict[str, str] = {}
    rows: list[QuantitySource] = []
    for page in sorted(pages, key=lambda p: (p.issue_id, p.page_index, p.layer)):
        if artifacts.setdefault(page.artifact_path, page.artifact_sha256) != page.artifact_sha256:
            raise ArticleError("quantitative source frame contains conflicting artifact versions")
        rows.append(
            QuantitySource(
                issue_id=page.issue_id,
                pdf_sha256=page.pdf_sha256,
                page_index=page.page_index,
                page_label=page.page_label,
                layer=page.layer,
                artifact_path=page.artifact_path,
                artifact_sha256=page.artifact_sha256,
                page_text_sha256=text_digest(page.text),
                characters=len(page.text),
                flags=page.flags,
            )
        )
    return tuple(rows)


def _input_digest(sources: tuple[QuantitySource, ...]) -> str:
    return hashlib.sha256(
        b"".join(row.model_dump_json().encode() + b"\n" for row in sources)
    ).hexdigest()


def _form(match: re.Match[str]) -> tuple[QuantityForm, str, str]:
    for name, form in GROUPS:
        if match.group(name) is not None:
            return (
                form,
                match.group(name + "_value"),
                ":" if name == "colon" else match.group(name + "_unit"),
            )
    raise ArticleError("quantitative matcher returned no declared expression form")


def _nearby(page: ArticlePage, context: Passage, maximum: int) -> tuple[tuple[NearbyCue, ...], int]:
    # Retain original string boundaries and one character beyond either clipped
    # edge. Matching a copied substring can turn the suffix of "motif" into "if".
    start, end = max(0, context.start - 1), min(len(page.text), context.end + 1)
    found: list[tuple[int, int, CueForm]] = sorted(
        (
            (match.start(), match.end(), form)
            for form, pattern in CUES
            for match in pattern.finditer(page.text, start, end)
            if context.start <= match.start() and match.end() <= context.end
        ),
        key=lambda row: (row[0], row[1], row[2]),
    )
    return (
        tuple(
            NearbyCue(form=form, source=witness(page, start, end))
            for start, end, form in found[:maximum]
        ),
        max(0, len(found) - maximum),
    )


def _mention_id(source: Passage, form: QuantityForm) -> str:
    return text_digest(
        json.dumps(
            (
                "quantitative-expression-retrieval-1",
                source.pdf_sha256,
                source.page_index,
                source.layer,
                source.artifact_sha256,
                source.page_text_sha256,
                source.start,
                source.end,
                form,
            ),
            separators=(",", ":"),
        )
    )


def _flags(form: QuantityForm) -> tuple[str, ...]:
    return (
        "syntactic-retrieval-candidate-unreviewed",
        "nearby-words-do-not-establish-attachment",
        "denominator-comparison-negation-and-genre-unassessed",
        *(("colon-may-be-time-aspect-or-other-notation",) if form == "colon-form" else ()),
    )


def _page_mentions(page: ArticlePage, settings: QuantitySettings) -> tuple[QuantityMention, ...]:
    excluded: list[tuple[int, int]] = []
    for match in EXPONENT_NOTATION.finditer(page.text):
        if len(excluded) >= settings.maximum_expressions_per_page:
            raise ArticleError("quantitative excluded-form capacity exceeded on a source page")
        excluded.append(match.span())
    rows: list[QuantityMention] = []
    cursor = 0
    for match in EXPRESSION.finditer(page.text):
        while cursor < len(excluded) and excluded[cursor][1] <= match.start():
            cursor += 1
        if cursor < len(excluded) and excluded[cursor][0] < match.end():
            continue
        if len(rows) >= settings.maximum_expressions_per_page:
            raise ArticleError("quantitative expression capacity exceeded on a source page")
        form, value, unit = _form(match)
        source = witness(page, match.start(), match.end())
        context = witness(
            page,
            max(0, match.start() - settings.context_characters_each_side),
            min(len(page.text), match.end() + settings.context_characters_each_side),
        )
        cues, omitted = _nearby(page, context, settings.maximum_cues_per_expression)
        rows.append(
            QuantityMention(
                mention_id=_mention_id(source, form),
                form=form,
                value_observed=value,
                unit_observed=unit,
                source=source,
                context=context,
                nearby_cues=cues,
                omitted_nearby_cues=omitted,
                flags=_flags(form),
            )
        )
    return tuple(rows)


def _layer(
    sources: tuple[QuantitySource, ...],
    mentions: tuple[QuantityMention, ...],
    layer: Literal["native", "ocr"],
) -> QuantityLayerSummary:
    eligible = tuple(row for row in sources if row.layer == layer)
    selected = tuple(row for row in mentions if row.source.layer == layer)
    pages = {(row.source.issue_id, row.source.page_index) for row in selected}
    counts = Counter(row.form for row in selected)
    return QuantityLayerSummary(
        layer=layer,
        pages=len(eligible),
        issues=len({row.issue_id for row in eligible}),
        raw_characters=sum(row.characters for row in eligible),
        expression_pages=len(pages),
        no_expression_pages=len(eligible) - len(pages),
        form_counts=tuple(QuantityFormCount(form=form, expressions=counts[form]) for form in FORMS),
    )


def quantitative_expressions(
    pages: tuple[ArticlePage, ...], settings: QuantitySettings | None = None
) -> QuantityRun:
    """Return complete bounded syntactic retrieval for caller-admitted current page text."""
    settings = settings or QuantitySettings()
    method = implementation_digest()
    sources = _sources(pages, settings)
    expressions: list[QuantityMention] = []
    for page in sorted(pages, key=lambda p: (p.issue_id, p.page_index, p.layer)):
        expressions.extend(_page_mentions(page, settings))
        if len(expressions) > settings.maximum_expressions:
            raise ArticleError("quantitative expression capacity exceeded for the supplied frame")
    result = QuantityRun(
        input_sha256=_input_digest(sources),
        implementation_sha256=method,
        settings_sha256=text_digest(settings.model_dump_json()),
        settings=settings,
        sources=sources,
        expressions=tuple(expressions),
        layers=tuple(_layer(sources, tuple(expressions), name) for name in ("native", "ocr")),
        matching_scope=SCOPE,
    )
    if implementation_digest() != method:
        raise ArticleError("quantitative retrieval producer changed during measurement")
    return result
