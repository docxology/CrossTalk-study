"""Recompute producers and bind descriptive statistics to current local sources."""

from __future__ import annotations

import hashlib
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from crosstalk.acquisition_lock import project_lock
from crosstalk.analysis import analyze_corpus_locked
from crosstalk.analysis_records import AnalysisSummary
from crosstalk.extraction_method import EXTRACTION_IMPLEMENTATION_FILES
from crosstalk.index_observe import IndexReader
from crosstalk.linguistic_records import LinguisticRun, LinguisticSettings
from crosstalk.linguistics import analyze_linguistics_locked
from crosstalk.models import file_digest, safe_directory
from crosstalk.records import ExtractionSummary, write_records
from crosstalk.statistical_bootstrap import cluster_intervals, principal_issue
from crosstalk.statistical_distributions import decade_summaries, distributions
from crosstalk.statistical_export import export_statistics
from crosstalk.statistical_records import (
    BootstrapSettings,
    SourceBinding,
    StatisticalRun,
)
from crosstalk.statistical_selection import ProducerPair, collect_measurements
from crosstalk.statistical_source import read_artifact

IMPLEMENTATION_FILES: Final = (
    "statistical_analysis.py",
    "statistical_records.py",
    "statistical_scope.py",
    "statistical_source.py",
    "statistical_measures.py",
    "statistical_bootstrap.py",
    "statistical_distributions.py",
    "statistical_export.py",
    "statistical_issue_export.py",
    "statistical_csv.py",
    "statistical_selection.py",
    "analysis.py",
    "analysis_source.py",
    "analysis_records.py",
    "extraction_cache.py",
    "metrics.py",
    "image_decode.py",
    "image_native.py",
    "image_preview.py",
    "report.py",
    "lexicon.py",
    "linguistics.py",
    "linguistic_metrics.py",
    "linguistic_records.py",
    "models.py",
    "records.py",
    "pdf_adapter.py",
    "text_source.py",
    "visual_records.py",
    "visual_measurement.py",
    "visual_asset.py",
    "visual_report.py",
    "index_observe.py",
    "index_records.py",
    *EXTRACTION_IMPLEMENTATION_FILES,
)


def _implementation_digest() -> str:
    """Bind all measurement, orchestration and schema dependencies explicitly."""
    digest = hashlib.sha256()
    for filename in IMPLEMENTATION_FILES:
        digest.update(filename.encode())
        digest.update(Path(__file__).with_name(filename).read_bytes())
    return digest.hexdigest()


def analyze_statistics(root: Path, settings: BootstrapSettings | None = None) -> StatisticalRun:
    """Recompute current native producers; visual missingness cannot exclude accepted text."""
    with project_lock(root):
        return analyze_statistics_locked(root, settings or BootstrapSettings(), IndexReader(root))


