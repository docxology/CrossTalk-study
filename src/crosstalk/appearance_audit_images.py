"""Accumulate bounded PDF image/mask declarations without extracting raster payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, NoReturn, assert_never

from pydantic import BaseModel, ConfigDict, TypeAdapter

from .appearance_audit_records import AuditCode, ImageDeclaration, ResourceAudit
from .appearance_records import AppearanceError, AppearanceSettings

if TYPE_CHECKING:
    import pymupdf

    from .appearance_native import PdfNode


class AppearanceAuditError(AppearanceError):
    """Retain policy/missingness evidence without labelling the source PDF corrupt."""

    def __init__(self, audit: ResourceAudit) -> None:
        """Retain the observed metadata independently of the human-readable reason."""
        self.audit: ResourceAudit = audit
        super().__init__(audit.detail or "Image metadata audit refused")


@dataclass(frozen=True, slots=True)
class AuditLocation:
    """Resource ancestry supplies both attributed context and bounded traversal depth."""

    context: str
    depth: int = 0

    def child(self, name: str) -> AuditLocation:
        """Extend attributed resource ancestry without an unbounded context string."""
        return AuditLocation((self.context + "/" + name)[:512], self.depth + 1)


class NativeDimensions(BaseModel):
    """No hash or guessed xref enters this dimension-only native observation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    width: int
    height: int


class AuditState:
    """Mutable traversal builder retains declarations observed before an explicit refusal."""

    def __init__(self, settings: AppearanceSettings) -> None:
        """Start one finite accumulation inside the opened PDF document lifetime."""
        self.settings: AppearanceSettings = settings
        self.nodes: int = 0
        self.images: list[ImageDeclaration] = []
        self.pixel_sum: int = 0
        self.native_count: int | None = None
        self.native_pixels: int | None = None
        self.native_max: int | None = None
        self.active: set[int] = set()
        self.seen: set[int] = set()

    def record(
        self,
        status: Literal["passed", "policy-refused", "unproved"],
        *,
        code: AuditCode | None = None,
        detail: str | None = None,
    ) -> ResourceAudit:
        """Freeze the observations collected before completion or refusal."""
        return ResourceAudit(
            status=status,
            metadata_nodes=self.nodes,
            image_declarations=tuple(self.images),
            native_inventory_entries=self.native_count,
            native_declared_pixel_sum=self.native_pixels,
            native_max_declared_pixels=self.native_max,
            conservative_declared_pixel_sum=self.pixel_sum,
            code=code,
            detail=detail,
        )

    def refuse(self, code: AuditCode, detail: str, *, unproved: bool = False) -> NoReturn:
        """Exit before page paint while retaining partial source metadata."""
        raise AppearanceAuditError(
            self.record(
                "unproved" if unproved else "policy-refused", code=code, detail=detail[:1024]
            )
        )

    def touch(self, where: AuditLocation) -> None:
        """Charge both breadth and depth before descending into a metadata value."""
        self.nodes += 1
        if (
            self.nodes > self.settings.max_metadata_nodes
            or where.depth > self.settings.max_audit_depth
        ):
            self.refuse(
                "metadata-work-bound", "Image metadata exceeds its traversal work/depth policy"
            )

    def entries(self, node: PdfNode) -> tuple[tuple[str, PdfNode], ...]:
        """Bound each native dictionary materialization by the remaining node policy."""
        return tuple(
            (entry.name, entry.node)
            for entry in node.entries(self.settings.max_metadata_nodes - self.nodes)
        )

    def pixels(self, pixels: int) -> None:
        """Apply separate single-object and conservative aggregate dimension policies."""
        self.pixel_sum += pixels
        if pixels > self.settings.max_source_image_pixels:
            self.refuse(
                "source-image-pixel-bound",
                "Declared source image/mask exceeds its per-object pixel policy",
            )
        if self.pixel_sum > self.settings.max_source_pixel_sum:
            self.refuse(
                "source-pixel-sum-bound",
                "Conservative raster sum exceeds policy; resource/native declarations may overlap",
            )

    def image(self, node: PdfNode, where: AuditLocation, *, mask: bool = False) -> None:
        """Observe image/mask dimensions without obtaining any encoded or decoded payload."""
        self.touch(where)
        xref = node.xref()
        if xref is not None and xref in self.active:
            self.refuse(
                "unsupported-context", "Cyclic image/mask metadata is unproved", unproved=True
            )
        if xref is not None and xref in self.seen:
            return
        if node.kind() != "dictionary" or node.get("Subtype").name() != "Image":
            self.refuse(
                "unsupported-context", "A raster context lacks an Image dictionary", unproved=True
            )
        width, height = node.get("Width").integer(), node.get("Height").integer()
        if min(width, height) < 1:
            self.refuse(
                "nonpositive-dimensions",
                "Image dictionary dimensions are nonpositive",
                unproved=True,
            )
        self.images.append(
            ImageDeclaration(
                context=where.context,
                object_xref=xref,
                role="mask" if mask else "image",
                width=width,
                height=height,
            )
        )
        self.pixels(width * height)
        if node.get("F").kind() != "null":
            self.refuse(
                "unsupported-context", "External image stream context is unproved", unproved=True
            )
        if xref is not None:
            self.active.add(xref)
        for key in ("SMask", "Mask"):
            self.mask(node.get(key), where.child(key))
        if xref is not None:
            self.active.remove(xref)
            self.seen.add(xref)

    def mask(self, node: PdfNode, where: AuditLocation) -> None:
        """Read only the supported bounded raster-mask declaration forms."""
        self.touch(where)
        kind = node.kind()
        match kind:
            case "null":
                return
            case "name":
                if node.name() != "None":
                    self.refuse("unsupported-context", "Unknown named raster mask", unproved=True)
            case "array":
                if not where.context.endswith("/Mask") or not all(
                    value.kind() == "integer" for value in node.array(8)
                ):
                    self.refuse(
                        "unsupported-context", "Unproved color-key mask declaration", unproved=True
                    )
            case "dictionary":
                self.image(node, where, mask=True)
            case "integer" | "other":
                self.refuse("unsupported-context", "Unproved raster mask metadata", unproved=True)
            case _:
                assert_never(kind)

    def finish_native(self, page: pymupdf.Page) -> ResourceAudit:
        """Add painted inventory dimensions without hashes, assets or xref guesses."""
        rows = TypeAdapter(tuple[NativeDimensions, ...]).validate_python(
            getattr(page, "get_image_info")(hashes=False, xrefs=False)  # noqa: B009 -- Parse untyped native return.
        )
        self.native_count = len(rows)
        if len(rows) > self.settings.max_metadata_nodes:
            self.refuse(
                "metadata-work-bound", "Native image inventory exceeds its entry-count policy"
            )
        if any(min(row.width, row.height) < 1 for row in rows):
            self.refuse(
                "nonpositive-dimensions",
                "Native inventory dimensions are nonpositive; coverage unproved",
                unproved=True,
            )
        self.native_pixels = sum(row.width * row.height for row in rows)
        self.native_max = max((row.width * row.height for row in rows), default=0)
        for row in rows:
            self.pixels(row.width * row.height)
        return self.record("passed")
