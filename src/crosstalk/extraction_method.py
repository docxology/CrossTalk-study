"""Bind current extraction semantics and the qualified native library to page records."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final, Literal, Protocol

import pymupdf
from pydantic import Field, TypeAdapter

from crosstalk.extraction_runtime import runtime_identity
from crosstalk.image_reference_records import Record
from crosstalk.models import AcquisitionError, Digest

QUALIFIED_PYMUPDF_VERSION: Final = "1.28.2"
QUALIFIED_PYMUPDF_WRAPPER_SHA256: Final = (
    "e8cdb45ed0afa21f919cec30e69b7b572c3db7bc80d203e4e07e4c7ea2b19cce"
)
TEXT: Final = TypeAdapter(str)
EXTRACTION_IMPLEMENTATION_FILES: Final = (
    "__init__.py",
    "acquisition_lock.py",
    "acquisition_ledger.py",
    "acquisition_records.py",
    "extraction_method.py",
    "extraction_runtime.py",
    "records.py",
    "extract.py",
    "extract_images.py",
    "extraction_cache.py",
    "pdf_adapter.py",
    "image_occurrences.py",
    "image_reference_records.py",
    "image_references.py",
    "image_inventory.py",
    "locator_storage.py",
    "locator_records.py",
    "models.py",
    "publisher_records.py",
    "source_inventory.py",
    "visual_outputs.py",
)


class ExtractionProducer(Record):
    """An observed library version and exact local implementation, never a cache self-claim."""

    method: Literal["native-text-resource-reference-v3"] = "native-text-resource-reference-v3"
    library: Literal["PyMuPDF"] = "PyMuPDF"
    library_version: str
    library_wrapper_sha256: Digest
    library_distribution_sha256: Digest
    library_distribution_files: int = Field(ge=1, le=1000)
    library_distribution_bytes: int = Field(ge=1, le=100_000_000)
    implementation_sha256: Digest


class PageMethodInput(Protocol):
    """A narrow readonly shape avoids importing page models into their own producer model."""

    @property
    def extractor_version(self) -> str:
        """Expose the declared native-page method version."""
        ...

    @property
    def producer(self) -> ExtractionProducer | None:
        """Expose optional legacy or explicit current producer custody."""
        ...


def current_extraction_producer() -> ExtractionProducer:
    """Hash the actual bounded regular dependency files used to produce native records."""
    digest = hashlib.sha256()
    for name in EXTRACTION_IMPLEMENTATION_FILES:
        path = Path(__file__).with_name(name)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise AcquisitionError("extraction implementation is missing, aliased or oversized")
        raw = path.read_bytes()
        digest.update(
            name.encode()
            + b"\0"
            + str(len(raw)).encode()
            + b"\0"
            + hashlib.sha256(raw).digest()
            + b"\0"
        )
    wrapper = Path(TEXT.validate_python(getattr(pymupdf, "__file__")))  # noqa: B009
    if wrapper.is_symlink() or not wrapper.is_file() or wrapper.stat().st_size > 5_000_000:
        raise AcquisitionError("native library wrapper is missing, aliased or oversized")
    version = TEXT.validate_python(getattr(pymupdf, "VersionBind"))  # noqa: B009
    runtime = runtime_identity(wrapper.parent.parent, version)
    return ExtractionProducer(
        library_version=version,
        library_wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        library_distribution_sha256=runtime.sha256,
        library_distribution_files=len(runtime.files),
        library_distribution_bytes=runtime.byte_count,
        implementation_sha256=digest.hexdigest(),
    )


def page_method_current(page: PageMethodInput, producer: ExtractionProducer) -> bool:
    """Legacy records remain readable but cannot authorize current extraction consumers."""
    return page.extractor_version == "3" and page.producer == producer
