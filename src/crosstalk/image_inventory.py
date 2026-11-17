"""Explicit image-reference inventory coverage, separate from native text eligibility."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from pydantic import Field, model_validator

from crosstalk.extraction_method import (
    QUALIFIED_PYMUPDF_VERSION,
    QUALIFIED_PYMUPDF_WRAPPER_SHA256,
    ExtractionProducer,
)
from crosstalk.image_reference_records import (
    ImageReference,
    ImageReferenceError,
    ImageReferenceInventoryError,
    Record,
    ResolutionStatus,
)
from crosstalk.image_references import image_references

if TYPE_CHECKING:
    import pymupdf


class ReferenceStatusCount(Record):
    """Counts describe native placement records, never semantic figures."""

    status: ResolutionStatus
    count: int = Field(ge=0)


class ImageInventory(Record):
    """An unavailable scan has unknown reference coverage rather than a true zero."""

    status: Literal["enumerated", "unavailable"]
    occurrence_count: int | None = Field(default=None, ge=0)
    occurrence_count_basis: Literal["native-occurrence-inventory"] | None = None
    reference_status_counts: tuple[ReferenceStatusCount, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def coverage_consistency(self) -> ImageInventory:
        """Do not encode a failed inventory as a measured absence of image occurrences."""
        if (self.occurrence_count is None) != (self.occurrence_count_basis is None):
            raise ImageReferenceError(
                "Known occurrence count requires its native observation basis"
            )
        match self.status:
            case "enumerated":
                statuses = tuple(row.status for row in self.reference_status_counts)
                if (
                    self.occurrence_count is None
                    or sum(row.count for row in self.reference_status_counts)
                    != self.occurrence_count
                    or len(set(statuses)) != len(statuses)
                    or self.reason is not None
                ):
                    raise ImageReferenceError("enumerated inventory counts or reason disagree")
            case "unavailable":
                if self.reference_status_counts or self.reason is None:
                    raise ImageReferenceError("unavailable inventory requires an explicit reason")
            case _:
                assert_never(self.status)
        return self


@dataclass(frozen=True, slots=True)
class ReferenceScan:
    """Typed return value carries preserved references and an explicit coverage state."""

    inventory: ImageInventory
    references: tuple[ImageReference, ...]


def scan_image_references(page: pymupdf.Page, producer: ExtractionProducer) -> ReferenceScan:
    """Image inventory limitations never discard independently extracted native text."""
    if (
        producer.library_version != QUALIFIED_PYMUPDF_VERSION
        or producer.library_wrapper_sha256 != QUALIFIED_PYMUPDF_WRAPPER_SHA256
    ):
        return ReferenceScan(
            ImageInventory(
                status="unavailable",
                reason=f"Unqualified PyMuPDF version/wrapper: {producer.library_version}/"
                + producer.library_wrapper_sha256,
            ),
            (),
        )
    try:
        references = image_references(page)
    except ImageReferenceInventoryError as error:
        return ReferenceScan(
            ImageInventory(
                status="unavailable",
                occurrence_count=error.occurrence_count,
                occurrence_count_basis="native-occurrence-inventory",
                reason=str(error),
            ),
            (),
        )
    except (ValueError, RuntimeError, TypeError) as error:
        return ReferenceScan(
            ImageInventory(status="unavailable", reason=f"{type(error).__name__}: {error}"), ()
        )
    counts: Counter[ResolutionStatus] = Counter(row.resolution_status for row in references)
    return ReferenceScan(
        ImageInventory(
            status="enumerated",
            occurrence_count=len(references),
            occurrence_count_basis="native-occurrence-inventory",
            reference_status_counts=tuple(
                ReferenceStatusCount(status=status, count=count)
                for status, count in sorted(counts.items())
            ),
        ),
        references,
    )
