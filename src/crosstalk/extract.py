"""Bounded, source-linked PDF extraction; OCR and mask compositing are not run."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import pymupdf
from PIL import Image, ImageDraw

from crosstalk.acquisition_lock import project_lock
from crosstalk.extract_images import ImageExtractionContext, extract_page_images
from crosstalk.extraction_cache import CacheIdentity, PageCache, previous_outcomes, reseal_outcomes
from crosstalk.extraction_method import ExtractionProducer, current_extraction_producer
from crosstalk.models import AcquisitionError, file_digest, safe_directory
from crosstalk.pdf_adapter import (
    block_bbox,
    document_info,
    page_geometry,
    preview_png,
    text_blocks,
)
from crosstalk.records import (
    ExtractionSummary,
    ImageOccurrence,
    IssueExtraction,
    PageRecord,
    Record,
    TextBlock,
    write_records,
)
from crosstalk.visual_outputs import save_visual

if TYPE_CHECKING:
    from pathlib import Path

MAX_PDF_BYTES: Final = 250 * 1024 * 1024
MAX_PAGES: Final = 500
__all__ = [
    "ExtractionSummary",
    "ImageOccurrence",
    "PageRecord",
    "Record",
    "extract_corpus",
    "write_records",
]


@dataclass(frozen=True, slots=True)
class PdfSource:
    """Physical source identity shared by all page observations in an issue."""

    root: Path
    pdf: Path
    sha256: str
    producer: ExtractionProducer


@dataclass(frozen=True, slots=True)
class ExtractionScope:
    """Requested page limit and the independently saved prior receipt."""

    limit: int
    prior: IssueExtraction | None
    producer: ExtractionProducer


def _page_record(document: pymupdf.Document, index: int, source: PdfSource) -> PageRecord:
    page = document[index]
    geometry = page_geometry(page)
    blocks = tuple(
        TextBlock(bbox=block_bbox(block), text=block[4], number=block[5])
        for block in text_blocks(page)
        if block[6] == 0
    )
    text = "\n".join(block.text for block in blocks)
    markers = ["reading-order-unverified", "ocr-not-run"]
    if len(text.strip()) < 60:
        markers.append("low-text-ocr-review")
    if "\ufffd" in text:
        markers.append("replacement-characters")
    producer = source.producer
    visual = extract_page_images(document, page, ImageExtractionContext(source.root, producer))
    if visual.inventory.status == "unavailable":
        markers.append("image-reference-inventory-unavailable")
    if any(image.status == "reference-unavailable" for image in visual.images):
        markers.append("image-reference-gaps")
    return PageRecord(
        issue_id=source.pdf.stem,
        source_pdf=source.pdf.relative_to(source.root).as_posix(),
        source_sha256=source.sha256,
        producer=producer,
        image_inventory=visual.inventory,
        page_index=index,
        page_label=page.get_label(),
        width=geometry.width,
        height=geometry.height,
        text=text,
        blocks=blocks,
        images=visual.images,
        quality=tuple(markers),
    )


def _preview(page: pymupdf.Page, target: Path) -> Image.Image:
    geometry = page_geometry(page)
    scale = min(220 / geometry.width, 290 / geometry.height)
    with Image.open(io.BytesIO(preview_png(page, scale))) as source:
        thumbnail = source.convert("RGB")
    target.parent.mkdir(parents=True, exist_ok=True)
    save_visual(thumbnail, target)
    return thumbnail


def _extract_pdf(
    pdf: Path, root: Path, scope: ExtractionScope
) -> tuple[IssueExtraction, tuple[PageRecord, ...]]:
    if pdf.is_symlink() or pdf.stat().st_size > MAX_PDF_BYTES:
        return IssueExtraction(
            issue_id=pdf.stem, status="failed", error="PDF symlink or byte bound refused"
        ), ()
    digest = file_digest(pdf)
    target = root / "data/processed/pages" / f"{pdf.stem}.jsonl"
    if target.is_symlink():
        message = "Page cache symlink refused"
        raise ValueError(message)
    with pymupdf.open(pdf) as document:
        info = document_info(document)
        if info.needs_pass or not info.is_pdf:
            return IssueExtraction(
                issue_id=pdf.stem,
                status="failed",
                source_sha256=digest,
                error="Encrypted or non-PDF input",
            ), ()
        count = min(info.page_count, scope.limit)
        cache = PageCache.read(root, pdf.stem)
        resumed = cache.resumes(
            CacheIdentity(pdf.stem, digest, count, info.page_count, scope.producer), scope.prior
        )
        pages = (
            cache.pages
            if resumed
            else tuple(
                _page_record(document, index, PdfSource(root, pdf, digest, scope.producer))
                for index in range(count)
            )
        )
        if not resumed:
            cache.preserve()
            write_records(target, pages)
        status: Literal["complete", "partial", "failed"] = (
            "complete" if count == info.page_count else "partial"
        )
        action: Literal["generated", "verified-resume", "regenerated-unsealed", "regenerated"] = (
            "verified-resume"
            if resumed
            else "generated"
            if cache.raw is None
            else "regenerated-unsealed"
            if scope.prior is None or scope.prior.page_artifact_sha256 is None
            else "regenerated"
        )
        return IssueExtraction(
            issue_id=pdf.stem,
            source_sha256=digest,
            page_artifact_sha256=file_digest(target),
            total_pages=info.page_count,
            extracted_pages=count,
            resumed=resumed,
            cache_action=action,
            status=status,
        ), pages


def _extract_corpus_locked(root: Path, max_pages: int | None = None) -> ExtractionSummary:
    """Extract at most 500 pages per local issue; preserve raw PDF bytes unchanged."""
    limit = min(max_pages, MAX_PAGES) if max_pages is not None else MAX_PAGES
    if limit < 1:
        message = "max_pages must be positive"
        raise ValueError(message)
    for directory in (
        "data/raw/pdf",
        "data/processed/pages",
        "data/processed/images",
        "output/reports",
        "output/figures/page_previews",
    ):
        _ = safe_directory(root, directory)
    outcomes: list[IssueExtraction] = []
    prior = {outcome.issue_id: outcome for outcome in previous_outcomes(root)}
    producer = current_extraction_producer()
    previews: list[tuple[Image.Image, str]] = []
    for pdf in sorted((root / "data/raw/pdf").glob("*.pdf")):
        try:
            outcome, pages = _extract_pdf(
                pdf, root, ExtractionScope(limit, prior.get(pdf.stem), producer)
            )
            if pages and len(previews) < 12:
                with pymupdf.open(pdf) as document:
                    for row in pages[: min(3, 12 - len(previews))]:
                        label = f"{pdf.stem} p{row.page_index + 1}"
                        target = (
                            root
                            / "output/figures/page_previews"
                            / f"{pdf.stem}-{row.page_index + 1}.png"
                        )
                        previews.append((_preview(document[row.page_index], target), label))
            outcomes.append(outcome)
        except (pymupdf.FileDataError, RuntimeError, OSError, ValueError) as error:
            outcomes.append(
                IssueExtraction(
                    issue_id=pdf.stem, status="failed", error=f"{type(error).__name__}: {error}"
                )
            )
    contact = None
    if previews:
        sheet = Image.new("RGB", (720, 330 * ((len(previews) + 2) // 3)), "#e8e8e8")
        draw = ImageDraw.Draw(sheet)
        for index, (thumbnail, label) in enumerate(previews):
            x, y = (index % 3) * 240 + 10, (index // 3) * 330 + 10
            sheet.paste(thumbnail, (x, y))
            draw.text((x, y + 296), label[:34], fill="black")
        contact = "output/figures/contact_sheet.png"
        save_visual(sheet, root / contact)
    summary = ExtractionSummary(
        issues=reseal_outcomes(root, tuple(outcomes)),
        page_limit_per_issue=limit,
        contact_sheet=contact,
    )
    if current_extraction_producer() != producer:
        raise AcquisitionError(
            "Extraction implementation or native runtime changed during the pass"
        )
    write_records(root / "output/reports/extraction.jsonl", (summary,))
    return summary


def extract_corpus(root: Path, max_pages: int | None = None) -> ExtractionSummary:
    """Take project admission before migration, resume checks and extraction publication."""
    with project_lock(root):
        return _extract_corpus_locked(root, max_pages)
