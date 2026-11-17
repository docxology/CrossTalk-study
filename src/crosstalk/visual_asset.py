"""Canonical measurement of one observed saved raster without altering page records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.analysis_records import VisualMetrics
from crosstalk.image_decode import measure_raster
from crosstalk.image_preview import publish_preview
from crosstalk.models import AcquisitionError

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.records import ImageOccurrence, PageRecord


def measure_recorded_asset(
    root: Path, occurrences: tuple[tuple[PageRecord, ImageOccurrence], ...]
) -> VisualMetrics:
    """Retain original coherent page objects and all declared physical placement observations."""
    representatives = tuple((page, image) for page, image in occurrences if image.path is not None)
    if not representatives:
        raise AcquisitionError("saved raster measurement requires an actual saved occurrence")
    page, image = representatives[-1]
    if image.sha256 is None or image.path is None:
        raise AcquisitionError("saved raster measurement requires an encoded asset identity")
    measured = measure_raster(root, page, image)
    return VisualMetrics(
        sha256=image.sha256,
        path=image.path,
        width=image.width,
        height=image.height,
        aspect_ratio=image.width / image.height,
        grayscale_entropy_bits=measured.entropy,
        mean_rgb=measured.mean_rgb,
        occurrence_count=len(occurrences),
        page_indexes=tuple(sorted({record.page_index for record, _ in occurrences})),
        pixel_decoder=measured.pixel_decoder,
        pixel_decoder_version=measured.pixel_decoder_version,
        pixel_source_pdf=measured.pixel_source_pdf,
        pixel_source_sha256=measured.pixel_source_sha256,
        pixel_source_page_index=measured.pixel_source_page_index,
        pixel_source_xref=measured.pixel_source_xref,
        pixel_decoder_initial_error=measured.pixel_decoder_initial_error,
        preview=publish_preview(root, measured.preview_png),
    )
