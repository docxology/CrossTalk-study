"""Visual measurement and literature appraisal pages retain distinct scientific units."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from crosstalk.study_graphical_svg import (
    CORAL,
    Drawing,
    arrow,
    coverage,
    histogram,
    panel,
    paragraph,
    text,
)

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractInputs


def visual_page(data: AbstractInputs) -> Drawing:
    """Separate whole-page pixel descriptors and reported native typography."""
    scope = data.visual
    body = paragraph(
        (40, 88, 1120, 65),
        (
            "Whole-page appearance includes composited ma"
            + "rks, vectors and masks. Native typography de"
            + "scribes reported text metadata; it can be ab"
            + "sent on visibly printed pages."
        ),
        22,
    )
    body += coverage((40, 174, 540, 190), scope.appearance, "Whole-page appearance: physical pages")
    body += coverage((620, 174, 540, 190), scope.layout, "Native layout inspection: physical pages")
    body += panel((40, 390, 1120, 106), "Measured layout is not measured native typography")
    body += text(
        (58, 458),
        (
            "Native spans: "
            + f"{scope.native_span_pages:,}"
            + "; no native spans: "
            + f"{scope.no_native_span_pages:,}"
            + "; exact union refused: "
            + f"{scope.native_union_refused_pages:,}"
        ),
        24,
    )
    body += paragraph(
        (58, 466, 1084, 28),
        ("Empty native rectangle sets: union = 0. Font" + "-size absence stays unavailable."),
        20,
    )
    body += histogram((40, 522, 350, 440), scope.appearance_entropy)
    body += histogram((425, 522, 350, 440), scope.reported_font_size, CORAL)
    body += histogram((810, 522, 350, 440), scope.native_union_fraction, "#777777")
    body += paragraph(
        (40, 984, 1120, 107),
        scope.interpretation_note
        + (
            " Fonts/flags are reported PDF metadata; pixe"
            + "ls and bounding boxes do not establish image"
            + " semantics, genre or printed-text accuracy."
        ),
        20,
    )
    return Drawing("03 Visual evidence: pixels, native geometry and missingness", body, 1100)


def literature_page(data: AbstractInputs) -> Drawing:
    """Show source-linked review progress and bounded appraisal examples without a census claim."""
    scope = data.literature
    body = paragraph((40, 87, 1120, 70), scope.scope_note, 22)
    for index, stage in enumerate(scope.stages):
        left, top = 40 + (index % 3) * 390, 174 + (index // 3) * 235
        body += panel((left, top, 340, 210), f"{index + 1:02d} {stage.label}")
        body += text(
            (left + 18, top + 115), "Unknown" if stage.count is None else f"{stage.count:,}", 34
        )
        body += paragraph((left + 175, top + 91, 147, 54), stage.unit, 20)
        body += paragraph((left + 18, top + 142, 304, 70), stage.qualification, 18)
        if index % 3 < 2 and index + 1 < len(scope.stages):
            body += arrow((left + 343, top + 105), (left + 385, top + 105))
    rows = math.ceil(len(scope.stages) / 3)
    at = 174 + rows * 235 + 5
    selected = scope.selected_readings[:2]
    body += text(
        (40, at),
        (
            "Source-checked appraisal examples: showing "
            + f"{len(selected)}"
            + " / "
            + f"{len(scope.selected_readings)}"
            + " supplied readings"
        ),
        22,
    )
    height = min(194.0, (1038 - at - 20) / max(1, len(selected)))
    for index, reading in enumerate(selected):
        top = at + 20 + index * height
        body += (
            '<rect x="40" y="'
            + f"{top}"
            + '" width="1120" height="'
            + f"{height - 10}"
            + '" rx="12" fill="white" stroke="#aaaaaa"/>'
        )
        body += paragraph((58, top + 6, 1084, 56), reading.title, 22)
        body += paragraph((58, top + 62, 1084, 24), reading.source_locator, 18)
        body += paragraph(
            (58, top + 91, 1084, height - 106),
            "Evidence: " + reading.evidence_note + " Limit: " + reading.limitation_note,
            20,
        )
    if not selected:
        body += paragraph(
            (40, at + 40, 1120, 150),
            (
                "No selected appraisal example supplied. Disc"
                + "overy/localization counts above cannot subst"
                + "itute for full article reading or critical e"
                + "valuation."
            ),
            24,
        )
    body += paragraph(
        (40, 1048, 1120, 45),
        (
            "Provisional entries are not a validated arti"
            + "cle census. Source-checked AI-assisted appra"
            + "isal does not establish human agreement, whi"
            + "ch remains unmeasured."
        ),
        18,
    )
    return Drawing("04 Literature: discovery, witnesses and critical appraisal", body, 1100)
