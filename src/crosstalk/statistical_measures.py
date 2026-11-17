"""Construct source-bound issue, page and saved-raster measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.statistical_records import ImageStatistic, IssueStatistic, PageStatistic
from crosstalk.statistical_source import current_pages, metadata_date

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.analysis_records import IssueAnalysis
    from crosstalk.index_observe import IndexReader
    from crosstalk.linguistic_records import IssueLinguistics


@dataclass(frozen=True, slots=True)
class IssueMeasurements:
    """All observational units belonging to one accepted issue source."""

    issue: IssueStatistic
    pages: tuple[PageStatistic, ...]
    images: tuple[ImageStatistic, ...]


def measure_issue(
    root: Path,
    analysis: IssueAnalysis,
    linguistic: IssueLinguistics,
    *,
    reader: IndexReader | None = None,
) -> IssueMeasurements:
    """Crosscheck current inputs before attaching measurements to publication units."""
    pages = current_pages(root, analysis, linguistic, reader=reader)
    visual = analysis.visual
    if visual is None:
        message = "current statistical native analysis requires explicit separate visual coverage"
        raise ValueError(message)
    digest, artifact = linguistic.source_sha256, linguistic.page_artifact_sha256
    date_status, precision, year = metadata_date(analysis.issued, analysis.title)
    page_rows = tuple(
        PageStatistic(
            issue_id=analysis.issue_id,
            pdf_sha256=digest,
            page_artifact_sha256=artifact,
            page_index=page.page_index,
            normalized_tokens=measure.tokens,
            types=measure.types,
            complete_windows=measure.diversity.complete_windows,
            mean_window_ttr=measure.diversity.mean_type_token_ratio,
            saved_occurrences=sum(image.path is not None for image in page.images),
            skipped_occurrences=sum(image.path is None for image in page.images),
            native_inventory_entries=page.image_inventory.occurrence_count
            if page.image_inventory is not None
            else None,
            native_inventory_entry_basis=page.image_inventory.occurrence_count_basis
            if page.image_inventory is not None
            else None,
            reference_inventory_status=page.image_inventory.status
            if page.image_inventory is not None
            else "legacy-unobserved",
            low_text="low-text-ocr-review" in page.quality,
        )
        for page, measure in zip(pages, linguistic.measures.pages, strict=True)
    )
    images = tuple(
        ImageStatistic(
            issue_id=analysis.issue_id,
            pdf_sha256=digest,
            page_artifact_sha256=artifact,
            image_sha256=image.sha256,
            path=image.path,
            width=image.width,
            height=image.height,
            aspect_ratio=image.aspect_ratio,
            grayscale_entropy_bits=image.grayscale_entropy_bits,
            occurrence_count=image.occurrence_count,
            pixel_decoder=image.pixel_decoder,
            pixel_decoder_version=image.pixel_decoder_version,
            pixel_source_pdf=image.pixel_source_pdf,
            pixel_source_sha256=image.pixel_source_sha256,
            pixel_source_page_index=image.pixel_source_page_index,
            pixel_source_xref=image.pixel_source_xref,
            pixel_decoder_initial_error=image.pixel_decoder_initial_error,
        )
        for image in analysis.images
    )
    issue = IssueStatistic(
        issue_id=analysis.issue_id,
        pdf_sha256=digest,
        page_artifact_sha256=artifact,
        title=analysis.title,
        issued=analysis.issued,
        date_status=date_status,
        date_precision=precision,
        metadata_year=year,
        metadata_decade=(year // 10) * 10 if year is not None else None,
        extraction_status=linguistic.extraction_status,
        pages=len(pages),
        total_pdf_pages=linguistic.total_pdf_pages,
        extracted_page_fraction=(
            len(pages) / linguistic.total_pdf_pages
            if linguistic.total_pdf_pages is not None
            else None
        ),
        raw_tokens=analysis.text.tokens,
        normalized_tokens=linguistic.measures.tokens,
        hedge_tokens=analysis.text.hedge_tokens,
        modal_tokens=analysis.text.modal_tokens,
        hedge_per_1000=analysis.text.hedge_per_1000,
        modal_per_1000=analysis.text.modal_per_1000,
        complete_windows=linguistic.measures.complete_windows,
        mean_window_ttr=linguistic.measures.mean_window_type_token_ratio,
        low_text_pages=sum(page.low_text for page in page_rows),
        visual_status=visual.status,
        measured_distinct_assets=len(images),
        measured_occurrences=sum(image.occurrence_count for image in images),
        native_inventory_entries=visual.native_inventory_entries,
        known_native_inventory_entry_sum=visual.known_native_inventory_entry_sum,
        unknown_native_inventory_pages=visual.unknown_native_inventory_pages,
        unavailable_reference_pages=visual.unavailable_reference_pages,
        saved_distinct_assets=len(
            {image.sha256 for page in pages for image in page.images if image.path is not None}
        ),
        saved_occurrences=sum(page.saved_occurrences for page in page_rows),
        skipped_occurrences=sum(page.skipped_occurrences for page in page_rows),
    )
    if issue.saved_occurrences < sum(image.occurrence_count for image in images):
        message = "measured saved occurrences exceed the native recorded saved subset"
        raise ValueError(message)
    return IssueMeasurements(issue, page_rows, images)
