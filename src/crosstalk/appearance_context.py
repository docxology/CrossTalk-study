"""Bind actual selected appearance code, dependencies and render settings once per run."""

from __future__ import annotations

import hashlib
import platform
from typing import TYPE_CHECKING, Final

import pymupdf
from PIL import __version__ as pillow_version
from pydantic import TypeAdapter

from .appearance_batch_records import AppearanceBatchSpec, AppearanceEngine
from .appearance_records import AntiAliasState, AppearanceError
from .ocr_files import binding_digest, canonical_digest, verify_selection

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_FILES: Final = (
    "scripts/page_appearance_compute.py",
    "src/crosstalk/__init__.py",
    "src/crosstalk/ocr_records.py",
    "src/crosstalk/ocr_files.py",
    "src/crosstalk/ocr_resume.py",
    "src/crosstalk/appearance_records.py",
    "src/crosstalk/appearance_pixels.py",
    "src/crosstalk/appearance_render.py",
    "src/crosstalk/appearance_batch_records.py",
    "src/crosstalk/appearance_context.py",
    "src/crosstalk/appearance_prior.py",
    "src/crosstalk/appearance_batch.py",
    "src/crosstalk/appearance_native.py",
    "src/crosstalk/appearance_audit_records.py",
    "src/crosstalk/appearance_audit_images.py",
    "src/crosstalk/appearance_audit.py",
)


def engine_binding(source: Path, inputs: Path, spec: AppearanceBatchSpec) -> AppearanceEngine:
    """Observe the closed actual source/runtime selection; no model or native artifact is used."""
    if any(not item.path.startswith("deps/") for item in spec.dependencies):
        raise AppearanceError("appearance dependencies must use the declared selected namespace")
    if len(spec.source_files) != len(SOURCE_FILES) or {
        item.path for item in spec.source_files
    } != set(SOURCE_FILES):
        raise AppearanceError("appearance producer source selection is incomplete or unexpected")
    verify_selection(source, spec.source_files)
    verify_selection(inputs, spec.dependencies)
    return AppearanceEngine(
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
        settings_sha256=hashlib.sha256(spec.settings.model_dump_json().encode()).hexdigest(),
        pymupdf_version=TypeAdapter(str).validate_python(pymupdf.VersionBind),
        mupdf_version=TypeAdapter(str).validate_python(
            getattr(pymupdf, "VersionFitz"),  # noqa: B009 -- Native version boundary.
        ),
        pillow_version=pillow_version,
        python_version=platform.python_version(),
        antialias=AntiAliasState.model_validate(pymupdf.TOOLS.show_aa_level()),
    )


def appearance_key(pdf_sha256: str, page_index: int, engine: AppearanceEngine) -> str:
    """Individual appearance identity excludes sibling selections and native image metadata."""
    return canonical_digest(
        {
            "pdf_sha256": pdf_sha256,
            "page_index": page_index,
            "engine": engine.model_dump(mode="json"),
        }
    )
