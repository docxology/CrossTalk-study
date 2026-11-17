"""Rectangular issue statistics retain explicit native and visual coverage columns."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.statistical_records import StatisticalRun


def number(value: float | None) -> str:
    """Keep unavailable values empty while preserving genuine zero."""
    return "" if value is None else str(value)


def issue_projection(run: StatisticalRun) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Project current source-distinct native issues with their separate visual scope."""
    source = run.source_binding_sha256
    return (
        (
            "source_binding_sha256",
            "issue_id",
            "pdf_sha256",
            "page_artifact_sha256",
            "issued",
            "date_status",
            "metadata_year",
            "pages",
            "total_pdf_pages",
            "extracted_page_fraction",
            "raw_tokens",
            "normalized_tokens",
            "hedge_per_1000",
            "modal_per_1000",
            "complete_windows",
            "mean_window_ttr",
            "saved_distinct_assets",
            "recorded_saved_occurrences",
            "recorded_unsaved_occurrences",
            "extraction_status",
            "visual_status",
            "measured_distinct_assets",
            "measured_occurrences",
            "native_inventory_entries",
            "known_native_inventory_entry_sum",
            "unknown_native_inventory_pages",
            "unavailable_reference_pages",
        ),
        tuple(
            (
                source,
                row.issue_id,
                row.pdf_sha256,
                row.page_artifact_sha256,
                row.issued or "",
                row.date_status,
                number(row.metadata_year),
                str(row.pages),
                number(row.total_pdf_pages),
                number(row.extracted_page_fraction),
                str(row.raw_tokens),
                str(row.normalized_tokens),
                number(row.hedge_per_1000),
                number(row.modal_per_1000),
                str(row.complete_windows),
                number(row.mean_window_ttr),
                str(row.saved_distinct_assets),
                str(row.saved_occurrences),
                str(row.skipped_occurrences),
                row.extraction_status,
                row.visual_status,
                number(row.measured_distinct_assets),
                number(row.measured_occurrences),
                number(row.native_inventory_entries),
                number(row.known_native_inventory_entry_sum),
                number(row.unknown_native_inventory_pages),
                number(row.unavailable_reference_pages),
            )
            for row in run.issues
        ),
    )
