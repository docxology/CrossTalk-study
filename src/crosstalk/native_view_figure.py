"""Two vector panels show view-specific native proxy diagnostics without difference inference."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never

from crosstalk.models import AcquisitionError, Digest
from crosstalk.records import Record
from crosstalk.statistical_svg import CORAL, MUTED, NAVY, TEAL, Dot, LabelStyle, SVGCanvas, linear

if TYPE_CHECKING:
    from crosstalk.native_layer_records import NativeLayerRun, NativeLayerVariant
    from crosstalk.native_layers.cohort_records import LayerInterval, LexicalMeasure, Weighting


class NativeFigureProof(Record):
    """Exact sealed native report, selected settings and independent vector method identity."""

    native_report_sha256: Digest
    implementation_sha256: Digest
    settings_sha256: Digest
    input_bindings_sha256: Digest


@dataclass(frozen=True, slots=True)
class Panel:
    """A measure owns its finite independent axis and a distinct eligible-n label column."""

    measure: LexicalMeasure
    left: float
    right: float
    domain: tuple[float, float]


@dataclass(frozen=True, slots=True)
class NativeMark:
    """One estimator's observed row, vertical track and weighting color."""

    row: LayerInterval
    y: float
    color: str


WEIGHTINGS: Final[tuple[Weighting, ...]] = ("token-weighted", "equal-issue-weighted")
MEASURES: Final[tuple[LexicalMeasure, ...]] = ("hedge-lexicon-per-1000", "modal-lexicon-per-1000")


def _interval(
    variant: NativeLayerVariant, measure: LexicalMeasure, weighting: Weighting
) -> LayerInterval:
    rows = tuple(
        row
        for row in variant.cohort.intervals
        if row.measure == measure and row.weighting == weighting
    )
    if len(rows) != 1:
        raise AcquisitionError("native view needs one actual interval for every measure/weighting")
    return rows[0]


def _domain(run: NativeLayerRun, measure: LexicalMeasure) -> tuple[float, float]:
    values = [
        value
        for variant in run.variants
        for row in variant.cohort.intervals
        if row.measure == measure
        for value in (row.estimate, row.lower, row.upper)
        if value is not None
    ]
    lower, upper = min((0.0, *values)), max((1.0, *values))
    return lower, upper + (upper - lower) * 0.07


def _label(variant: NativeLayerVariant) -> str:
    if variant.maximum_low_text_fraction is not None:
        return f"Wrapper-minus: low-text <= {variant.maximum_low_text_fraction:.0%}"
    view = variant.cohort.view
    match view:
        case "raw-native":
            return "Raw native"
        case "native-minus-matched-repository-wrapper":
            return "Minus matched wrapper"
        case _:
            assert_never(view)


def _mark(canvas: SVGCanvas, panel: Panel, mark: NativeMark) -> None:
    row, y, color = mark.row, mark.y, mark.color
    n = len(row.eligible_issue_ids)
    canvas.text((panel.right + 8, y + 5), f"n={n}", LabelStyle(15, color))
    if row.estimate is None:
        canvas.text((panel.left + 3, y + 5), "NA", LabelStyle(15, color))
        _mark_metadata(canvas, row)
        return
    x = linear(row.estimate, panel.domain, (panel.left, panel.right))
    match row.status:
        case "available-diagnostic":
            if row.lower is None or row.upper is None:
                raise AcquisitionError("available native diagnostic lacks actual bounds")
            low, high = (
                linear(value, panel.domain, (panel.left, panel.right))
                for value in (row.lower, row.upper)
            )
            canvas.interval((low, y), (high, y))
            for end in (low, high):
                canvas.line((end, y - 5), (end, y + 5), NAVY)
            canvas.dot(
                Dot(
                    (x, y),
                    3.2,
                    f"{row.measure}; {row.weighting}; estimate={row.estimate:.6g}; eligible n={n}",
                    color,
                )
            )
        case "below-resampling-gate":
            canvas.rectangle((x - 3, y - 3, 6, 6), color)
        case "no-eligible-data":
            raise AcquisitionError("no-eligible native diagnostic unexpectedly carries a point")
        case _:
            assert_never(row.status)
    _mark_metadata(canvas, row)


def _mark_metadata(canvas: SVGCanvas, row: LayerInterval) -> None:
    """Each actual point or missing-value symbol declares its own status and denominator."""
    node = canvas.root[-1]
    for key, value in (
        ("data-measure", row.measure),
        ("data-weighting", row.weighting),
        ("data-status", row.status),
        ("data-eligible-n", str(len(row.eligible_issue_ids))),
    ):
        node.set(key, value)


def native_view_svg(run: NativeLayerRun, proof: NativeFigureProof) -> str:
    """Use per-point eligibility and status; unavailable estimates/bounds are never fabricated."""
    if not 1 <= len(run.variants) <= 12:
        raise AcquisitionError("native view chart needs one to twelve observed views")
    height = max(430, 164 + len(run.variants) * 38)
    confidence = run.settings.bootstrap.confidence
    if any(variant.cohort.settings != run.settings.bootstrap for variant in run.variants):
        raise AcquisitionError("native view resampling settings differ from their report")
    canvas = SVGCanvas(
        "Native-text view sensitivity",
        f"Proxy hits / 1,000 native tokens; bars: {confidence:.0%} "
        + "nominal marginal conditional diagnostics.",
    )
    canvas.root.set("viewBox", f"0 0 900 {height}")
    canvas.root.set("height", str(height))
    canvas.text(
        (24, 84),
        "Teal: pooled token rate | Coral: equal-issue mean | Square: point only, below gate",
        LabelStyle(15, MUTED),
    )
    canvas.text((24, 109), "View / workflow-selected n", LabelStyle(15))
    panels = (
        Panel(MEASURES[0], 300, 510, _domain(run, MEASURES[0])),
        Panel(MEASURES[1], 600, 810, _domain(run, MEASURES[1])),
    )
    for panel, title in zip(panels, ("Hedge lexicon proxy", "Modal lexicon proxy"), strict=True):
        canvas.text((panel.left, 109), title, LabelStyle(16))
    for index, variant in enumerate(run.variants):
        y = 135.0 + index * 38
        canvas.text((24, y - 3), _label(variant), LabelStyle(15))
        canvas.text(
            (24, y + 14),
            f"selected n={len(variant.cohort.workflow_selected_issue_ids)}",
            LabelStyle(15, MUTED),
        )
        for panel in panels:
            tracks: tuple[tuple[int, Weighting, str], ...] = (
                (-8, WEIGHTINGS[0], TEAL),
                (9, WEIGHTINGS[1], CORAL),
            )
            for offset, weighting, color in tracks:
                _mark(
                    canvas,
                    panel,
                    NativeMark(_interval(variant, panel.measure, weighting), y + offset, color),
                )
        canvas.line((290, y + 23), (874, y + 23))
    for panel in panels:
        canvas.horizontal_axis(panel.domain, (panel.left, height - 39, panel.right - panel.left, 0))
    caption = (
        "Nominal marginal conditional whole-issue diagnostics; eligibility varies across views. "
        + "No paired difference, causal effect, extraction-error or template-rule uncertainty "
        + "claim. NA indicates an undefined point; square indicates a below-gate point "
        + "without interval."
    )
    canvas.root.set("data-native-report-sha256", proof.native_report_sha256)
    canvas.root.set("aria-labelledby", "title native-desc")
    ET.SubElement(canvas.root, "desc", {"id": "native-desc"}).text = caption
    ET.SubElement(canvas.root, "metadata").text = proof.model_dump_json()
    return ET.tostring(canvas.root, encoding="unicode")
