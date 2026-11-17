"""Adapt independently sealed native/OCR pages without merging their text layers."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from crosstalk.article_records import ArticleError, ArticlePage, SourceBlock
from crosstalk.index_observe import IndexReader
from crosstalk.locator_storage import read_metadata
from crosstalk.ocr_records import PageResult, relative_file
from crosstalk.records import ExtractionSummary
from crosstalk.text_source import MeasurementInputs, admit_text_source

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.records import PageRecord


class _Accepted(BaseModel):
    """Parse accepted result fields; unrelated evidence stays bound in the full raw index."""

    result: PageResult


class _IndexPage(BaseModel):
    """Require typed acceptance or explicit absence for every selected index page."""

    accepted: _Accepted | None


class _Index(BaseModel):
    """A narrow projection, not a claim to revalidate the prior supervisor's full ledger."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    pages: tuple[_IndexPage, ...]


def native_page(page: PageRecord, artifact_path: str, artifact_sha256: str) -> ArticlePage:
    """Retain page text and native block numbers exactly, including duplicate blocks."""
    return ArticlePage(
        issue_id=page.issue_id,
        pdf_sha256=page.source_sha256,
        page_index=page.page_index,
        page_label=page.page_label,
        layer="native",
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        text=page.text,
        blocks=tuple(
            SourceBlock(block_number=b.number, bbox=b.bbox, text=b.text) for b in page.blocks
        ),
        flags=page.quality,
    )


def read_native_pages(root: Path, *, reader: IndexReader | None = None) -> tuple[ArticlePage, ...]:
    """Require current manifest, extraction seals, actual PDFs and ordered native3 pages."""
    reader = _reader(root, reader)
    report = ExtractionSummary.model_validate_json(reader.read("output/reports/extraction.jsonl"))
    pages: list[ArticlePage] = []
    for outcome in report.issues:
        admitted = admit_text_source(root, outcome, None, reader=reader)
        if not isinstance(admitted, MeasurementInputs):
            raise ArticleError(f"article source refused: {outcome.issue_id}: {admitted.reason}")
        relative = f"data/processed/pages/{outcome.issue_id}.jsonl"
        pages.extend(
            native_page(page, relative, admitted.page_artifact_sha256) for page in admitted.pages
        )
    reader.recheck()
    if len({(page.issue_id, page.page_index) for page in pages}) != len(pages):
        raise ArticleError("native article input repeats a physical page")
    return tuple(pages)


def _reader(root: Path, selected: IndexReader | None) -> IndexReader:
    """Allow the publication caller to retain and recheck the full admission binding set."""
    reader = IndexReader(root) if selected is None else selected
    if reader.root != root.absolute():
        raise ArticleError("shared article source reader belongs to another physical project root")
    return reader


def _native_frame(native: tuple[ArticlePage, ...]) -> dict[tuple[str, int], ArticlePage]:
    """Require unique physical pages and consistent issue/PDF/artifact identities."""
    current = {(p.issue_id, p.page_index): p for p in native}
    if any(page.layer != "native" for page in native):
        raise ArticleError("OCR admission requires independently supplied native pages")
    if len(current) != len(native):
        raise ArticleError("native source identity is not unique")
    issue_sources: dict[str, tuple[str, str, str]] = {}
    pdf_sources: dict[str, str] = {}
    for page in native:
        identity = (page.pdf_sha256, page.artifact_path, page.artifact_sha256)
        if issue_sources.setdefault(page.issue_id, identity) != identity:
            raise ArticleError("native issue contains conflicting physical source bindings")
        if pdf_sources.setdefault(page.pdf_sha256, page.issue_id) != page.issue_id:
            raise ArticleError("native physical PDF aliases require reconciliation")
    return current


def _native_page_seal(
    reader: IndexReader,
    base: ArticlePage,
    line_seals: dict[str, tuple[str, ...]],
    pdf_seals: dict[str, str],
) -> str:
    """Bind actual current PDF and page-artifact bytes once per issue in this read pass."""
    if base.issue_id not in pdf_seals:
        pdf_seals[base.issue_id] = reader.digest(f"data/raw/pdf/{base.issue_id}.pdf").sha256
    if pdf_seals[base.issue_id] != base.pdf_sha256:
        raise ArticleError("actual raw PDF differs from supplied native OCR context")
    if base.issue_id not in line_seals:
        native_raw = reader.read(base.artifact_path)
        if hashlib.sha256(native_raw).hexdigest() != base.artifact_sha256:
            raise ArticleError("native article pages changed before OCR admission")
        line_seals[base.issue_id] = tuple(
            hashlib.sha256(line).hexdigest() for line in native_raw.splitlines()
        )
    if base.page_index >= len(line_seals[base.issue_id]):
        raise ArticleError("native OCR context selects a physical page outside its artifact")
    return line_seals[base.issue_id][base.page_index]


def read_ocr_pages(
    root: Path,
    native: tuple[ArticlePage, ...],
    index_path: str,
    index_sha256: str,
    *,
    reader: IndexReader | None = None,
) -> tuple[ArticlePage, ...]:
    """Use one exact accepted index; verify each native/PDF identity against current inputs.

    The index is an immutable prior evidence selection. Its measured transcription accuracy
    remains unknown. Its embedded text is bound to the actual selected index bytes, rather
    than falsely claiming the reserialized result is its original artifact file.
    """
    reader = _reader(root, reader)
    relative = relative_file(index_path)
    observed = reader.digest(relative)
    raw = read_metadata(reader.path(relative), 64_000_000)
    if observed.sha256 != index_sha256 or hashlib.sha256(raw).hexdigest() != index_sha256:
        raise ArticleError("selected OCR index changed")
    content = _Index.model_validate_json(raw)
    current = _native_frame(native)
    results: list[ArticlePage] = []
    seen: set[tuple[str, int]] = set()
    line_seals: dict[str, tuple[str, ...]] = {}
    pdf_seals: dict[str, str] = {}
    for row in content.pages:
        accepted = row.accepted
        if accepted is None:
            continue
        result = accepted.result
        key = (result.source.issue_id, result.source.page_index)
        if key not in current or key in seen:
            raise ArticleError("accepted OCR is duplicate or outside current native scope")
        base = current[key]
        page_seal = _native_page_seal(reader, base, line_seals, pdf_seals)
        if (
            result.source.source_kind != "journal-page"
            or result.native_extractor_version != "3"
            or result.source.pdf_sha256 != base.pdf_sha256
            or result.source.native_artifact_sha256 != base.artifact_sha256
            or result.source.native_page_sha256 != page_seal
            or result.status not in {"ocr-produced", "ocr-empty"}
        ):
            raise ArticleError("accepted OCR disagrees with actual native/PDF input")
        seen.add(key)
        results.append(
            ArticlePage(
                issue_id=base.issue_id,
                pdf_sha256=base.pdf_sha256,
                page_index=base.page_index,
                page_label=base.page_label,
                layer="ocr",
                artifact_path=index_path,
                artifact_sha256=index_sha256,
                text=result.text,
                blocks=tuple(
                    SourceBlock(block_number=b.number, bbox=b.bbox, text=b.text)
                    for b in result.blocks
                ),
                flags=result.quality,
            )
        )
    reader.recheck()
    return tuple(results)
