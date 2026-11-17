"""Appearance reuse requires original successful manager envelopes and both sealed files."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from .appearance_batch_records import AppearanceArtifact, AppearanceEngine, PriorAppearance
from .appearance_context import appearance_key
from .appearance_records import AppearanceError
from .ocr_files import binding_digest, canonical_digest, checked
from .ocr_records import BoundFile
from .ocr_resume import (
    ManagedExit,
    ManagedResults,
    ManagedUse,
    supervisor_record,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class VerifiedAppearance:
    """Exact reusable bytes from a successful manager-selected record and thumbnail pair."""

    artifact: AppearanceArtifact
    artifact_raw: bytes
    thumbnail_raw: bytes
    run_id: str


def _selection_bindings(use: ManagedUse, results: ManagedResults, engine: AppearanceEngine) -> None:
    """Producer, runtime and original closed selections cannot be supplied by a self-seal."""
    if results.bindings != use.bindings:
        raise AppearanceError("appearance prior manager bindings disagree")
    if (
        use.bindings.runtime != engine.runtime_sha256
        or use.bindings.source != engine.source_selection_sha256
    ):
        raise AppearanceError("appearance prior source/runtime differs from the current producer")
    for selection, digest in (
        (use.source_selection, use.bindings.source),
        (use.input_selection, use.bindings.inputs),
    ):
        if canonical_digest([row.model_dump(mode="json") for row in selection.files]) != digest:
            raise AppearanceError("appearance prior manager selection differs from its binding")
    dependencies = tuple(
        BoundFile(path=row.name, sha256=row.sha256, size=row.size)
        for row in use.input_selection.files
        if row.name.startswith("deps/")
    )
    if binding_digest(dependencies) != engine.dependency_sha256:
        raise AppearanceError(
            "appearance prior dependency closure differs from the current producer"
        )


def verify_appearance_prior(
    inputs: Path, prior: PriorAppearance, engine: AppearanceEngine
) -> VerifiedAppearance:
    """A present PNG, producer self-seal or failed partial cannot supply an accepted prior."""
    declared = prior.record
    prefix = f"prior/{declared.run_id}/"
    for file, name in (
        (declared.results, "results.json"),
        (declared.compute_exit, "compute-exit.json"),
        (declared.run_use, "run-use.json"),
    ):
        if file.path != prefix + name:
            raise AppearanceError("appearance prior manager files do not share their run namespace")
    results = supervisor_record(inputs, declared.results, ManagedResults)
    _ = supervisor_record(inputs, declared.compute_exit, ManagedExit)
    use = supervisor_record(inputs, declared.run_use, ManagedUse)
    if use.run_id != declared.run_id:
        raise AppearanceError("appearance prior actual run id differs from its namespace")
    _selection_bindings(use, results, engine)
    for selected, name in (
        (declared.artifact, declared.output_name),
        (prior.thumbnail, prior.thumbnail_output_name),
    ):
        records = tuple(row for row in results.outputs if row.name == name)
        if (
            len(records) != 1
            or records[0].executable
            or records[0].sha256 != selected.sha256
            or records[0].size != selected.size
            or selected.path != prefix + "outputs/" + name
        ):
            raise AppearanceError(
                "appearance prior pair is absent from the successful manager seal"
            )
    raw = checked(inputs, declared.artifact)
    artifact = AppearanceArtifact.model_validate_json(raw)
    key = appearance_key(artifact.page.source_pdf_sha256, artifact.page.page_index, engine)
    if (
        artifact.engine != engine
        or artifact.cache_key != key
        or declared.output_name != f"pages/{key}.json"
        or prior.thumbnail_output_name != f"pages/{key}.png"
        or prior.thumbnail.sha256 != artifact.page.thumbnail_sha256
    ):
        raise AppearanceError(
            "appearance prior identity, settings or output names are incompatible"
        )
    if not any(
        row.name.startswith("pdf/") and row.sha256 == artifact.page.source_pdf_sha256
        for row in use.input_selection.files
    ):
        raise AppearanceError("appearance prior original PDF is absent from actual selected inputs")
    if prior.thumbnail.size > 4_000_000:
        raise AppearanceError("appearance prior thumbnail exceeds its output byte bound")
    png = checked(inputs, prior.thumbnail)
    with Image.open(io.BytesIO(png)) as image:
        if (
            image.format != "PNG"
            or image.mode != "RGB"
            or image.size != (artifact.page.thumbnail_width, artifact.page.thumbnail_height)
        ):
            raise AppearanceError("appearance prior thumbnail format or dimensions disagree")
        image.verify()
    return VerifiedAppearance(artifact, raw, png, use.run_id)
