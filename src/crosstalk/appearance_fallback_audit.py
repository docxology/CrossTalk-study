"""Validate a portable strict-plus-fallback appearance projection."""

import csv
import io
import math
import re
from collections import Counter
from hashlib import sha256
from statistics import median
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type PageKey = tuple[str, int]
type Row = dict[str, str]


class AppearanceProjectionError(ValueError):
    """The selected appearance evidence does not reconcile."""


class ControlDeltas(BaseModel):
    """Declared absolute and signed deltas for one metric."""

    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)
    median_signed_delta: float
    median_absolute_delta: float
    p90_absolute_delta_nearest_rank: float
    maximum_absolute_delta: float


class ControlReport(BaseModel):
    """Declared sample counts and paired summaries."""

    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)
    count: int
    count_by_family: dict[str, int]
    same_dimensions: int
    delta_summaries: dict[str, ControlDeltas]
    delta_summaries_by_family: dict[str, dict[str, ControlDeltas]]


class RendererReport(BaseModel):
    """Renderer settings needed to validate the spatial partition."""

    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)
    grid_side: int


class ProjectionReport(BaseModel):
    """Source-bound declarations consumed by the portable audit."""

    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)
    schema_version: int = Field(alias="schema")
    source_page_ledger_sha256: str
    outputs: dict[str, str]
    renderer: RendererReport
    controls: ControlReport
    coverage: dict[str, JsonValue]


class FamilyCoverage(BaseModel):
    """Validated counts for one source family."""

    retained_pages: int
    strict_measured: int
    fallback_measured: int
    combined_measured: int


class AppearanceCoverageAudit(BaseModel):
    """Reconciled retained page-key and renderer control counts."""

    retained_pages: int
    strict_measured_pages: int
    strict_refused_pages: int
    fallback_rendered_pages: int
    fallback_measured_pages: int
    any_whole_page_appearance_measured: int
    unresolved_pages: int
    coverage_by_family: dict[str, FamilyCoverage]
    control_count: int


FALLBACK = "appearance-fallback-pages-v10.csv"
CONTROLS = "appearance-renderer-controls-v10.csv"
REPORT = "appearance-fallback-v10.json"


def _table(raw: bytes) -> list[Row]:
    reader = csv.DictReader(io.StringIO(raw.decode(), newline=""), strict=True)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise AppearanceProjectionError("Invalid table header")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise AppearanceProjectionError("Incomplete table record")
    return rows


def _by_page(rows: list[Row]) -> dict[PageKey, Row]:
    indexed: dict[PageKey, Row] = {}
    for row in rows:
        digest = row["pdf_sha256"]
        page = int(row["page_index_zero_based"])
        key = digest, page
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or page < 0 or key in indexed:
            raise AppearanceProjectionError("Invalid or duplicate physical page key")
        indexed[key] = row
    return indexed


def _validate_metrics(row: Row, original: Row, grid_side: int) -> None:
    width, height, pixels = (int(row[field]) for field in ("width", "height", "pixels"))
    dark = float(row["nonwhite_fraction"])
    if (
        not 0 < width <= 2000
        or not 0 < height <= 2000
        or width * height != pixels
        or abs(width - float(original["width_points"])) > 1.001
        or abs(height - float(original["height_points"])) > 1.001
        or not re.fullmatch(r"[0-9a-f]{64}", row["render_rgb_sha256"])
        or not 0 <= dark <= 1
        or not 0 <= float(row["grayscale_entropy_bits"]) <= 8.0000000001
        or any(not 0 <= float(row[f"mean_{color}"]) <= 255 for color in ("red", "green", "blue"))
    ):
        raise AppearanceProjectionError("Appearance measurement fails physical or numeric bounds")
    weighted_dark = 0.0
    for r in range(grid_side):
        cell_height = height * (r + 1) // grid_side - height * r // grid_side
        for c in range(grid_side):
            cell_width = width * (c + 1) // grid_side - width * c // grid_side
            value = float(row[f"grid_row_{r}_column_{c}"])
            if not 0 <= value <= 1:
                raise AppearanceProjectionError("Invalid spatial darkness fraction")
            weighted_dark += cell_width * cell_height * value
    if not math.isclose(weighted_dark / pixels, dark, rel_tol=0, abs_tol=1e-12):
        raise AppearanceProjectionError(
            "The spatial darkness grid does not reconstruct whole-page darkness"
        )