def analyze_statistics_locked(
    root: Path, config: BootstrapSettings, reader: IndexReader
) -> StatisticalRun:
    """Compose producers beneath an actual project_lock, sharing one runtime custody reader."""
    for directory in (
        "data/raw/pdf",
        "data/processed/pages",
        "data/processed/images",
        "data/manifest",
        "output/reports",
        "output/data",
    ):
        _ = safe_directory(root, directory)
    implementation = _implementation_digest()
    extraction_raw = reader.read("output/reports/extraction.jsonl")
    extraction_digest = hashlib.sha256(extraction_raw).hexdigest()
    extraction = ExtractionSummary.model_validate_json(extraction_raw.strip())
    manifest = root / "data/manifest/issues.jsonl"
    manifest_digest = file_digest(manifest) if manifest.exists() else None
    analysis = analyze_corpus_locked(root, reader)
    analysis_raw = read_artifact(root / "output/reports/analysis.jsonl")
    if AnalysisSummary.model_validate_json(analysis_raw.strip()) != analysis:
        message = "analysis receipt changed while statistics captured it"
        raise ValueError(message)
    linguistic = analyze_linguistics_locked(
        root,
        LinguisticSettings(window_size=config.window_size, max_issues=config.max_issues),
        reader,
    )
    linguistic_raw = read_artifact(root / "output/reports/linguistics.jsonl")
    if (
        LinguisticRun.model_validate_json(linguistic_raw.strip()) != linguistic
        or linguistic.extraction_receipt_sha256 != extraction_digest
        or linguistic.manifest_sha256 != manifest_digest
    ):
        message = "linguistic producer receipt/source scope changed during statistical capture"
        raise ValueError(message)
    selected = extraction.issues[: config.max_issues]
    selection = collect_measurements(
        root, ProducerPair(analysis, linguistic), selected, reader=reader
    )
    bundles = selection.bundles
    issues = tuple(sorted((bundle.issue for bundle in bundles), key=lambda row: row.issue_id))
    pages = tuple(
        row
        for bundle in sorted(bundles, key=lambda item: item.issue.issue_id)
        for row in bundle.pages
    )
    images = tuple(
        row
        for bundle in sorted(bundles, key=lambda item: item.issue.issue_id)
        for row in bundle.images
    )
    bindings = tuple(
        SourceBinding(
            issue_id=row.issue_id,
            pdf_sha256=row.pdf_sha256,
            page_artifact_sha256=row.page_artifact_sha256,
        )
        for row in issues
    )
    binding_digest = hashlib.sha256()
    binding_digest.update(extraction_digest.encode())
    binding_digest.update((manifest_digest or "missing-manifest").encode())
    for binding in bindings:
        binding_digest.update(binding.model_dump_json().encode())
    run = StatisticalRun(
        method_version="3",
        native_text_issue_units=len(issues),
        pixel_measured_issue_units=sum(bool(row.measured_distinct_assets) for row in issues),
        visual_partial_issue_units=sum(row.visual_status == "partial" for row in issues),
        visual_unavailable_issue_units=sum(row.visual_status == "unavailable" for row in issues),
        visual_complete_scope_issue_units=sum(
            row.visual_status in {"complete-declared-raster-scope", "empty-declared-raster-scope"}
            for row in issues
        ),
        observed_at=datetime.now(UTC).isoformat(),
        source_binding_sha256=binding_digest.hexdigest(),
        implementation_sha256=implementation,
        analysis_receipt_sha256=hashlib.sha256(analysis_raw).hexdigest(),
        linguistics_receipt_sha256=hashlib.sha256(linguistic_raw).hexdigest(),
        extraction_receipt_sha256=extraction_digest,
        manifest_sha256=manifest_digest,
        settings=config,
        python_version=platform.python_version(),
        issues=issues,
        pages=pages,
        images=images,
        extraction_issue_units=len(extraction.issues),
        selected_issue_units=len(selected),
        complete_extraction_issue_units=sum(row.extraction_status == "complete" for row in issues),
        partial_extraction_issue_units=sum(row.extraction_status == "partial" for row in issues),
        unknown_page_coverage_issue_units=sum(row.total_pdf_pages is None for row in issues),
        principal_diagnostic_issue_units=sum(principal_issue(row) for row in issues),
        deferred_issue_ids=tuple(row.issue_id for row in extraction.issues[config.max_issues :]),
        distributions=distributions(issues, pages, images),
        bootstrap=cluster_intervals(issues, config),
        decades=decade_summaries(issues),
        unavailable=selection.unavailable,
        duplicate_issue_ids=selection.duplicates,
        date_excluded_issue_ids=tuple(row.issue_id for row in issues if row.metadata_year is None),
        unique_saved_assets=len({row.image_sha256 for row in images}),
    )
    for binding in bindings:
        if (
            file_digest(root / "data/raw/pdf" / f"{binding.issue_id}.pdf") != binding.pdf_sha256
            or file_digest(root / "data/processed/pages" / f"{binding.issue_id}.jsonl")
            != binding.page_artifact_sha256
        ):
            message = "source bytes changed while computing statistical diagnostics"
            raise ValueError(message)
    for image in images:
        if file_digest(root / image.path) != image.image_sha256:
            message = "image bytes changed while computing statistical diagnostics"
            raise ValueError(message)
    if (
        file_digest(root / "output/reports/extraction.jsonl") != extraction_digest
        or (file_digest(manifest) if manifest.exists() else None) != manifest_digest
        or _implementation_digest() != implementation
    ):
        message = "statistical scope or implementation changed during computation"
        raise ValueError(message)
    reader.recheck()
    export_statistics(root, run)
    write_records(root / "output/reports/statistics.jsonl", (run,))
    return run
