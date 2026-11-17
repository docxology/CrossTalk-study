"""Page morphology and an evidence matrix use grayscale density and direct source labels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.study_briefing_svg import (
    GRAY,
    RED,
    BriefingPage,
    coverage,
    histogram,
    line,
    metric,
    number,
    section,
)
from crosstalk.study_continuation import continuation_diagram
from crosstalk.study_graphical_svg import paragraph, text

if TYPE_CHECKING:
    from crosstalk.study_continuation_records import ContinuationWitness
    from crosstalk.study_graphical_records import AbstractInputs


def morphology(data: AbstractInputs) -> BriefingPage:
    """Pixel, font and native-rectangle measurements retain separate eligibility and exclusions."""
    scope = data.visual
    body = coverage((20, 112, 550, 175), scope.appearance, "WHOLE-PAGE APPEARANCE")
    body += coverage((630, 112, 550, 175), scope.layout, "NATIVE LAYOUT INSPECTION")
    body += metric((20, 318, 350, 135), scope.native_span_pages, "FONT METADATA OBSERVED")
    body += metric((425, 318, 350, 135), scope.no_native_span_pages, "FONT METADATA UNAVAILABLE")
    body += metric(
        (830, 318, 350, 135), scope.native_union_refused_pages, "UNION CAPACITY REFUSALS"
    )
    body += histogram((20, 489, 350, 468), scope.appearance_entropy)
    body += histogram((425, 489, 350, 468), scope.reported_font_size)
    body += histogram((830, 489, 350, 468), scope.native_union_fraction)
    body += line((20, 980, 1180, 980))
    body += text(
        (20, 1012),
        (
            "Empty native rectangle sets have measured un"
            + "ion = 0. Missing font size is unavailable."
        ),
        20,
    )
    body += paragraph((20, 1030, 1160, 57), scope.interpretation_note, 20)
    return BriefingPage("03 / PAGE MORPHOLOGY", "measured descriptor channels", body, 1100)


def evidence(data: AbstractInputs, continuation: ContinuationWitness | None = None) -> BriefingPage:
    """Show unit-labelled evidence stages and source-linked appraisal observations."""
    scope = data.literature
    body = section((20, 116), "EVIDENCE STAGES") + line((470, 105, 470, 1055), GRAY)
    for index, stage in enumerate(scope.stages):
        top = 144 + index * 153
        body += paragraph((20, top - 24, 430, 54), f"{index + 1:02d} / {stage.label.upper()}", 20)
        body += number((20, top + 78), stage.count, 42)
        body += paragraph((260, top + 52, 185, 54), stage.unit, 18)
        body += paragraph((20, top + 94, 430, 54), stage.qualification, 18)
        body += line((20, top + 146, 445, top + 146), GRAY)
    body += paragraph((500, 109, 680, 83), scope.scope_note, 20)
    selected = scope.selected_readings[:2] if continuation is None else ()
    body += section(
        (500, 224),
        (
            "APPRAISAL / "
            + f"{len(selected)}"
            + " OF "
            + f"{len(scope.selected_readings)}"
            + " READINGS SHOWN"
        )
        if continuation is None
        else "SOURCE-LOCATED CONTINUATION CASE",
    )
    if continuation is not None:
        body += continuation_diagram(continuation)
    for index, reading in enumerate(selected):
        top = 252 + index * 380
        body += paragraph((500, top, 680, 86), reading.title, 22)
        body += paragraph((500, top + 90, 680, 45), reading.source_locator, 18)
        body += section((500, top + 163), "OBSERVATION")
        body += paragraph((500, top + 176, 680, 60), reading.evidence_note, 20)
        body += f'<g fill="{RED}">' + text((500, top + 266), "APPRAISAL BOUNDARY", 18) + "</g>"
        body += paragraph((500, top + 280, 680, 75), reading.limitation_note, 20)
        body += line((500, top + 368, 1180, top + 368), GRAY)
    if not selected and continuation is None:
        body += paragraph(
            (500, 265, 680, 160),
            (
                "No selected reading supplied. Discovery coun"
                + "ts cannot substitute for source-linked appra"
                + "isal."
            ),
            24,
        )
    body += line((20, 1066, 1180, 1066))
    body += text((20, 1090), "PROVISIONAL ARTICLE CENSUS / HUMAN AGREEMENT: NOT MEASURED", 18)
    return BriefingPage(
        "04 / EVIDENCE MATRIX",
        "explicit textual continuation" if continuation is not None else "source-checked appraisal",
        body,
        1100,
    )