def _validate_controls(controls: dict[PageKey, Row], report: ControlReport) -> None:
    rows = list(controls.values())
    if not rows:
        raise AppearanceProjectionError("No strict renderer controls are available")
    families = Counter(row["family"] for row in rows)
    same_dimensions = sum(
        (row["width"], row["height"]) == (row["strict_width"], row["strict_height"]) for row in rows
    )
    if (
        report.count != len(rows)
        or report.count_by_family != families
        or report.same_dimensions != same_dimensions
    ):
        raise AppearanceProjectionError("Renderer control count or dimensions do not reconcile")
    groups = {family: [row for row in rows if row["family"] == family] for family in families}
    summaries = report.delta_summaries_by_family
    for subset, summary in [(rows, report.delta_summaries)] + [
        (groups[family], summaries[family]) for family in groups
    ]:
        for metric, expected in summary.items():
            paired = [float(row[metric]) - float(row[f"strict_{metric}"]) for row in subset]
            absolute = sorted(map(abs, paired))
            observed = {
                "median_signed_delta": median(paired),
                "median_absolute_delta": median(absolute),
                "p90_absolute_delta_nearest_rank": absolute[math.ceil(0.9 * len(absolute)) - 1],
                "maximum_absolute_delta": absolute[-1],
            }
            if expected.model_dump() != observed:
                raise AppearanceProjectionError("Renderer control summaries do not reconcile")


def validate_coverage(
    ledger_raw: bytes, fallback_raw: bytes, control_raw: bytes, report_raw: bytes
) -> AppearanceCoverageAudit:
    """Validate all physical keys, reported metrics, and source and output hashes."""
    report = ProjectionReport.model_validate_json(report_raw)
    if (
        report.schema_version != 1
        or report.source_page_ledger_sha256 != sha256(ledger_raw).hexdigest()
        or report.outputs[FALLBACK] != sha256(fallback_raw).hexdigest()
        or report.outputs[CONTROLS] != sha256(control_raw).hexdigest()
    ):
        raise AppearanceProjectionError("Appearance evidence digest mismatch")
    pages = _by_page(_table(ledger_raw))
    fallback = _by_page(_table(fallback_raw))
    controls = _by_page(_table(control_raw))
    refused = {key for key, row in pages.items() if row["appearance_status"] == "policy-refused"}
    strict = {key for key, row in pages.items() if row["appearance_status"] == "measured"}
    if set(fallback) != refused or not set(controls) <= strict:
        raise AppearanceProjectionError(
            "Selected fallback and control keys disagree with strict appearance status"
        )
    grid_side = report.renderer.grid_side
    if not 1 <= grid_side <= 16:
        raise AppearanceProjectionError("Unsupported grid size")
    accepted: set[PageKey] = set()
    for key, row in (fallback | controls).items():
        original = pages[key]
        if (
            row["family"] != original["family"]
            or row["issue_id"] != original["issue_id"]
            or row["strict_appearance_status"] != original["appearance_status"]
            or row["strict_appearance_refusal_reason"] != original["appearance_refusal_reason"]
        ):
            raise AppearanceProjectionError(
                "Fallback evidence changed its source identity or strict policy status"
            )
        _validate_metrics(row, original, grid_side)
        error_lines = int(row["renderer_error_or_unclassified_lines"])
        stderr_lines = int(row["renderer_stderr_lines"])
        if not 0 <= error_lines <= stderr_lines:
            raise AppearanceProjectionError("Renderer diagnostic counts are invalid")
        expected = "rendered-with-errors" if error_lines else "measured"
        if row["fallback_appearance_status"] != expected:
            raise AppearanceProjectionError(
                "Fallback result does not respect the renderer diagnostic policy"
            )
        if key in refused and expected == "measured":
            accepted.add(key)
    _validate_controls(controls, report.controls)
    combined = strict | accepted
    coverage = report.coverage
    expected = {
        "retained_pages": len(pages),
        "strict_measured_pages": len(strict),
        "strict_refused_pages": len(refused),
        "fallback_rendered_pages": len(fallback),
        "fallback_measured_pages": len(accepted),
        "any_whole_page_appearance_measured": len(combined),
    }
    if any(coverage.get(field) != count for field, count in expected.items()):
        raise AppearanceProjectionError("Reported appearance counts do not reconcile")
    family_pages = Counter(row["family"] for row in pages.values())
    strict_by_family = Counter(pages[key]["family"] for key in strict)
    fallback_by_family = Counter(pages[key]["family"] for key in accepted)
    combined_by_family = Counter(pages[key]["family"] for key in combined)
    return AppearanceCoverageAudit(
        **expected,
        unresolved_pages=len(pages.keys() - combined),
        coverage_by_family={
            family: FamilyCoverage(
                retained_pages=total,
                strict_measured=strict_by_family[family],
                fallback_measured=fallback_by_family[family],
                combined_measured=combined_by_family[family],
            )
            for family, total in sorted(family_pages.items())
        },
        control_count=len(controls),
    )
