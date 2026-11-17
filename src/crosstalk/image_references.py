"""Conservative proposed provider: digest-only xref mappings are never authoritative."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, ClassVar, Final, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .image_reference_records import (
    MAX_PIXELS,
    BBox,
    ImageReference,
    ImageReferenceError,
    ImageReferenceInventoryError,
    ResourceEvidence,
    Transform,
    bbox_matches,
)

if TYPE_CHECKING:
    import pymupdf

MAX_REFERENCES: Final = 10_000
MAX_RESOURCE_REPORTS: Final = 128
MAX_REFERENCE_COMPARISONS: Final = 1_000_000
type ResourceRow = tuple[int, int, int, int, int, str, str, str, str, int]
RESOURCES: Final = TypeAdapter(tuple[ResourceRow, ...])


class NativeOccurrence(BaseModel):
    """Preserve source geometry without requesting a native raster digest/xref lookup."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="ignore", allow_inf_nan=False
    )
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    bbox: BBox
    transform: Transform | None = None
    xref: int | None = Field(default=None, ge=0)


class NativeBox(BaseModel):
    """Read numeric resource position without assuming a positive or painted rectangle."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, from_attributes=True, allow_inf_nan=False
    )
    x0: float
    y0: float
    x1: float
    y1: float


class NativeFrame(BaseModel):
    """Unsupported cropped/rotated frames cannot create a coincidentally shifted match."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)
    mediabox: NativeBox
    cropbox: NativeBox
    rotation: int


OCCURRENCES: Final = TypeAdapter(tuple[NativeOccurrence, ...])


class ResourceValues(TypedDict):
    """Exact keyword shape at the native-row to evidence-record boundary."""

    xref: int
    name: str
    referencer_xref: int
    smask_xref: int
    width: int
    height: int
    resource_name_count: int


class ReferenceValues(TypedDict):
    """Shared immutable occurrence fields across explicit resolution outcomes."""

    occurrence_index: int
    width: int
    height: int
    bbox: BBox
    transform: Transform | None
    reported_xref: int | None
    reported_xref_basis: Literal["not-requested", "present-in-library-metadata"]
    candidate_xrefs: tuple[int, ...]
    candidates: tuple[ResourceEvidence, ...]
    coincident_occurrence_count: int


def _resource(
    page: pymupdf.Page,
    row: ResourceRow,
    names: Counter[str],
    *,
    frame_proved: bool,
) -> ResourceEvidence:
    """Use only the installed direct-resource, no-transform native reporter branch."""
    xref, mask, width, height, _, _, _, name, _, owner = row
    evidence: ResourceValues = {
        "xref": xref,
        "name": name,
        "referencer_xref": owner,
        "smask_xref": mask,
        "width": width,
        "height": height,
        "resource_name_count": names[name],
    }
    if width * height > MAX_PIXELS:
        return ResourceEvidence(**evidence, bbox=None, position_status="oversized-resource")
    if not frame_proved:
        return ResourceEvidence(**evidence, bbox=None, position_status="coordinate-frame-unproved")
    if owner != 0:
        return ResourceEvidence(**evidence, bbox=None, position_status="nested-context-unproved")
    if names[name] != 1:
        return ResourceEvidence(**evidence, bbox=None, position_status="duplicate-resource-name")
    try:
        box = NativeBox.model_validate(
            getattr(page, "get_image_bbox")(row, transform=False)  # noqa: B009 -- Typed native boundary.
        )
    except (ValueError, RuntimeError, TypeError):
        box = None
    if box is None or box.x1 <= box.x0 or box.y1 <= box.y0:
        return ResourceEvidence(**evidence, bbox=None, position_status="dead-or-unavailable")
    bbox = box.x0, box.y0, box.x1, box.y1
    return ResourceEvidence(**evidence, bbox=bbox, position_status="independent-direct-resource")


