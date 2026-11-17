"""Publish six source-bound scientific SVGs and their escaped HTML dashboard."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from crosstalk.models import AcquisitionError, file_digest, safe_directory
from crosstalk.records import write_records
from crosstalk.statistical_distribution_charts import coverage_chart, image_chart, page_chart
from crosstalk.statistical_interval_charts import decade_chart, diversity_chart, rate_chart
from crosstalk.statistical_visual_html import DashboardInput, RenderedFigure, statistical_dashboard
from crosstalk.statistical_visual_records import VisualFigure, VisualMetadata, VisualSummary
from crosstalk.statistical_visual_source import binding_rows, statistical_visual_inputs

if TYPE_CHECKING:
    from crosstalk.statistical_records import StatisticalRun


def _publish(path: Path, raw: bytes) -> None:
    """Atomically publish changed regular output bytes, preserving identical artifacts."""
    if path.is_symlink():
        raise AcquisitionError("statistical visualization output is a symlink")
    if path.exists() and file_digest(path) == hashlib.sha256(raw).hexdigest():
        return
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".statistical-visual-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    _ = Path(temporary).replace(path)


def render_statistical_report(root: Path, run: StatisticalRun) -> VisualSummary:
    """Require a current statistical run, then render descriptors and eligible diagnostics."""
    root = root.absolute()
    directory = safe_directory(root, "output/figures/statistics")
    reports = safe_directory(root, "output/reports")
    report = reports / "statistics.html"
    receipt = reports / "statistical-visuals.jsonl"
    with statistical_visual_inputs(root, run) as inputs:
        metadata = VisualMetadata(
            statistics_sha256=inputs.statistics_sha256,
            source_binding_sha256=run.source_binding_sha256,
            statistical_implementation_sha256=run.implementation_sha256,
            rendering_implementation_sha256=inputs.rendering_sha256,
            input_snapshot_sha256=inputs.snapshot_digest(),
            settings=run.settings,
            observed_at=run.observed_at,
        )
        drafts = (
            coverage_chart(run, inputs.coverage),
            page_chart(run),
            image_chart(run),
            rate_chart(run),
            diversity_chart(run),
            decade_chart(run),
        )
        rendered: list[RenderedFigure] = []
        for draft in drafts:
            svg = draft.svg(metadata)
            figure = VisualFigure(
                name=draft.name,
                title=draft.title,
                unit=draft.unit,
                path=(directory / (draft.name + ".svg")).relative_to(root).as_posix(),
                sha256=hashlib.sha256(svg.encode()).hexdigest(),
                observed_units=draft.observed_units,
                caption=draft.caption,
            )
            rendered.append(RenderedFigure(figure, svg))
        bindings = binding_rows(inputs)
        document = statistical_dashboard(
            DashboardInput(
                run=run,
                metadata=metadata,
                coverage=inputs.coverage,
                figures=tuple(rendered),
                bindings=bindings,
                missing=tuple(sorted(inputs.reader.missing)),
            )
        ).encode()
        paths = (report, receipt, *(root / row.figure.path for row in rendered))
        if any(path.is_symlink() for path in paths):
            raise AcquisitionError("statistical visualization target is a symlink")
        inputs.recheck(run)
        summary = VisualSummary(
            report_path=report.relative_to(root).as_posix(),
            report_sha256=hashlib.sha256(document).hexdigest(),
            metadata=metadata,
            figures=tuple(row.figure for row in rendered),
            source_bindings=bindings,
            missing_inputs=tuple(sorted(inputs.reader.missing)),
            coverage=inputs.coverage,
            notes=run.limitations,
        )
        for row in rendered:
            _publish(root / row.figure.path, row.svg.encode())
        _publish(report, document)
        inputs.recheck(run)
        write_records(receipt, (summary,))
        return summary
