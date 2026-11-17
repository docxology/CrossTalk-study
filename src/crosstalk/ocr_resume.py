"""Admit prior OCR only through independently retained successful supervisor records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from crosstalk.ocr_files import binding_digest, canonical_digest, checked
from crosstalk.ocr_records import BoundFile, Digest, OcrError, PageResult, Record

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.ocr_records import EngineBinding, PriorArtifact


class ManagerProjection(BaseModel):
    """Parse required supervisor facts while retaining the raw envelope for seal verification."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True, extra="ignore")


class ManagerBindings(Record):
    """Source, input, runtime and configuration identities from the actual manager."""

    source: Digest
    inputs: Digest
    runtime: Digest
    configuration: Digest


class ManagedOutput(Record):
    """An explicit file selected and sealed after compute was reaped successfully."""

    name: str
    sha256: Digest
    size: int
    executable: bool


class ManagedResults(ManagerProjection):
    """The supervisor result seal binds all selected outputs to its run context."""

    bindings: ManagerBindings
    outputs: tuple[ManagedOutput, ...]


class ManagedExit(ManagerProjection):
    """Failed, interrupted, unreaped and partial executions cannot supply reusable outputs."""

    reaped: Literal[True]
    returncode: Literal[0]
    interrupted: Literal[False]
    state: Literal["process_succeeded"]


class ManagedUse(ManagerProjection):
    """The retained run identity ties its result bindings to one run namespace."""

    run_id: str
    bindings: ManagerBindings
    source_selection: ManagedSelection
    input_selection: ManagedSelection


class ManagedSelection(ManagerProjection):
    """Actual selected file identities retained in the manager's run-use receipt."""

    files: tuple[ManagedOutput, ...]


@dataclass(frozen=True, slots=True)
class VerifiedPrior:
    """A supervisor-sealed previous outcome; page failures remain retryable history."""

    result: PageResult
    run_id: str


def supervisor_record[T: BaseModel](root: Path, file: BoundFile, model: type[T]) -> T:
    """Verify both externally selected bytes and the original manager content envelope."""
    raw = checked(root, file)
    envelope = TypeAdapter(dict[str, JsonValue]).validate_json(raw)
    if set(envelope) != {"payload", "sha256"}:
        raise OcrError("prior supervisor envelope has unexpected fields")
    seal = TypeAdapter(Digest).validate_python(envelope["sha256"])
    if canonical_digest(envelope["payload"]) != seal:
        raise OcrError("prior supervisor envelope content seal disagrees")
    return model.model_validate_json(json.dumps(envelope["payload"]))


def _run_bindings(use: ManagedUse, results: ManagedResults, engine: EngineBinding) -> None:
    """Bind actual manager selections and runtime before considering any OCR artifact."""
    if results.bindings != use.bindings:
        raise OcrError("prior supervisor run identity or source/input/runtime bindings disagree")
    if (
        use.bindings.runtime != engine.runtime_sha256
        or use.bindings.source != engine.source_selection_sha256
    ):
        raise OcrError("prior supervisor runtime/source identity differs from this producer")
    for selected, digest in (
        (use.source_selection, use.bindings.source),
        (use.input_selection, use.bindings.inputs),
    ):
        if canonical_digest([item.model_dump(mode="json") for item in selected.files]) != digest:
            raise OcrError("prior supervisor selected file list disagrees with its binding")


def verify_prior(inputs: Path, prior: PriorArtifact, engine: EngineBinding) -> VerifiedPrior:
    """Reject cache text edits, resealed producer-only artifacts and failed-run partials."""
    prefix = f"prior/{prior.run_id}/"
    for file, name in (
        (prior.results, "results.json"),
        (prior.compute_exit, "compute-exit.json"),
        (prior.run_use, "run-use.json"),
    ):
        if file.path != prefix + name:
            raise OcrError("prior supervisor evidence does not share its reviewed run namespace")
    results = supervisor_record(inputs, prior.results, ManagedResults)
    _ = supervisor_record(inputs, prior.compute_exit, ManagedExit)
    use = supervisor_record(inputs, prior.run_use, ManagedUse)
    if use.run_id != prior.run_id:
        raise OcrError("prior supervisor run identity differs from its reviewed namespace")
    _run_bindings(use, results, engine)
    outputs = tuple(row for row in results.outputs if row.name == prior.output_name)
    if (
        len(outputs) != 1
        or outputs[0].sha256 != prior.artifact.sha256
        or outputs[0].size != prior.artifact.size
        or outputs[0].executable
    ):
        raise OcrError("OCR prior artifact is absent from the successful supervisor output seal")
    if prior.artifact.path != prefix + "outputs/" + prior.output_name:
        raise OcrError("prior artifact pathname is not bound to its reviewed managed output")
    result = PageResult.model_validate_json(checked(inputs, prior.artifact))
    if result.engine != engine:
        raise OcrError("prior OCR engine/model/producer/settings/runtime context is incompatible")
    files = use.input_selection.files
    dependencies = tuple(
        BoundFile(path=row.name, sha256=row.sha256, size=row.size)
        for row in files
        if row.name.startswith("deps/")
    )
    if (
        binding_digest(dependencies) != engine.dependency_sha256
        or not any(
            row.name == "model/eng.traineddata" and row.sha256 == engine.model_sha256
            for row in files
        )
        or not any(
            row.name.startswith("pdf/") and row.sha256 == result.source.pdf_sha256 for row in files
        )
        or not any(
            row.name.startswith("native/") and row.sha256 == result.source.native_artifact_sha256
            for row in files
        )
    ):
        raise OcrError("prior OCR result disagrees with its actual selected input closure")
    return VerifiedPrior(result, prior.run_id)