def _reference(
    index: int,
    occurrence: NativeOccurrence,
    resources: tuple[ResourceEvidence, ...],
    coincident_count: int,
) -> ImageReference:
    """Any unproved possible context prevents promotion of a seemingly matching resource."""
    candidates = tuple(
        row
        for row in resources
        if (row.width, row.height) == (occurrence.width, occurrence.height)
        and (row.bbox is None or bbox_matches(row.bbox, occurrence.bbox))
    )
    values: ReferenceValues = {
        "occurrence_index": index,
        "width": occurrence.width,
        "height": occurrence.height,
        "bbox": occurrence.bbox,
        "transform": occurrence.transform,
        "reported_xref": occurrence.xref,
        "reported_xref_basis": "not-requested"
        if occurrence.xref is None
        else "present-in-library-metadata",
        "candidate_xrefs": tuple(sorted({row.xref for row in candidates})),
        "candidates": candidates,
        "coincident_occurrence_count": coincident_count,
    }
    if occurrence.width * occurrence.height > MAX_PIXELS:
        return ImageReference(**values, resolution_status="oversized-occurrence")
    if candidates and coincident_count > 1:
        return ImageReference(**values, resolution_status="ambiguous-reference")
    if len(candidates) == 1 and candidates[0].position_status == "independent-direct-resource":
        row = candidates[0]
        return ImageReference(
            **values,
            resolution_status="resolved-xobject",
            resolved_xref=row.xref,
            resolved_resource_name=row.name,
            resolved_referencer_xref=row.referencer_xref,
            resolved_smask_xref=row.smask_xref,
        )
    if len(candidates) > 1:
        return ImageReference(**values, resolution_status="ambiguous-reference")
    if candidates:
        return ImageReference(**values, resolution_status="unresolved-reference")
    return ImageReference(**values, resolution_status="unclassified-reference")


def image_references(page: pymupdf.Page) -> tuple[ImageReference, ...]:
    """One proposed seam for extraction and native revalidation; no image payload is saved here."""
    occurrences = OCCURRENCES.validate_python(
        getattr(page, "get_image_info")(hashes=False, xrefs=False)  # noqa: B009 -- Typed native boundary.
    )
    try:
        return _resolve_references(page, occurrences)
    except (ValueError, RuntimeError, TypeError) as error:
        raise ImageReferenceInventoryError(
            f"{type(error).__name__}: {error}", len(occurrences)
        ) from error


def _resolve_references(
    page: pymupdf.Page, occurrences: tuple[NativeOccurrence, ...]
) -> tuple[ImageReference, ...]:
    """Resolve only inside the explicit comparison/native-report work bounds."""
    if any(min(row.width, row.height) < 1 for row in occurrences):
        raise ImageReferenceError(
            "native occurrence inventory has nonpositive intrinsic dimensions; references unproved"
        )
    rows = RESOURCES.validate_python(
        getattr(page, "get_images")(full=True)  # noqa: B009 -- Typed native boundary.
    )
    if len(occurrences) > MAX_REFERENCES or len(rows) > MAX_REFERENCES:
        raise ImageReferenceError("native image reference inventory exceeds its 10,000-row bound")
    if (
        len(rows) > MAX_RESOURCE_REPORTS
        or len(occurrences) * (len(occurrences) + len(rows)) > MAX_REFERENCE_COMPARISONS
    ):
        raise ImageReferenceError(
            "reference work bound exceeded: at most128 resource reports and1,000,000 comparisons"
        )
    frame = NativeFrame.model_validate(page)
    media, crop = frame.mediabox, frame.cropbox
    frame_proved = (
        frame.rotation == 0
        and media.x0 == 0
        and media.y0 == 0
        and (media.x0, media.y0, media.x1, media.y1) == (crop.x0, crop.y0, crop.x1, crop.y1)
    )
    names = Counter(row[7] for row in rows)
    resources = tuple(_resource(page, row, names, frame_proved=frame_proved) for row in rows)
    return tuple(
        _reference(
            index,
            occurrence,
            resources,
            sum(
                (other.width, other.height) == (occurrence.width, occurrence.height)
                and bbox_matches(other.bbox, occurrence.bbox)
                for other in occurrences
            ),
        )
        for index, occurrence in enumerate(occurrences)
    )
