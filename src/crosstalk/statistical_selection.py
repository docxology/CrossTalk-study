"""Current native-producer agreement, independent of visual decoder availability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.statistical_measures import IssueMeasurements, measure_issue
from crosstalk.statistical_records import StatisticalFailure
from crosstalk.statistical_source import sealed_page_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.analysis_records import AnalysisSummary
    from crosstalk.index_observe import IndexReader
    from crosstalk.linguistic_records import LinguisticRun
    from crosstalk.records import IssueExtraction


@dataclass(frozen=True, slots=True)
class ProducerPair:
    """Both current producer observations over one captured extraction scope."""

    baseline: AnalysisSummary
    linguistic: LinguisticRun


@dataclass(frozen=True, slots=True)
class MeasurementSelection:
    """Accepted source units and mutually separate selected failure/duplicate states."""

    bundles: tuple[IssueMeasurements, ...]
    unavailable: tuple[StatisticalFailure, ...]
    duplicates: tuple[str, ...]


def collect_measurements(
    root: Path,
    producers: ProducerPair,
    selected: tuple[IssueExtraction, ...],
    *,
    reader: IndexReader | None = None,
) -> MeasurementSelection:
    """Do not let one failed producer or edited cache silently supply a partial unit."""
    bases = {issue.issue_id: issue for issue in producers.baseline.issues}
    words = {issue.issue_id: issue for issue in producers.linguistic.issues}
    identifiers = {row.issue_id for row in selected}
    duplicates = tuple(
        sorted(
            (
                set(producers.baseline.duplicate_issues)
                | set(producers.linguistic.duplicate_issue_ids)
            )
            & identifiers
        )
    )
    failed = {row.issue_id: row.reason for row in producers.linguistic.unavailable}
    failed.update(
        {
            row.issue_id: f"Baseline {row.stage}: {row.path or 'unavailable path'}: "
            + f"{row.error_type or 'source check'}: {row.reason}"
            + (f"; initial Pillow error: {row.initial_error}" if row.initial_error else "")
            for row in producers.baseline.unavailable_details
        }
    )
    bundles: list[IssueMeasurements] = []
    unavailable: list[StatisticalFailure] = []
    for outcome in selected:
        if outcome.issue_id in duplicates:
            continue
        base, word = bases.get(outcome.issue_id), words.get(outcome.issue_id)
        if base is None or word is None:
            unavailable.append(
                StatisticalFailure(
                    issue_id=outcome.issue_id,
                    reason=failed.get(outcome.issue_id, "Not accepted by both current producers"),
                )
            )
            continue
        try:
            _ = sealed_page_bytes(root, outcome)
            bundles.append(measure_issue(root, base, word, reader=reader))
        except (OSError, ValueError) as error:
            unavailable.append(StatisticalFailure(issue_id=outcome.issue_id, reason=str(error)))
    return MeasurementSelection(tuple(bundles), tuple(unavailable), duplicates)
