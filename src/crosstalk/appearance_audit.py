"""Conservative resource coverage gate before native page paint; never resolves image xrefs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, assert_never

from pydantic import TypeAdapter, ValidationError
from pymupdf.mupdf import FzErrorBase

from .appearance_audit_images import AppearanceAuditError, AuditLocation, AuditState
from .appearance_native import NativeMetadataError, PdfNode, page_object

if TYPE_CHECKING:
    import pymupdf

    from .appearance_audit_records import ResourceAudit
    from .appearance_records import AppearanceSettings

type ResourceKey = Literal[
    "XObject", "ExtGState", "Pattern", "Font", "ColorSpace", "Properties", "Shading", "ProcSet"
]
KEY: Final = TypeAdapter(ResourceKey)
SUBTYPE: Final = TypeAdapter(Literal["Image", "Form"])


def _xobject(state: AuditState, node: PdfNode, where: AuditLocation) -> None:
    state.touch(where)
    subtype = SUBTYPE.validate_python(node.get("Subtype").name())
    match subtype:
        case "Image":
            state.image(node, where)
        case "Form":
            xref = node.xref()
            if xref is not None and xref in state.active:
                state.refuse(
                    "unsupported-context", "Cyclic form resources are unproved", unproved=True
                )
            if xref is not None:
                state.active.add(xref)
            _resources(state, node.get("Resources"), where.child("Resources"))
            if xref is not None:
                state.active.remove(xref)
        case _:
            assert_never(subtype)


def _table(state: AuditState, table: PdfNode, where: AuditLocation) -> None:
    key = KEY.validate_python(where.context.rsplit("/", 1)[-1])
    for name, child in state.entries(table):
        location = where.child(name)
        state.touch(location)
        match key:
            case "XObject":
                _xobject(state, child, location)
            case "ExtGState":
                softmask = child.get("SMask")
                if softmask.kind() != "null" and not (
                    softmask.kind() == "name" and softmask.name() == "None"
                ):
                    state.refuse(
                        "unsupported-context",
                        "Transparency-group soft-mask coverage is unproved",
                        unproved=True,
                    )
            case "Pattern":
                if child.get("PatternType").integer() != 2:
                    state.refuse(
                        "unsupported-context",
                        "Tiling-pattern image coverage is unproved",
                        unproved=True,
                    )
            case "Font":
                if child.get("Subtype").name() == "Type3":
                    state.refuse(
                        "unsupported-context",
                        "Type3 glyph image coverage is unproved",
                        unproved=True,
                    )
            case "ColorSpace" | "Properties" | "Shading" | "ProcSet":
                return
            case _:
                assert_never(key)


def _resources(state: AuditState, node: PdfNode, where: AuditLocation) -> None:
    state.touch(where)
    if node.kind() == "null":
        return
    for key, table in state.entries(node):
        parsed = KEY.validate_python(key)
        match parsed:
            case "ColorSpace" | "Properties" | "Shading" | "ProcSet":
                continue
            case "XObject" | "ExtGState" | "Pattern" | "Font":
                _table(state, table, where.child(key))
            case _:
                assert_never(parsed)


def _annotations(state: AuditState, page: PdfNode) -> None:
    annotations = page.get("Annots")
    if annotations.kind() == "null":
        return
    for annotation in annotations.array(state.settings.max_metadata_nodes):
        state.touch(AuditLocation("Annots", 1))
        if annotation.get("Subtype").name() != "Link" or annotation.get("AP").kind() != "null":
            state.refuse(
                "unsupported-context",
                "Annotation appearance image coverage is unproved",
                unproved=True,
            )


def audit_page(
    document: pymupdf.Document, page: pymupdf.Page, settings: AppearanceSettings
) -> ResourceAudit:
    """Observe declared dimensions only; guards do not certify full-process RAM use."""
    state = AuditState(settings)
    try:
        current = page_object(document, page)
        if settings.include_annotations:
            _annotations(state, current)
        parents: set[int] = set()
        for depth in range(settings.max_audit_depth):
            state.touch(AuditLocation("Page/Parent", depth))
            resources = current.get("Resources")
            if resources.kind() != "null":
                _resources(state, resources, AuditLocation("Resources"))
                return state.finish_native(page)
            parent = current.get("Parent")
            if parent.kind() == "null":
                return state.finish_native(page)
            xref = parent.xref()
            if xref is not None and xref in parents:
                state.refuse(
                    "unsupported-context", "Page resource inheritance is cyclic", unproved=True
                )
            if xref is not None:
                parents.add(xref)
            current = parent
        state.refuse("metadata-work-bound", "Page resource inheritance exceeds its depth policy")
    except AppearanceAuditError:
        raise
    except (NativeMetadataError, FzErrorBase, ValidationError, TypeError, RuntimeError) as error:
        state.refuse(
            "native-metadata-unproved",
            f"Native image metadata is unproved: {type(error).__name__}",
            unproved=True,
        )
