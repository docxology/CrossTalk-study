"""Source-bound aggregation of exploratory issue-level measurements."""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from crosstalk.acquisition_lock import project_lock
from crosstalk.analysis_records import AnalysisFailure, AnalysisSummary, IssueAnalysis
from crosstalk.analysis_source import AnalysisSource, admit_analysis_source
from crosstalk.index_observe import IndexReader
from crosstalk.metrics import categorize, image_metrics, text_metrics
from crosstalk.models import AcquisitionError, Issue, safe_directory
from crosstalk.records import ExtractionSummary, write_records
from crosstalk.report import write_report

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["analyze_corpus", "categorize", "image_metrics", "text_metrics"]


def analyze_corpus(root: Path) -> AnalysisSummary:
    """Analyze source-bound native text and separately scoped visuals under the project lock."""
    with project_lock(root):
        return analyze_corpus_locked(root, IndexReader(root))


def analyze_corpus_locked(root: Path, reader: IndexReader) -> AnalysisSummary:
    """Compose only beneath an actual enclosing project_lock, without nested OS locks."""
    for directory in (
        "data/raw/pdf",
        "data/processed/pages",
        "data/processed/images",
        "output/reports",
    ):
        _ = safe_directory(root, directory)
    extraction = ExtractionSummary.model_validate_json(
        reader.read("output/reports/extraction.jsonl").strip()
    )
    try:
        inventory = reader.read("data/manifest/issues.jsonl")
    except FileNotFoundError:
        inventory = b""
    inventory_rows = tuple(
        Issue.model_validate_json(line) for line in inventory.splitlines() if line.strip()
    )
    if len({issue.issue_id for issue in inventory_rows}) != len(inventory_rows):
        raise AcquisitionError("analysis inventory contains duplicate issue identities")
    metadata = {issue.issue_id: issue for issue in inventory_rows}
    analyses: list[IssueAnalysis] = []
    duplicates: list[str] = []
    unavailable: list[str] = []
    failures: list[AnalysisFailure] = []
    hashes: set[str] = set()
    corpus: list[str] = []
    for outcome in extraction.issues:
        issue = metadata.get(outcome.issue_id)
        source = admit_analysis_source(root, outcome, issue, reader=reader)
        match source:
            case AnalysisFailure() as failure:
                unavailable.append(outcome.issue_id)
                failures.append(failure)
                continue
            case AnalysisSource():
                pass
            case _:
                assert_never(source)
        digest, rows, visuals = source.sha256, source.pages, source.visuals
        if digest in hashes:
            duplicates.append(outcome.issue_id)
            continue
        hashes.add(digest)
        text = "\n".join(row.text for row in rows)
        corpus.append(text)
        analyses.append(
            IssueAnalysis(
                analysis_method_version="3",
                visual=source.visual,
                issue_id=outcome.issue_id,
                title=issue.title if issue else outcome.issue_id,
                issued=issue.issued if issue else None,
                source_url=issue.landing_url if issue else None,
                source_sha256=digest,
                pages=len(rows),
                low_text_pages=sum("low-text-ocr-review" in row.quality for row in rows),
                text=text_metrics(text),
                categories=categorize(rows),
                images=visuals,
            )
        )
    ordered = tuple(
        sorted(analyses, key=lambda row: (row.issued is None, row.issued or "", row.issue_id))
    )
    summary = AnalysisSummary(
        method_version="3",
        issues=ordered,
        visual_unavailable_issues=tuple(
            row.issue_id
            for row in ordered
            if row.visual is not None and row.visual.status == "unavailable"
        ),
        visual_partial_issues=tuple(
            row.issue_id
            for row in ordered
            if row.visual is not None and row.visual.status == "partial"
        ),
        duplicate_issues=tuple(duplicates),
        unavailable_issues=tuple(unavailable),
        unavailable_details=tuple(failures),
        corpus_text=text_metrics("\n".join(corpus)),
    )
    reader.recheck()
    write_records(root / "output/reports/analysis.jsonl", (summary,))
    contact = extraction.contact_sheet if summary.issues and not unavailable else None
    write_report(root, summary, contact)
    return summary
