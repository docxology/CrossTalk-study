"""Saved asset custody and unresolved resource references at the page-record boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

from pydantic import Field, field_validator, model_validator

from crosstalk.image_reference_records import (
    MAX_PIXELS,
    BBox,
    ImageReference,
    ImageReferenceError,
    Record,
)

type ImageStatus = Literal[
    "saved", "small-skipped", "inline-unavailable", "oversized-skipped", "reference-unavailable"
]


class ImageOccurrence(Record):
    """A placement retains reference uncertainty without inventing an encoded asset."""

    bbox: BBox
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    xref: int = Field(ge=0)
    status: ImageStatus
    sha256: str | None = None
    path: str | None = None
    reference: ImageReference | None = None

    @field_validator("path")
    @classmethod
    def contained_image_path(cls, value: str | None) -> str | None:
        """Admit only content-addressed images inside the generated image pool."""
        if value is not None and (
            not value.startswith("data/processed/images/")
            or len(Path(value).parts) != 4
            or ".." in Path(value).parts
        ):
            raise ImageReferenceError("Image path must remain inside data/processed/images")
        return value

    @model_validator(mode="after")
    def reference_consistency(self) -> ImageOccurrence:
        """Legacy fields cannot override the explicit version-3 resource evidence."""
        reference = self.reference
        if reference is None:
            return self
        if (self.bbox, self.width, self.height, self.xref) != (
            reference.bbox,
            reference.width,
            reference.height,
            reference.resolved_xref or 0,
        ):
            raise ImageReferenceError("Image occurrence differs from its reference evidence")
        if self.status == "saved":
            if (
                reference.resolution_status != "resolved-xobject"
                or self.path is None
                or self.sha256 is None
                or Path(self.path).stem != self.sha256
            ):
                raise ImageReferenceError(
                    "Saved asset requires a resolved content-addressed reference"
                )
        elif self.path is not None or self.sha256 is not None:
            raise ImageReferenceError("Unsaved occurrence cannot carry an encoded asset identity")
        _status_consistency(self, reference)
        return self


def _status_consistency(image: ImageOccurrence, reference: ImageReference) -> None:
    """Size policy and resolution outcomes cannot silently create saved or inline evidence."""
    match image.status:
        case "saved":
            if min(image.width, image.height) < 24 or image.width * image.height > MAX_PIXELS:
                raise ImageReferenceError("Saved asset violates image allocation or size policy")
        case "small-skipped":
            if min(image.width, image.height) >= 24:
                raise ImageReferenceError("Small-image status disagrees with dimensions")
        case "oversized-skipped":
            if image.width * image.height <= MAX_PIXELS:
                raise ImageReferenceError("Oversized-image status disagrees with dimensions")
        case "reference-unavailable":
            if reference.resolution_status == "resolved-xobject":
                raise ImageReferenceError("Resolved reference cannot be marked unavailable")
        case "inline-unavailable":
            raise ImageReferenceError("A missing resource candidate does not prove an inline image")
        case _:
            assert_never(image.status)
