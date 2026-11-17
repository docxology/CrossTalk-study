"""Bounded retained-tool captures and reproducible publisher issue/article-index parsing."""

from __future__ import annotations

from crosstalk.holdings_parse import ToolLine, extract_article_entries, extract_assertions

__all__ = [
    "SourceReader",
    "ToolLine",
    "capture_lines",
    "extract_article_entries",
    "extract_assertions",
    "load_holdings",
    "parse_jsonl",
    "recheck_holdings_inputs",
]

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from crosstalk.case_files import read_bytes, unique_pairs
from crosstalk.catalog import CatalogIssue
from crosstalk.holdings_records import (
    ArticleIndexEntry,
    CatalogObservation,
    HoldingsDecision,
    HoldingsError,
    HoldingsInputs,
    InputBinding,
    IssueAssertion,
    SourceObservation,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

LINE = re.compile(r"^L(\d+): (.*)$", re.MULTILINE)


class SourceReader:
    """Accumulate immutable input bindings; mutation records each observed metadata file."""

    root: Path
    observed: dict[str, str]

    def __init__(self, root: Path) -> None:
        """Create one independent read pass over fixed metadata namespaces."""
        self.root = root.absolute()
        self.observed = {}

    def read(self, relative: str) -> bytes:
        """Confine all reads to ordinary project metadata, with independent byte bounds."""
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or path.as_posix() != relative
            or ".." in path.parts
            or path.parts[:2] not in {("data", "manifest"), ("data", "source-observations")}
        ):
            raise HoldingsError("holdings input path escapes the fixed metadata namespace")
        raw = read_bytes(self.root / relative, 4_000_000)
        digest = hashlib.sha256(raw).hexdigest()
        prior = self.observed.setdefault(relative, digest)
        if digest != prior:
            raise HoldingsError("holdings input changed during observation")
        return raw

    def recheck(self) -> None:
        """Reobserve remembered bytes before their derived report can be published."""
        for name in tuple(self.observed):
            _ = self.read(name)


def parse_jsonl[T: BaseModel](raw: bytes, model: type[T]) -> tuple[T, ...]:
    """Reject duplicate JSON members before the strict typed JSONL boundary."""
    lines = raw.splitlines()
    if len(lines) > 10000 or any(not line.strip() for line in lines):
        raise HoldingsError("holdings JSONL has empty rows or exceeds its row bound")
    for line in lines:
        if json.loads(line, object_pairs_hook=unique_pairs) is None:
            raise HoldingsError("holdings JSONL row is null")
    return tuple(model.model_validate_json(line) for line in lines)


def capture_lines(source: SourceObservation, reader: SourceReader) -> tuple[ToolLine, ...]:
    """Require complete numbered tool-page coverage and agreement of overlapping captures."""
    merged: dict[int, str] = {}
    for binding in source.captures:
        raw = reader.read(binding.path)
        if hashlib.sha256(raw).hexdigest() != binding.sha256:
            raise HoldingsError("retained tool representation digest disagrees")
        text = raw.decode("utf-8")
        canonical = source.capture_url.replace(":80/", "/")
        if source.capture_url not in text and canonical not in text:
            raise HoldingsError("tool capture does not attribute the declared archived page")
        for match in LINE.finditer(text):
            number, value = int(match[1]), match[2]
            if number in merged and merged[number] != value:
                raise HoldingsError("overlapping tool captures disagree")
            merged[number] = value
    if set(merged) != set(range(source.total_tool_lines)):
        raise HoldingsError("retained numbered tool-page coverage is incomplete")
    return tuple(ToolLine(line=number, text=merged[number]) for number in sorted(merged))


def load_holdings(root: Path) -> HoldingsInputs:
    """Admit metadata only after reproducing every assertion and annual index entry."""
    reader = SourceReader(root)
    prefix = "data/manifest/"
    sources = parse_jsonl(
        reader.read(prefix + "historical-source-observations.jsonl"), SourceObservation
    )
    assertions = parse_jsonl(reader.read(prefix + "historical-assertions.jsonl"), IssueAssertion)
    entries = parse_jsonl(reader.read(prefix + "historical-article-index.jsonl"), ArticleIndexEntry)
    reproduced: list[IssueAssertion] = []
    articles: list[ArticleIndexEntry] = []
    for source in sources:
        lines = capture_lines(source, reader)
        reproduced.extend(extract_assertions(source, lines))
        if source.format == "article-index":
            articles.extend(extract_article_entries(source, lines))
    if assertions != tuple(reproduced) or entries != tuple(articles):
        raise HoldingsError("normalized historical data does not reproduce from retained tool text")
    catalog = tuple(
        CatalogObservation(
            issue_id=row.issue_id,
            title=row.title,
            issued_metadata=row.issued_metadata,
            landing_url=row.landing_url,
        )
        for row in parse_jsonl(reader.read(prefix + "catalog.jsonl"), CatalogIssue)
    )
    decisions = parse_jsonl(reader.read(prefix + "historical-decisions.jsonl"), HoldingsDecision)
    for decision in decisions:
        for binding in decision.evidence_receipts:
            if hashlib.sha256(reader.read(binding.path)).hexdigest() != binding.sha256:
                raise HoldingsError("identity decision witness receipt changed")
    reader.recheck()
    return HoldingsInputs(
        assertions=assertions,
        catalog=catalog,
        decisions=decisions,
        sources=sources,
        article_entries=entries,
        bindings=tuple(
            InputBinding(path=name, sha256=digest)
            for name, digest in sorted(reader.observed.items())
        ),
    )


def recheck_holdings_inputs(root: Path, inputs: HoldingsInputs) -> None:
    """Public consumers must recheck all admitted metadata before publishing derived evidence."""
    reader = SourceReader(root)
    for binding in inputs.bindings:
        if hashlib.sha256(reader.read(binding.path)).hexdigest() != binding.sha256:
            raise HoldingsError("historical reconciliation input changed after admission")
