"""One-time closure checks and exact native-page admission for isolated OCR."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, assert_never

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from crosstalk.ocr_files import binding_digest, canonical_digest, checked, verify_selection
from crosstalk.ocr_records import (
    BatchSpec,
    BoundFile,
    Digest,
    EngineBinding,
    NativeVersion,
    OcrError,
    PageBinding,
    Task,
)

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_FILES: Final = (
    "scripts/ocr_compute.py",
    "src/crosstalk/__init__.py",
    "src/crosstalk/ocr_records.py",
    "src/crosstalk/ocr_files.py",
    "src/crosstalk/ocr_source.py",
    "src/crosstalk/ocr_engine.py",
    "src/crosstalk/ocr_resume.py",
    "src/crosstalk/ocr_selection.py",
    "src/crosstalk/ocr_batch.py",
)


class NativeProjection(BaseModel):
    """Read required native provenance while image-reference validation stays upstream."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="ignore")


class NativeProducer(NativeProjection):
    """Preserve explicit v3 implementation/library custody without importing visual modules."""

    method: Literal["native-text-resource-reference-v3"]
    library: Literal["PyMuPDF"]
    library_version: str = Field(min_length=1, max_length=100)
    library_wrapper_sha256: Digest
    library_distribution_sha256: Digest
    library_distribution_files: int = Field(ge=1, le=1000)
    library_distribution_bytes: int = Field(ge=1, le=100_000_000)
    implementation_sha256: Digest


