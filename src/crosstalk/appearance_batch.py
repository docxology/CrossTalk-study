"""Finite whole-page appearance producer; genuine isolation is the supervisor's responsibility."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from .appearance_audit_images import AppearanceAuditError
from .appearance_batch_records import (
    AppearanceArtifact,
    AppearanceBatchReport,
    AppearanceBatchSpec,
    AppearanceEngine,
    AppearanceOutcome,
    AppearanceTask,
)
from .appearance_context import appearance_key, engine_binding
from .appearance_prior import VerifiedAppearance, verify_appearance_prior
from .appearance_records import AppearanceError
from .appearance_render import render_pdf_bytes
from .ocr_files import (
    MAX_SELECTION,
    checked,
    publish,
    publish_record,
    read_bytes,
    verify_selection,
)
from .ocr_records import BoundFile

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def input_files(spec: AppearanceBatchSpec) -> tuple[BoundFile, ...]:
    """Deduplicate exact declared paths while refusing conflicting source identities."""
    files: dict[str, BoundFile] = {}
    declared = [*spec.dependencies, *(task.pdf for task in spec.tasks)]
    for prior in spec.prior:
        previous = prior.record
        declared.extend(
            (
                previous.results,
                previous.compute_exit,
                previous.run_use,
                previous.artifact,
                prior.thumbnail,
            )
        )
    for file in declared:
        if file.path in files and files[file.path] != file:
            raise AppearanceError("appearance selected input path has conflicting byte identities")
        files[file.path] = file
    return tuple(sorted(files.values(), key=lambda file: file.path))


def prior_cache(history: tuple[VerifiedAppearance, ...]) -> Mapping[str, VerifiedAppearance]:
    """Contradictory accepted bytes cannot be silently chosen by run order."""
    cache: dict[str, VerifiedAppearance] = {}
    for prior in history:
        key = prior.artifact.cache_key
        previous = cache.get(key)
        if previous is not None and (
            previous.artifact_raw != prior.artifact_raw
            or previous.thumbnail_raw != prior.thumbnail_raw
        ):
            raise AppearanceError("conflicting manager-sealed appearances need reconciliation")
        cache[key] = prior
    return cache


@dataclass(frozen=True, slots=True)
class BatchContext:
    """Shared render configuration and destination stay constant across selected pages."""

    spec: AppearanceBatchSpec
    engine: AppearanceEngine
    outputs: Path
    originals: Mapping[str, bytes]


def _page(
    task: AppearanceTask, context: BatchContext, previous: VerifiedAppearance | None
) -> AppearanceOutcome:
    """Render errors retain page missingness; output-publication failures stop the batch."""
    key = appearance_key(task.pdf.sha256, task.page_index, context.engine)
    if previous is None:
        try:
            result = render_pdf_bytes(
                context.originals[task.pdf.path], task.page_index, context.spec.settings
            )
            artifact = AppearanceArtifact(cache_key=key, engine=context.engine, page=result.record)
        except AppearanceAuditError as error:
            return AppearanceOutcome(
                task=task, status="policy-refused", reason=str(error), resource_audit=error.audit
            )
        except (AppearanceError, ValidationError) as error:
            return AppearanceOutcome(task=task, status="render-error", reason=str(error))
        artifact_raw = (artifact.model_dump_json() + "\n").encode()
        png = result.thumbnail_png
    else:
        artifact_raw, png = previous.artifact_raw, previous.thumbnail_raw
        artifact = previous.artifact
    if (
        artifact.page.source_pdf_sha256 != task.pdf.sha256
        or artifact.page.page_index != task.page_index
    ):
        raise AppearanceError("cached appearance differs from the independently selected PDF/page")
    record_name, png_name = f"pages/{key}.json", f"pages/{key}.png"
    publish(context.outputs / record_name, artifact_raw)
    publish(context.outputs / png_name, png)
    return AppearanceOutcome(
        task=task,
        status="appearance-produced",
        record=BoundFile(
            path=record_name,
            sha256=hashlib.sha256(artifact_raw).hexdigest(),
            size=len(artifact_raw),
        ),
        thumbnail=BoundFile(path=png_name, sha256=hashlib.sha256(png).hexdigest(), size=len(png)),
        reused=previous is not None,
        prior_run_id=previous.run_id if previous else None,
    )


def run_batch(
    source: Path, inputs: Path, outputs: Path, runtime_sha256: str
) -> AppearanceBatchReport:
    """Consume closed immutable selections and publish only new private derivative files."""
    raw_spec = read_bytes(inputs / "batch.json", 5_000_000)
    spec = AppearanceBatchSpec.model_validate_json(raw_spec)
    if spec.runtime_sha256 != runtime_sha256:
        raise AppearanceError(
            "appearance actual supervisor runtime differs from the reviewed batch"
        )
    if len(spec.tasks) > spec.maximum_batch_pages:
        raise AppearanceError("appearance task count exceeds its explicit finite batch limit")
    identities = tuple((task.pdf.sha256, task.page_index) for task in spec.tasks)
    if len(set(identities)) != len(identities):
        raise AppearanceError("appearance batch contains duplicate original physical pages")
    if any(not task.pdf.path.startswith("pdf/") for task in spec.tasks):
        raise AppearanceError("appearance original PDFs need their selected input namespace")
    selected = input_files(spec)
    if (
        len(selected) > 10_000
        or len(raw_spec) + sum(file.size for file in selected) > MAX_SELECTION
    ):
        raise AppearanceError("appearance complete selected inputs exceed their bounded budget")
    engine = engine_binding(source, inputs, spec)
    verify_selection(inputs, selected)
    pdfs = {task.pdf.path: task.pdf for task in spec.tasks}
    originals = {name: checked(inputs, file) for name, file in pdfs.items()}
    history = tuple(verify_appearance_prior(inputs, prior, engine) for prior in spec.prior)
    cache = prior_cache(history)
    context = BatchContext(spec, engine, outputs, originals)
    outcomes = tuple(
        _page(task, context, cache.get(appearance_key(task.pdf.sha256, task.page_index, engine)))
        for task in spec.tasks
    )
    verify_selection(source, spec.source_files)
    verify_selection(inputs, selected)
    if read_bytes(inputs / "batch.json", 5_000_000) != raw_spec:
        raise AppearanceError("appearance batch changed during measurement")
    report = AppearanceBatchReport(
        spec_sha256=hashlib.sha256(raw_spec).hexdigest(),
        engine=engine,
        settings=spec.settings,
        outcomes=outcomes,
    )
    _ = publish_record(outputs, "appearance-batch.json", report)
    return report
