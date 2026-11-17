"""Four distinct source-bound vector abstracts; no corpus discovery or invented current results."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pydantic

from crosstalk.study_graphical_evidence import literature_page, visual_page
from crosstalk.study_graphical_svg import canvas
from crosstalk.study_graphical_text import corpus_page, language_page
from crosstalk.study_language_records import StudyError, StudyFigure

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractInputs

IMPLEMENTATION_FILES: Final = (
    "study_graphical_abstracts.py",
    "study_graphical_records.py",
    "study_graphical_svg.py",
    "study_graphical_labels.py",
    "study_graphical_text.py",
    "study_graphical_evidence.py",
    "study_language_records.py",
)


def implementation_digest() -> str:
    """Frame actual method members and validation/wrapping runtime identities canonically."""
    directory = Path(__file__).parent
    members: list[tuple[str, int, str]] = []
    for name in IMPLEMENTATION_FILES:
        raw = (directory / name).read_bytes()
        members.append((name, len(raw), hashlib.sha256(raw).hexdigest()))
    context = (members, sys.version, unicodedata.unidata_version, pydantic.__version__)
    return hashlib.sha256(json.dumps(context, separators=(",", ":")).encode()).hexdigest()


def graphical_abstracts(data: AbstractInputs) -> tuple[StudyFigure, ...]:
    """Author four abstracts from caller-admitted measurements."""
    method = implementation_digest()
    input_sha = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    captions = (
        (
            "Captured NPS and separate publisher frames; "
            + "catalog-issued distribution and source-witne"
            + "ssed historical limits. No expected historic"
            + "al issue census is assumed."
        ),
        (
            "Native and accepted OCR are overlapping obse"
            + "rvations kept separate. Operational OCR outc"
            + "omes, native selection frames and equal-wind"
            + "ow diversity retain their own denominators."
        ),
        (
            "Whole-page appearance and native-layout insp"
            + "ection retain measured, refused, failed and "
            + "unattempted states. Missing native typograph"
            + "y is not missing printed content; descriptor"
            + "s carry no semantic labels."
        ),
        (
            "Discovery, source localization and article a"
            + "ppraisal are different evidence stages. Sele"
            + "cted source-checked examples do not establis"
            + "h an article census or measured human agreem"
            + "ent."
        ),
    )
    figures: list[StudyFigure] = []
    factories = (corpus_page, language_page, visual_page, literature_page)
    for number, (factory, caption) in enumerate(zip(factories, captions, strict=True), 1):
        page = factory(data)
        metadata = json.dumps(
            {
                "method_version": "study-graphical-abstracts-3",
                "page_number": number,
                "input_record_sha256": input_sha,
                "implementation_sha256": method,
                "source_admission": "caller-required; authoring does not verify scientific custody",
                "supplied_observations": data.model_dump(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        figures.append(
            StudyFigure(
                name=f"graphical-abstract-{number:02d}", caption=caption, svg=canvas(page, metadata)
            )
        )
    if implementation_digest() != method:
        raise StudyError("graphical abstract method changed during authoring")
    return tuple(figures)