class NativeStatusCount(NativeProjection):
    """Inventory labels remain native observations, not semantic figure classes."""

    status: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class NativeInventory(NativeProjection):
    """A known or unavailable v3 inventory remains explicit in the selected source."""

    status: Literal["enumerated", "unavailable"]
    occurrence_count: int | None = Field(default=None, ge=0)
    occurrence_count_basis: Literal["native-occurrence-inventory"] | None = None
    reference_status_counts: tuple[NativeStatusCount, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def accounting(self) -> NativeInventory:
        """Reject invented absence and contradictory counts without decoding any image."""
        if (self.occurrence_count is None) != (self.occurrence_count_basis is None):
            raise OcrError("v3 native inventory count lacks its observation basis")
        if self.status == "enumerated":
            labels = tuple(row.status for row in self.reference_status_counts)
            if (
                self.occurrence_count is None
                or sum(row.count for row in self.reference_status_counts) != self.occurrence_count
                or len(labels) != len(set(labels))
                or self.reason is not None
            ):
                raise OcrError("v3 native inventory accounting disagrees")
        elif self.reference_status_counts or not self.reason:
            raise OcrError("unavailable v3 inventory requires its explicit limitation")
        return self


class NativePage(NativeProjection):
    """Identity projection of original bytes; fixture provenance remains an explicit variant."""

    issue_id: str
    source_sha256: str
    page_index: int
    extractor_version: NativeVersion
    producer: NativeProducer | None = None
    image_inventory: NativeInventory | None = None
    text: str

    @model_validator(mode="after")
    def version_evidence(self) -> NativePage:
        """Legacy/fixture records cannot be promoted by carrying a v3 version string alone."""
        if self.extractor_version == "3":
            if self.producer is None or self.image_inventory is None:
                raise OcrError("v3 OCR source requires explicit producer and inventory evidence")
        elif self.producer is not None or self.image_inventory is not None:
            raise OcrError(
                "legacy or fixture OCR source cannot carry v3 producer/inventory evidence"
            )
        return self


@dataclass(frozen=True, slots=True)
class PreparedPage:
    """Verified current in-memory PDF and selected native page, without rewriting either."""

    task: Task
    source: PageBinding
    pdf_bytes: bytes
    native_text: str
    native_version: NativeVersion


def engine_binding(source: Path, inputs: Path, spec: BatchSpec) -> EngineBinding:
    """Hash the complete selected engine/model/producer closure once for this run."""
    if spec.model.path != "model/eng.traineddata" or any(
        not item.path.startswith("deps/") for item in spec.dependencies
    ):
        raise OcrError("model and runtime dependencies must use their declared input namespaces")
    if {item.path for item in spec.source_files} != set(SOURCE_FILES):
        raise OcrError("OCR producer source selection is not the complete declared implementation")
    verify_selection(source, spec.source_files)
    verify_selection(inputs, (*spec.dependencies, spec.model))
    return EngineBinding(
        producer_sha256=binding_digest(spec.source_files),
        source_selection_sha256=canonical_digest(
            [
                {
                    "name": item.path,
                    "sha256": item.sha256,
                    "size": item.size,
                    "executable": bool((source / item.path).stat().st_mode & 0o111),
                }
                for item in sorted(spec.source_files, key=lambda value: value.path)
            ]
        ),
        runtime_sha256=spec.runtime_sha256,
        dependency_sha256=binding_digest(spec.dependencies),
        model_sha256=spec.model.sha256,
        settings_sha256=hashlib.sha256(spec.settings.model_dump_json().encode()).hexdigest(),
        pymupdf_version=TypeAdapter(str).validate_python(pymupdf.VersionBind),
        mupdf_version=TypeAdapter(str).validate_python(getattr(pymupdf, "VersionFitz")),
    )


def _native_page(task: Task, raw: bytes) -> NativePage:
    """Parse and independently bind one physical page inside a closed native artifact."""
    lines = raw.splitlines()
    if not 1 <= len(lines) <= 500 or task.page_index >= len(lines):
        raise OcrError("selected native physical page is unavailable or outside bounds")
    native = tuple(NativePage.model_validate_json(line) for line in lines)
    match task.source_kind:
        case "journal-page":
            versions = {"2", "3"}
        case "synthetic-fixture":
            versions = {"synthetic-raster-fixture-1"}
        case _:
            assert_never(task.source_kind)
    observed = {row.extractor_version for row in native}
    if len(observed) != 1 or not observed <= versions:
        raise OcrError("native extractor version disagrees with the explicit page source kind")
    if any(
        row.issue_id != task.issue_id
        or row.source_sha256 != task.pdf.sha256
        or row.page_index != index
        for index, row in enumerate(native)
    ):
        raise OcrError("native artifact identities do not match the selected current PDF")
    if hashlib.sha256(lines[task.page_index]).hexdigest() != task.native_page_sha256:
        raise OcrError("native page differs from its independently selected byte digest")
    return native[task.page_index]


def prepare_pages(inputs: Path, spec: BatchSpec) -> tuple[PreparedPage, ...]:
    """Verify each unique input once and forbid duplicate source pages or aliased declarations."""
    if len(spec.tasks) > spec.settings.maximum_batch_pages:
        raise OcrError("selected OCR pages exceed the explicit finite batch limit")
    files: dict[str, BoundFile] = {}
    for task in spec.tasks:
        if not task.pdf.path.startswith("pdf/") or not task.native.path.startswith("native/"):
            raise OcrError("PDF/native selections must use their declared input namespaces")
        for file in (task.pdf, task.native):
            if file.path in files and files[file.path] != file:
                raise OcrError("one input path has conflicting byte identities")
            files[file.path] = file
    verify_selection(inputs, tuple(files.values()))
    raw = {path: checked(inputs, file) for path, file in files.items()}
    pages: list[PreparedPage] = []
    identities: set[tuple[str, int]] = set()
    for task in spec.tasks:
        identity = task.pdf.sha256, task.page_index
        if identity in identities:
            raise OcrError("duplicate physical source page in the OCR batch")
        identities.add(identity)
        native = _native_page(task, raw[task.native.path])
        pages.append(
            PreparedPage(
                task=task,
                source=PageBinding(
                    issue_id=task.issue_id,
                    source_kind=task.source_kind,
                    pdf_sha256=task.pdf.sha256,
                    native_artifact_sha256=task.native.sha256,
                    native_page_sha256=task.native_page_sha256,
                    page_index=task.page_index,
                ),
                pdf_bytes=raw[task.pdf.path],
                native_text=native.text,
                native_version=native.extractor_version,
            )
        )
    return tuple(pages)


def page_key(page: PageBinding, engine: EngineBinding) -> str:
    """Stable page identity excludes observation time, batch membership and copied host paths."""
    raw = (page.model_dump_json() + "\n" + engine.model_dump_json()).encode()
    return hashlib.sha256(raw).hexdigest()
