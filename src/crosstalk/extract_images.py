"""Publish only independently resolved embedded assets; preserve all reference gaps."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.image_inventory import ImageInventory, scan_image_references
from crosstalk.image_occurrences import ImageOccurrence, ImageStatus
from crosstalk.image_reference_records import MAX_PIXELS, ImageReference
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.pdf_adapter import image_payload

if TYPE_CHECKING:
    from pathlib import Path

    import pymupdf

    from crosstalk.extraction_method import ExtractionProducer


@dataclass(frozen=True, slots=True)
class ImageExtraction:
    """One scan's encoded asset outcomes and explicit inventory coverage."""

    images: tuple[ImageOccurrence, ...]
    inventory: ImageInventory


@dataclass(frozen=True, slots=True)
class ImageExtractionContext:
    """Publication directory and producer identity shared by all image placements."""

    root: Path
    producer: ExtractionProducer


def _save_asset(
    document: pymupdf.Document, reference: ImageReference, root: Path
) -> tuple[str, str]:
    if reference.resolved_xref is None:
        raise AcquisitionError("Unresolved image reference cannot save an asset")
    payload = image_payload(document, reference.resolved_xref)
    if (payload.width, payload.height) != (reference.width, reference.height):
        raise AcquisitionError("Encoded image dimensions differ from resolved resource metadata")
    digest = hashlib.sha256(payload.image).hexdigest()
    relative = f"data/processed/images/{digest}.{payload.ext}"
    directory = safe_directory(root, "data/processed/images")
    _ = publish_metadata(directory, f"{digest}.{payload.ext}", payload.image)
    return digest, relative


def _occurrence(
    document: pymupdf.Document, reference: ImageReference, root: Path
) -> ImageOccurrence:
    status: ImageStatus
    digest = relative = None
    if reference.width * reference.height > MAX_PIXELS:
        status = "oversized-skipped"
    elif min(reference.width, reference.height) < 24:
        status = "small-skipped"
    elif reference.resolution_status != "resolved-xobject":
        status = "reference-unavailable"
    else:
        status = "saved"
        digest, relative = _save_asset(document, reference, root)
    return ImageOccurrence(
        bbox=reference.bbox,
        width=reference.width,
        height=reference.height,
        xref=reference.resolved_xref or 0,
        status=status,
        sha256=digest,
        path=relative,
        reference=reference,
    )


def extract_page_images(
    document: pymupdf.Document,
    page: pymupdf.Page,
    context: ImageExtractionContext,
) -> ImageExtraction:
    """Retain every bounded occurrence even when no trustworthy encoded reference exists."""
    scan = scan_image_references(page, context.producer)
    return ImageExtraction(
        tuple(_occurrence(document, reference, context.root) for reference in scan.references),
        scan.inventory,
    )
