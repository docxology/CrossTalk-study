"""Declared PDF image metadata guards are separate from the rendered target pixel bound."""

from typing import ClassVar, Literal, Self, assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditRecordError(ValueError):
    """Contradictory metadata observations cannot certify rendering admission."""

    def __init__(self, reason: str) -> None:
        """Preserve the typed record-consistency reason for the parsing boundary."""
        self.reason: str = reason
        super().__init__(reason)


class ImageDeclaration(BaseModel):
    """One image dictionary or mask declaration, not a resolved painted image occurrence."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    context: str = Field(min_length=1, max_length=512)
    object_xref: int | None = Field(default=None, gt=0)
    role: Literal["image", "mask"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)


type AuditCode = Literal[
    "source-image-pixel-bound",
    "source-pixel-sum-bound",
    "metadata-work-bound",
    "unsupported-context",
    "nonpositive-dimensions",
    "native-metadata-unproved",
]


class ResourceAudit(BaseModel):
    """Passing declared-dimension guards never certifies a full-process memory bound."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="forbid")
    status: Literal["passed", "policy-refused", "unproved"]
    metadata_nodes: int = Field(ge=0)
    image_declarations: tuple[ImageDeclaration, ...]
    native_inventory_entries: int | None = Field(default=None, ge=0)
    native_declared_pixel_sum: int | None = Field(default=None, ge=0)
    native_max_declared_pixels: int | None = Field(default=None, ge=0)
    conservative_declared_pixel_sum: int = Field(ge=0)
    code: AuditCode | None = None
    detail: str | None = Field(default=None, max_length=1024)
    scope: Literal[
        "PDF image/mask dictionaries and no-digest native metadata; not a process RAM bound"
    ] = "PDF image/mask dictionaries and no-digest native metadata; not a process RAM bound"

    @model_validator(mode="after")
    def status_consistency(self) -> Self:
        """Unknown source coverage cannot be represented as a completed zero-image audit."""
        match self.status:
            case "passed":
                if (
                    self.code is not None
                    or self.detail is not None
                    or self.native_inventory_entries is None
                    or self.native_declared_pixel_sum is None
                    or self.native_max_declared_pixels is None
                ):
                    raise AuditRecordError(
                        "Passed metadata audit requires complete native dimension observation"
                    )
                if (self.native_inventory_entries == 0) != (self.native_declared_pixel_sum == 0):
                    raise AuditRecordError(
                        "Native dimension sums must agree with observed entry absence"
                    )
                if (
                    not self.native_max_declared_pixels
                    <= self.native_declared_pixel_sum
                    <= self.native_inventory_entries * self.native_max_declared_pixels
                ):
                    raise AuditRecordError(
                        "Native dimension maxima and sums disagree with entry counts"
                    )
                if self.conservative_declared_pixel_sum != self.native_declared_pixel_sum + sum(
                    row.width * row.height for row in self.image_declarations
                ):
                    raise AuditRecordError("Passed metadata dimension sums do not reconcile")
            case "policy-refused" | "unproved":
                if self.code is None or self.detail is None:
                    raise AuditRecordError("Refused/unproved audit requires an explicit reason")
            case _:
                assert_never(self.status)
        return self
