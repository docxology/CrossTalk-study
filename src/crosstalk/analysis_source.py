"""Native custody admission with independent per-asset visual coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from crosstalk.analysis_records import AnalysisFailure
from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError
from crosstalk.text_source import MeasurementInputs, TextAdmissionFailure, admit_text_source
from crosstalk.visual_measurement import measure_visuals

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.analysis_records import VisualMetrics
    from crosstalk.models import Issue
    from crosstalk.records import IssueExtraction, PageRecord
    from crosstalk.visual_records import VisualObservation


@dataclass(frozen=True, slots=True)
class AnalysisSource:
    """Native-accepted pages retain independent pixel observations and visual missingness."""

    sha256: str
    pages: tuple[PageRecord, ...]
    visuals: tuple[VisualMetrics, ...]
    visual: VisualObservation


def admit_analysis_source(
    root: Path, outcome: IssueExtraction, issue: Issue | None, *, reader: IndexReader | None = None
) -> AnalysisSource | AnalysisFailure:
    """Native refusals exclude text; visual asset failures preserve eligible native text."""
    own_reader = reader is None
    reader = reader if reader is not None else IndexReader(root)
    native = admit_text_source(root, outcome, issue, reader=reader)
    match native:
        case TextAdmissionFailure():
            return AnalysisFailure(
                issue_id=native.issue_id,
                stage=native.stage,
                path=None,
                reason=native.reason,
            )
        case MeasurementInputs():
            visual = measure_visuals(root, outcome.issue_id, native.pages)
            for image in visual.images:
                if reader.digest(image.path).sha256 != image.sha256:
                    raise AcquisitionError("accepted raster changed before source publication")
            if own_reader:
                reader.recheck()
            return AnalysisSource(native.sha256, native.pages, visual.images, visual.coverage)
        case _:
            assert_never(native)
