"""Presentation-only research briefing pages preserve the frozen measurement epoch."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.study_briefing_evidence import evidence, morphology
from crosstalk.study_briefing_svg import canvas
from crosstalk.study_briefing_text import language, source_frame
from crosstalk.study_language_records import StudyError, StudyFigure

if TYPE_CHECKING:
    from crosstalk.study_continuation_records import ContinuationWitness
    from crosstalk.study_graphical_records import AbstractInputs

METHOD_FILES: Final = (
    "study_briefing.py",
    "study_briefing_svg.py",
    "study_briefing_text.py",
    "study_briefing_evidence.py",
    "study_continuation.py",
    "study_continuation_records.py",
    "study_graphical_records.py",
    "study_graphical_svg.py",
    "study_graphical_labels.py",
    "study_language_records.py",
)


def implementation_digest() -> str:
    """Frame only the presentation source/runtime; the measurement identity remains separate."""
    directory = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest()) for name in METHOD_FILES
    )
    return hashlib.sha256(
        json.dumps(
            (members, sys.version, unicodedata.unidata_version), separators=(",", ":")
        ).encode()
    ).hexdigest()


def captions(data: AbstractInputs) -> tuple[str, ...]:
    """State what is shown, its unit/eligible N/exclusions, then one bounded interpretation."""
    source, text, visual, review = data.corpus, data.language, data.visual, data.literature
    return (
        (
            "Captured NPS frame: "
            + f"{source.captured_catalog_rows:,}"
            + " metadata rows, "
            + f"{source.verified_pdf_sources:,}"
            + " verified PDF sources and "
            + f"{source.physical_pages:,}"
            + " physical pages. "
        )
        + (
            "Year bars exclude "
            + f"{source.undated_catalog_rows:,}"
            + " undated rows; publisher cards remain a sepa"
            + "rate family. Catalog gaps do not establish m"
            + "issing historical issues."
        ),
        (
            "Native text covers "
            + f"{text.native.supplied_units:,}"
            + " physical pages; accepted OCR covers "
            + f"{text.ocr.supplied_units:,}"
            + " overlapping physical pages. "
        )
        + (
            "Diversity distributions include "
            + f"{text.native.diversity.eligible_units:,}"
            + " native and "
            + f"{text.ocr.diversity.eligible_units:,}"
            + " OCR pages; "
        )
        + (
            "short/unavailable exclusions are "
            + f"{text.native.diversity.unavailable_units:,}"
            + " and "
            + f"{text.ocr.diversity.unavailable_units:,}"
            + ". These layers retain distinct denominators."
        ),
        (
            "Physical-page morphology: appearance N="
            + f"{visual.appearance.measured_pages:,}"
            + "/"
            + f"{visual.appearance.total_pages:,}"
            + "; layout N="
            + f"{visual.layout.measured_pages:,}"
            + "/"
            + f"{visual.layout.total_pages:,}"
            + ". "
        )
        + (
            "Font summaries include "
            + f"{visual.native_span_pages:,}"
            + " pages; union excludes "
            + f"{visual.native_union_refused_pages:,}"
            + " capacity refusals and retains observed zero"
            + " rectangle sets. Native observability differ"
            + "s from printed content."
        ),
        (
            "The matrix retains "
            + f"{len(review.stages)}"
            + " source-checking stages and their displayed "
            + "units; "
            + f"{min(2, len(review.selected_readings))}"
            + " of "
            + f"{len(review.selected_readings)}"
            + " supplied appraisals are shown. "
        )
        + (
            "Discovery counts do not measure completed ap"
            + "praisal; the article census remains provisio"
            + "nal and human agreement is unmeasured."
        ),
    )


def briefing_abstracts(
    data: AbstractInputs, continuation: ContinuationWitness | None = None
) -> tuple[StudyFigure, ...]:
    """Create four monochrome pages from caller-admitted unchanged measurements."""
    method = implementation_digest()
    combined = (
        data.model_dump_json(),
        continuation.model_dump_json() if continuation is not None else None,
    )
    input_sha = hashlib.sha256(json.dumps(combined, separators=(",", ":")).encode()).hexdigest()
    figures: list[StudyFigure] = []
    for index, (factory, inherited_caption) in enumerate(
        zip((source_frame, language, morphology, evidence), captions(data), strict=True), 1
    ):
        page = evidence(data, continuation) if index == 4 else factory(data)
        caption = inherited_caption
        if index == 4 and continuation is not None:
            physical = {node.step_id: node.physical_page_index for node in continuation.pages}
            backward = any(
                physical[edge.target_step] < physical[edge.source_step]
                for edge in continuation.edges
            )
            caption = (
                (
                    "Text-located continuation: "
                    + f"{len(continuation.pages)}"
                    + " physical PDF pages and "
                    + f"{len(continuation.edges)}"
                    + " witnessed reading transitions; "
                )
                + (
                    "printed labels are retained separately. Regi"
                    + "on ownership is not geometry-verified. "
                )
                + (
                    "The witnessed reading order includes a backward physical-page jump."
                    if backward
                    else (
                        "The graph records the supplied reading seque"
                        + "nce, not a complete article interval."
                    )
                )
            )
        metadata = json.dumps(
            {
                "presentation_method": "study-briefing-1",
                "presentation_sha256": method,
                "input_record_sha256": input_sha,
                "page_number": index,
                "declared_red_focus": page.focus,
                "measurement_epoch": (
                    "inherited from supplied bound observations; "
                    + "never recomputed by presentation"
                ),
                "supplied_observations": data.model_dump(),
                "optional_continuation_witness": continuation.model_dump()
                if continuation is not None
                else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        figures.append(
            StudyFigure(
                name=f"briefing-abstract-{index:02d}", svg=canvas(page, metadata), caption=caption
            )
        )
    if implementation_digest() != method:
        raise StudyError("briefing presentation source changed during authoring")
    return tuple(figures)
