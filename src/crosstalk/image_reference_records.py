"""Proposed immutable image-reference evidence; no legacy xref is silently promoted."""

from __future__ import annotations

from typing import ClassVar, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator

type BBox = tuple[float, float, float, float]
type Transform = tuple[float, float, float, float, float, float]
MAX_PIXELS: Final = 100_000_000
TOLERANCE_POINTS: Final = 0.0001
type PositionStatus = Literal[
    "independent-direct-resource",
    "nested-context-unproved",
    "duplicate-resource-name",
    "dead-or-unavailable",
    "oversized-resource",
    "coordinate-frame-unproved",
]
type ResolutionStatus = Literal[
    "resolved-xobject",
    "ambiguous-reference",
    "unresolved-reference",
    "unclassified-reference",
    "oversized-occurrence",
]


class ImageReferenceError(ValueError):
    """A contradictory native reference is refused rather than repaired or guessed."""


class ImageReferenceInventoryError(ImageReferenceError):
    """Retain a known native occurrence count when later resource resolution is refused."""

    def __init__(self, reason: str, occurrence_count: int) -> None:
        """The count is attributed to successful native enumeration, not resolved coverage."""
        self.occurrence_count: int = occurrence_count
        super().__init__(reason)


def bbox_matches(first: BBox, second: BBox) -> bool:
    """A declared small tolerance accommodates measured native coordinate rounding only."""
    return all(abs(a - b) <= TOLERANCE_POINTS for a, b in zip(first, second, strict=True))


class Record(BaseModel):
    """Finite frozen evidence belongs to an explicit method, not an inferred semantic image."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class ResourceEvidence(Record):
    """An actual resource identity, including owner and separate uncomposited mask metadata."""

    xref: int = Field(gt=0)
    name: str
    referencer_xref: int = Field(ge=0)
    smask_xref: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bbox: BBox | None
    position_status: PositionStatus
    resource_name_count: int = Field(ge=1)

    @model_validator(mode="after")
    def position_consistency(self) -> ResourceEvidence:
        """Parsed evidence cannot promote an unproved owner/name/rectangle into a position."""
        if self.position_status == "independent-direct-resource":
            if self.referencer_xref != 0 or self.resource_name_count != 1 or self.bbox is None:
                raise ImageReferenceError(
                    "independent position requires direct unique-name context"
                )
            left, top, right, bottom = self.bbox
            if right <= left or bottom <= top:
                raise ImageReferenceError("independent position requires positive rectangle area")
        elif self.bbox is not None:
            raise ImageReferenceError("unproved resource position cannot carry a proved rectangle")
        return self


class ImageReference(Record):
    """A source occurrence retains uncertainty without receiving an invented saved asset."""

    occurrence_index: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bbox: BBox
    transform: Transform | None = None
    reported_xref: int | None = Field(default=None, ge=0)
    reported_xref_basis: Literal["not-requested", "present-in-library-metadata"]
    resolved_xref: int | None = Field(default=None, gt=0)
    candidate_xrefs: tuple[int, ...]
    candidates: tuple[ResourceEvidence, ...]
    coincident_occurrence_count: int = Field(ge=1)
    resolution_status: ResolutionStatus
    resolved_resource_name: str | None = None
    resolved_referencer_xref: int | None = None
    resolved_smask_xref: int | None = None
    method: Literal["direct-resource-name-position-dimensions-v3"] = (
        "direct-resource-name-position-dimensions-v3"
    )

    @model_validator(mode="after")
    def reference_consistency(self) -> ImageReference:
        """Parsed candidate facts and status must agree before any live-source revalidation."""
        if (self.reported_xref is None) != (self.reported_xref_basis == "not-requested"):
            raise ImageReferenceError(
                "reported xref basis disagrees with the preserved observation"
            )
        if self.candidate_xrefs != tuple(sorted({row.xref for row in self.candidates})):
            raise ImageReferenceError(
                "candidate xref set disagrees with retained resource evidence"
            )
        for candidate in self.candidates:
            if (candidate.width, candidate.height) != (self.width, self.height):
                raise ImageReferenceError("candidate dimensions differ from the occurrence")
            if candidate.bbox is not None and not bbox_matches(candidate.bbox, self.bbox):
                raise ImageReferenceError("candidate position differs from the occurrence")
        if self.resolution_status != "resolved-xobject" and any(
            value is not None
            for value in (
                self.resolved_xref,
                self.resolved_resource_name,
                self.resolved_referencer_xref,
                self.resolved_smask_xref,
            )
        ):
            raise ImageReferenceError(
                "unresolved reference cannot carry resolved identity metadata"
            )
        _resolution_consistency(self)
        return self


def _resolved_consistency(reference: ImageReference) -> None:
    """One matching resource cannot resolve multiple indistinguishable occurrences."""
    if len(reference.candidates) != 1 or reference.coincident_occurrence_count != 1:
        raise ImageReferenceError("resolved image requires one resource and occurrence context")
    candidate = reference.candidates[0]
    if (
        candidate.position_status != "independent-direct-resource"
        or candidate.bbox is None
        or reference.resolved_xref != candidate.xref
        or reference.resolved_resource_name != candidate.name
        or reference.resolved_referencer_xref != candidate.referencer_xref
        or reference.resolved_smask_xref != candidate.smask_xref
    ):
        raise ImageReferenceError("resolved reference lacks matching independent resource evidence")


def _resolution_consistency(reference: ImageReference) -> None:
    """Status cannot discard possible references or assert an unsupported result."""
    match reference.resolution_status:
        case "resolved-xobject":
            _resolved_consistency(reference)
        case "ambiguous-reference":
            if not reference.candidates or (
                len(reference.candidates) < 2 and reference.coincident_occurrence_count < 2
            ):
                raise ImageReferenceError("ambiguous status lacks multiple possible contexts")
        case "unresolved-reference":
            if (
                len(reference.candidates) != 1
                or reference.coincident_occurrence_count != 1
                or reference.candidates[0].position_status == "independent-direct-resource"
            ):
                raise ImageReferenceError("unresolved status disagrees with its possible context")
        case "unclassified-reference":
            if reference.candidates:
                raise ImageReferenceError("unclassified status cannot discard possible references")
        case "oversized-occurrence":
            if reference.width * reference.height <= MAX_PIXELS:
                raise ImageReferenceError("oversized status disagrees with occurrence dimensions")
        case _:
            assert_never(reference.resolution_status)
