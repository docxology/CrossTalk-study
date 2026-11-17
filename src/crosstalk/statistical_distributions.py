"""Descriptive distributions with unit-specific denominators and metadata dates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.statistical_bootstrap import describe
from crosstalk.statistical_records import DecadeSummary

if TYPE_CHECKING:
    from crosstalk.statistical_records import (
        Distribution,
        ImageStatistic,
        IssueStatistic,
        PageStatistic,
    )


def distributions(
    issues: tuple[IssueStatistic, ...],
    pages: tuple[PageStatistic, ...],
    images: tuple[ImageStatistic, ...],
) -> tuple[Distribution, ...]:
    """Describe captured units; this adds no sampling intervals to census counts."""
    missing_pixels = sum(
        max(0, row.saved_distinct_assets - row.measured_distinct_assets)
        for row in issues
        if row.measured_distinct_assets is not None
    )
    unknown_pages = sum(row.reference_inventory_status != "enumerated" for row in pages)
    pixel_scope = {"unit_frame_complete": unknown_pages == 0, "unknown_frame_pages": unknown_pages}
    return (
        describe(
            tuple(float(row.pages) for row in issues),
            ("extracted_pages_per_issue", "extracted physical pages per accepted source issue"),
        ),
        describe(
            tuple(float(row.raw_tokens) for row in issues),
            ("raw_tokens_per_issue", "raw alphabetic tokens per source-distinct issue"),
        ),
        describe(
            tuple(row.hedge_per_1000 for row in issues),
            (
                "hedge_per_1000_by_issue",
                "lexical-proxy occurrences per 1000 raw tokens within issue",
            ),
        ),
        describe(
            tuple(row.modal_per_1000 for row in issues),
            (
                "modal_per_1000_by_issue",
                "lexical-proxy occurrences per 1000 raw tokens within issue",
            ),
        ),
        describe(
            tuple(row.mean_window_ttr for row in issues),
            ("window_ttr_by_issue", "per-issue mean complete-window normalized type-token ratio"),
        ),
        describe(
            tuple(float(row.normalized_tokens) for row in pages),
            ("normalized_tokens_per_page", "normalized alphabetic tokens per physical page"),
        ),
        describe(
            tuple(
                float(row.saved_occurrences)
                if row.reference_inventory_status == "enumerated"
                else None
                for row in pages
            ),
            (
                "saved_occurrences_per_page",
                "recorded saved raster placements per reference-enumerated physical page",
            ),
        ),
        describe(
            tuple(row.mean_window_ttr for row in pages),
            ("window_ttr_by_page", "per-page mean complete-window normalized type-token ratio"),
        ),
        describe(
            tuple(float(row.width * row.height) for row in images) + (None,) * missing_pixels,
            ("saved_asset_pixels", "pixels per issue/saved-raster-asset pair"),
        ).model_copy(update=pixel_scope),
        describe(
            tuple(row.aspect_ratio for row in images) + (None,) * missing_pixels,
            ("saved_asset_aspect_ratio", "width/height per issue/saved-raster-asset pair"),
        ).model_copy(update=pixel_scope),
        describe(
            tuple(row.grayscale_entropy_bits for row in images) + (None,) * missing_pixels,
            (
                "saved_asset_grayscale_entropy",
                "grayscale entropy bits per issue/saved-raster-asset pair",
            ),
        ).model_copy(update=pixel_scope),
    )


def decade_summaries(issues: tuple[IssueStatistic, ...]) -> tuple[DecadeSummary, ...]:
    """Group usable repository metadata years without claiming printed-date verification."""
    decades = sorted({row.metadata_decade for row in issues if row.metadata_decade is not None})
    result: list[DecadeSummary] = []
    for decade in decades:
        members = tuple(row for row in issues if row.metadata_decade == decade)
        result.append(
            DecadeSummary(
                metadata_decade=decade,
                issues=len(members),
                pages=sum(row.pages for row in members),
                raw_tokens=sum(row.raw_tokens for row in members),
                saved_occurrences=sum(row.saved_occurrences for row in members),
                mean_issue_pages=sum(row.pages for row in members) / len(members),
            )
        )
    return tuple(result)
