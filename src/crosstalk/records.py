"""Immutable extraction artifacts and atomic JSONL publication."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crosstalk.extraction_method import ExtractionProducer  # noqa: TC001 -- Pydantic runtime field.
from crosstalk.image_inventory import ImageInventory  # noqa: TC001 -- Pydantic runtime field.
from crosstalk.image_occurrences import ImageOccurrence
from crosstalk.image_reference_records import ImageReferenceError
from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves the digest field at runtime.

EXTRACTOR_VERSION: Final = "3"
BBox = tuple[float, float, float, float]
__all__ = [
    "EXTRACTOR_VERSION",
    "BBox",
    "ExtractionSummary",
    "ImageInfo",
    "ImageOccurrence",
    "IssueExtraction",
    "PageRecord",
    "Record",
    "TextBlock",
    "write_records",
]


class Record(BaseModel):
    """Immutable, parsed extraction artifact."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class TextBlock(Record):
    """Text and its PDF coordinate rectangle; ordering is a layout heuristic."""

    bbox: BBox
    text: str
    number: int


class PageRecord(Record):
    """One physical PDF page; page_label is PDF metadata, not OCR of folios."""

    issue_id: str
    source_pdf: str
    source_sha256: str
    extractor_version: Literal["2", "3"] = EXTRACTOR_VERSION
    producer: ExtractionProducer | None = None
    image_inventory: ImageInventory | None = None
    page_index: int = Field(ge=0)
    page_label: str
    width: float
    height: float
    text: str
    blocks: tuple[TextBlock, ...]
    images: tuple[ImageOccurrence, ...]
    quality: tuple[str, ...]

    @model_validator(mode="after")
    def image_method_consistency(self) -> PageRecord:
        """Current records require explicit reference custody; legacy evidence is never promoted."""
        if self.extractor_version == "2":
            if (
                self.producer is not None
                or self.image_inventory is not None
                or any(image.reference is not None for image in self.images)
            ):
                raise ImageReferenceError(
                    "Legacy version2 cannot carry version3 reference evidence"
                )
            return self
        inventory = self.image_inventory
        if self.producer is None or inventory is None:
            raise ImageReferenceError("Version3 requires producer and image inventory evidence")
        if inventory.status == "unavailable":
            if self.images:
                raise ImageReferenceError(
                    "Unavailable inventory cannot carry enumerated occurrences"
                )
            return self
        if inventory.occurrence_count != len(self.images):
            raise ImageReferenceError("Image inventory count differs from preserved occurrences")
        counts: dict[str, int] = {}
        for index, image in enumerate(self.images):
            reference = image.reference
            if reference is None or reference.occurrence_index != index:
                raise ImageReferenceError("Version3 image references must retain occurrence order")
            counts[reference.resolution_status] = counts.get(reference.resolution_status, 0) + 1
        if counts != {row.status: row.count for row in inventory.reference_status_counts}:
            raise ImageReferenceError(
                "Image inventory status counts differ from preserved references"
            )
        return self


class IssueExtraction(Record):
    """Explicit complete/partial/failure state for one PDF."""

    issue_id: str
    source_sha256: str | None = None
    page_artifact_sha256: Digest | None = None
    total_pages: int | None = None
    extracted_pages: int = 0
    resumed: bool = False
    cache_action: (
        Literal["generated", "verified-resume", "regenerated-unsealed", "regenerated"] | None
    ) = None
    status: Literal["complete", "partial", "failed"]
    error: str | None = None


class ExtractionSummary(Record):
    """Run scope and outcomes; completion is limited to the selected local PDFs."""

    issues: tuple[IssueExtraction, ...]
    page_limit_per_issue: int
    contact_sheet: str | None
    ocr_status: str = "not-run"


class ImageInfo(BaseModel):
    """Projection parsed from PyMuPDF's image inventory."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    bbox: BBox
    width: int
    height: int
    xref: int


def write_records(path: Path, records: tuple[BaseModel, ...]) -> None:
    """Atomically replace one JSONL artifact with unique temporary custody."""
    if path.is_symlink():
        message = "Artifact path must be a regular local file"
        raise ValueError(message)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        for record in records:
            _ = stream.write(record.model_dump_json() + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(mode)
    _ = temporary.replace(path)
