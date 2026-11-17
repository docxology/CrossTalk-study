"""Attach current statistical observations and original vector plates to the dossier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.analysis_records import AnalysisSummary
from crosstalk.corpus_index import build_corpus_index
from crosstalk.dossier_native_layers import current_native_layer_appendix
from crosstalk.dossier_records import DossierFigure, DossierSection, SourceBinding
from crosstalk.models import file_digest
from crosstalk.statistical_analysis import analyze_statistics
from crosstalk.statistical_scope_report import native_visual_scope_text
from crosstalk.statistical_source import read_artifact
from crosstalk.statistical_visual_report import render_statistical_report

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class DossierStatistics:
    """One freshly measured statistical appendix and its independently checked inputs."""

    analysis: AnalysisSummary
    section: DossierSection
    figures: tuple[DossierFigure, ...]
    bindings: tuple[SourceBinding, ...]


def current_statistics(root: Path) -> DossierStatistics:
    """Recompute producers once; bind their receipts, CSV exports and SVG plates."""
    _ = build_corpus_index(root)
    run = analyze_statistics(root)
    visual = render_statistical_report(root, run)
    analysis = AnalysisSummary.model_validate_json(
        read_artifact(root / "output/reports/analysis.jsonl").strip()
    )
    native = current_native_layer_appendix(root)
    paragraphs = [
        *native.paragraphs,
        native_visual_scope_text(run),
        f"Current statistical units: {len(run.issues)} accepted source-distinct issue PDF(s), "
        + f"{len(run.pages)} physical pages, {len(run.images)} issue/asset pairs and "
        + f"{run.unique_saved_assets} distinct measured saved asset digests. "
        + "Pages and image occurrences are nested observations, not independent issue samples.",
        f"Extraction scope: {run.complete_extraction_issue_units} complete-status issues and "
        + f"{run.partial_extraction_issue_units} partial issues; "
        + f"{run.unknown_page_coverage_issue_units} issues have unknown total-page coverage. "
        + "Principal resampling diagnostics require complete status and independently known "
        + "extracted/total PDF page agreement. Partial-inclusive descriptions remain separate.",
        "Raw baseline tokens and Unicode-normalized linguistic tokens use different algorithms. "
        + "Every rate declares its denominator. Zero-token units are retained descriptively; "
        + "undefined rates and insufficient-data intervals remain unavailable.",
    ]
    for interval in run.bootstrap:
        estimate = "unavailable" if interval.estimate is None else f"{interval.estimate:.6g}"
        bounds = (
            "unavailable"
            if interval.lower is None or interval.upper is None
            else f"[{interval.lower:.6g}, {interval.upper:.6g}]"
        )
        paragraphs.append(
            f"{interval.measure}: estimate {estimate}; diagnostic interval {bounds}; "
            + f"status {interval.status}; eligible source-distinct issue units "
            + f"{interval.eligible_source_issue_units}; "
            + f"excluded partial issues {interval.excluded_partial_issue_units}, "
            + f"unknown coverage {interval.excluded_unknown_coverage_issue_units}, "
            + f"unavailable metric {interval.excluded_metric_unavailable_issue_units}; "
            + f"denominator: {interval.denominator}."
        )
    paragraphs.extend(
        (
            f"Diagnostic settings: seed {run.settings.seed}; "
            + f"{run.settings.resamples} requested whole-issue resamples; "
            + f"{run.settings.confidence:.0%} percentile bounds; "
            + f"minimum {run.settings.minimum_issues} eligible issues. "
            + "This minimum is a heuristic. Adjacent issues can share editorial and temporal "
            + "dependence, so the count does not establish independent sampling.",
            *run.limitations,
        )
    )
    bindings = {row.path: row.sha256 for row in visual.source_bindings}
    bindings.update({row.path: row.sha256 for row in native.bindings})
    for relative in (
        "output/reports/statistics.jsonl",
        "output/reports/statistical-visuals.jsonl",
        visual.report_path,
    ):
        bindings[relative] = file_digest(root / relative)
    for figure in visual.figures:
        bindings[figure.path] = figure.sha256
    return DossierStatistics(
        analysis=analysis,
        section=DossierSection(
            title="Current statistical observations", paragraphs=tuple(paragraphs)
        ),
        figures=(
            *native.figures,
            *(
                DossierFigure(
                    title=figure.title,
                    path=figure.path,
                    sha256=figure.sha256,
                    caption=figure.caption,
                )
                for figure in visual.figures
            ),
        ),
        bindings=tuple(
            SourceBinding(path=path, sha256=digest) for path, digest in sorted(bindings.items())
        ),
    )
