"""Atomic CSV projections of a typed statistical run, including its source identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.models import safe_directory
from crosstalk.statistical_csv import write_csv
from crosstalk.statistical_issue_export import issue_projection
from crosstalk.statistical_issue_export import number as _number

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.statistical_records import StatisticalRun


def export_statistics(root: Path, run: StatisticalRun) -> None:
    """Write small rectangular projections; JSONL remains the full typed contract."""
    directory = safe_directory(root, "output/data")
    source = run.source_binding_sha256
    headers, rows = issue_projection(run)
    write_csv(directory / "statistical_issues.csv", headers, rows)
    write_csv(
        directory / "statistical_pages.csv",
        (
            "source_binding_sha256",
            "issue_id",
            "pdf_sha256",
            "page_artifact_sha256",
            "page_index",
            "normalized_tokens",
            "types",
            "complete_windows",
            "mean_window_ttr",
            "saved_occurrences",
            "skipped_occurrences",
            "low_text",
            "native_inventory_entries",
            "native_inventory_entry_basis",
            "reference_inventory_status",
        ),
        tuple(
            (
                source,
                row.issue_id,
                row.pdf_sha256,
                row.page_artifact_sha256,
                str(row.page_index),
                str(row.normalized_tokens),
                str(row.types),
                str(row.complete_windows),
                _number(row.mean_window_ttr),
                str(row.saved_occurrences),
                str(row.skipped_occurrences),
                str(row.low_text).lower(),
                _number(row.native_inventory_entries),
                row.native_inventory_entry_basis or "",
                row.reference_inventory_status,
            )
            for row in run.pages
        ),
    )
    write_csv(
        directory / "statistical_images.csv",
        (
            "source_binding_sha256",
            "issue_id",
            "pdf_sha256",
            "page_artifact_sha256",
            "image_sha256",
            "path",
            "width",
            "height",
            "aspect_ratio",
            "grayscale_entropy_bits",
            "occurrence_count",
            "pixel_decoder",
            "pixel_decoder_version",
        ),
        tuple(
            (
                source,
                row.issue_id,
                row.pdf_sha256,
                row.page_artifact_sha256,
                row.image_sha256,
                row.path,
                str(row.width),
                str(row.height),
                str(row.aspect_ratio),
                str(row.grayscale_entropy_bits),
                str(row.occurrence_count),
                row.pixel_decoder,
                row.pixel_decoder_version,
            )
            for row in run.images
        ),
    )
    write_csv(
        directory / "statistical_bootstrap.csv",
        (
            "source_binding_sha256",
            "measure",
            "status",
            "estimate",
            "lower",
            "upper",
            "eligible_source_issue_units",
            "excluded_issue_units",
            "excluded_partial_issue_units",
            "excluded_unknown_coverage_issue_units",
            "excluded_metric_unavailable_issue_units",
            "valid_resamples",
            "seed",
            "requested_resamples",
            "minimum_issues",
            "confidence",
        ),
        tuple(
            (
                source,
                row.measure,
                row.status,
                _number(row.estimate),
                _number(row.lower),
                _number(row.upper),
                str(row.eligible_source_issue_units),
                str(row.excluded_issue_units),
                str(row.excluded_partial_issue_units),
                str(row.excluded_unknown_coverage_issue_units),
                str(row.excluded_metric_unavailable_issue_units),
                str(row.valid_resamples),
                str(run.settings.seed),
                str(run.settings.resamples),
                str(run.settings.minimum_issues),
                str(run.settings.confidence),
            )
            for row in run.bootstrap
        ),
    )
    write_csv(
        directory / "statistical_distributions.csv",
        (
            "source_binding_sha256",
            "measure",
            "unit",
            "observed_units",
            "missing_units",
            "minimum",
            "q25",
            "median",
            "q75",
            "maximum",
            "mean",
            "unit_frame_complete",
            "unknown_frame_pages",
        ),
        tuple(
            (
                source,
                row.measure,
                row.unit,
                str(row.observed_units),
                str(row.missing_units),
                _number(row.minimum),
                _number(row.q25),
                _number(row.median),
                _number(row.q75),
                _number(row.maximum),
                _number(row.mean),
                "" if row.unit_frame_complete is None else str(row.unit_frame_complete).lower(),
                _number(row.unknown_frame_pages),
            )
            for row in run.distributions
        ),
    )
    write_csv(
        directory / "statistical_decades.csv",
        (
            "source_binding_sha256",
            "metadata_decade",
            "issues",
            "pages",
            "raw_tokens",
            "saved_occurrences",
            "mean_issue_pages",
            "interpretation",
        ),
        tuple(
            (
                source,
                str(row.metadata_decade),
                str(row.issues),
                str(row.pages),
                str(row.raw_tokens),
                str(row.saved_occurrences),
                str(row.mean_issue_pages),
                "repository-metadata descriptive grouping only",
            )
            for row in run.decades
        ),
    )
