"""Finite OCR producer for actual isolated source/input/runtime snapshots."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from crosstalk.ocr_engine import recognize
from crosstalk.ocr_files import MAX_SELECTION, publish_record, read_bytes, verify_selection
from crosstalk.ocr_records import BatchReport, BatchSpec, BoundFile, OcrError, PageOutcome
from crosstalk.ocr_resume import VerifiedPrior, verify_prior
from crosstalk.ocr_source import engine_binding, page_key, prepare_pages

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def prior_cache(history: tuple[VerifiedPrior, ...]) -> Mapping[str, VerifiedPrior]:
    """Only sealed text/empty outcomes authorize reuse; contradictory cached text refuses."""
    cache: dict[str, VerifiedPrior] = {}
    for prior in history:
        result = prior.result
        if result.status not in {"ocr-produced", "ocr-empty"}:
            continue
        if result.cache_key != page_key(result.source, result.engine):
            raise OcrError("prior OCR cache key disagrees with its actual bound result")
        if result.cache_key in cache and cache[result.cache_key].result != result:
            raise OcrError("conflicting supervisor-sealed OCR results require reconciliation")
        cache[result.cache_key] = prior
    return cache


def input_files(spec: BatchSpec) -> tuple[BoundFile, ...]:
    """Construct the exact consumed input closure and refuse conflicting path declarations."""
    files: dict[str, BoundFile] = {}
    declared = [*spec.dependencies, spec.model]
    for task in spec.tasks:
        declared.extend((task.pdf, task.native))
    for prior in spec.prior:
        declared.extend((prior.results, prior.compute_exit, prior.run_use, prior.artifact))
    for item in declared:
        if item.path in files and files[item.path] != item:
            raise OcrError("one OCR input path has conflicting selected digests")
        files[item.path] = item
    return tuple(sorted(files.values(), key=lambda file: file.path))


def run_batch(source: Path, inputs: Path, outputs: Path, runtime_sha256: str) -> BatchReport:
    """Do not claim isolation here: actual isolated_run admission is the supervisor's job."""
    raw = read_bytes(inputs / "batch.json", 5_000_000)
    spec = BatchSpec.model_validate_json(raw)
    if spec.runtime_sha256 != runtime_sha256:
        raise OcrError("actual supervisor runtime binding differs from the reviewed batch")
    engine = engine_binding(source, inputs, spec)
    selected_files = input_files(spec)
    if len(selected_files) > 10_000 or sum(file.size for file in selected_files) > MAX_SELECTION:
        raise OcrError("complete OCR input closure exceeds the finite selection budget")
    engine_paths = {file.path for file in (*spec.dependencies, spec.model)}
    verify_selection(
        inputs, tuple(file for file in selected_files if file.path not in engine_paths)
    )
    prepared = prepare_pages(inputs, spec)
    history = tuple(verify_prior(inputs, prior, engine) for prior in spec.prior)
    cache = prior_cache(history)
    outcomes: list[PageOutcome] = []
    for page in prepared:
        key = page_key(page.source, engine)
        previous = cache.get(key)
        result = (
            previous.result
            if previous
            else recognize(page, engine, spec.settings, inputs / spec.model.path)
        )
        if result.source != page.source:
            raise OcrError("cached page differs from the independently bound current source")
        file = publish_record(outputs, f"pages/{key}.json", result)
        outcomes.append(
            PageOutcome(
                source=page.source,
                output=file,
                status=result.status,
                reused=previous is not None,
                prior_run_id=previous.run_id if previous else None,
            )
        )
    # Two closure checks per run, never 55 MB of engine hashing on every page.
    verify_selection(source, spec.source_files)
    verify_selection(inputs, selected_files)
    if read_bytes(inputs / "batch.json", 5_000_000) != raw:
        raise OcrError("OCR batch specification changed during recognition")
    report = BatchReport(
        spec_sha256=hashlib.sha256(raw).hexdigest(),
        engine=engine,
        settings=spec.settings,
        outcomes=tuple(outcomes),
    )
    _ = publish_record(outputs, "ocr-batch.json", report)
    return report
