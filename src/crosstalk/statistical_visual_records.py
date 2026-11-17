"""Source identities and scientific units attached to statistical figures."""

from __future__ import annotations

from typing import Literal

from crosstalk.index_records import IndexBinding  # noqa: TC001 -- Pydantic resolves nested records.
from crosstalk.models import Digest  # noqa: TC001 -- Pydantic resolves digest fields at runtime.
from crosstalk.records import Record
from crosstalk.statistical_records import BootstrapSettings  # noqa: TC001 -- Runtime schema.


class CoverageObservation(Record):
    """Guarded catalog accounting; unknown historical holdings are never a percentage."""

    available: bool
    catalog_records: int | None = None
    catalog_reported_total: int | None = None
    capture_matches_reported: bool | None = None
    resolved_locators: int | None = None
    verified_pdfs: int | None = None
    current_extractions: int | None = None
    accepted_indexed_issues: int | None = None
    uncataloged_accepted_issues: int | None = None
    reason: str | None = None
    expected_historical_issues: None = None


class VisualMetadata(Record):
    """Full data-receipt identity and declared settings travel with every SVG."""

    method_version: Literal["2"] = "2"
    statistics_sha256: Digest
    source_binding_sha256: Digest
    statistical_implementation_sha256: Digest
    rendering_implementation_sha256: Digest
    input_snapshot_sha256: Digest
    settings: BootstrapSettings
    observed_at: str
    archive_complete: Literal[False] = False


class VisualFigure(Record):
    """One portable chart with a declared observational unit and content digest."""

    name: str
    title: str
    path: str
    sha256: Digest
    unit: str
    observed_units: int | None
    caption: str


class VisualSummary(Record):
    """A finite, reproducible visual report, conditional on captured local sources."""

    report_path: str
    report_sha256: Digest
    metadata: VisualMetadata
    figures: tuple[VisualFigure, ...]
    source_bindings: tuple[IndexBinding, ...]
    missing_inputs: tuple[str, ...]
    coverage: CoverageObservation
    notes: tuple[str, ...]
    archive_complete: Literal[False] = False
