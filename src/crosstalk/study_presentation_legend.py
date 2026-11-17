"""Exact source-bound color-word legend amendments retain every numeric/data annotation."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final

from crosstalk.study_language_records import StudyError
from crosstalk.study_presentation_xml import local

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET

    from crosstalk.study_presentation_records import LegendEdit, SvgPresentation

WORDS: Final = re.compile(
    r"\b(Teal|Coral|Pale|Blue|Green|Orange|Purple|Navy|Red|Black|Gray)\b", re.IGNORECASE
)
CLAUSE: Final = re.compile(
    ("\\b(Teal|Coral|Pale|Blue|Green|Orange|Purple|" + "Navy|Red|Black|Gray)\\s*:\\s*"),
    re.IGNORECASE,
)
TARGET_NAMES: Final = {"#000000": "Black", "#777777": "Gray", "#b00020": "Red"}


def _amend(edit: LegendEdit, mapping: tuple[tuple[str, str, str], ...]) -> str:
    """Only exact indexed color-word tokens may differ; all other original bytes are retained."""
    if hashlib.sha256(edit.original_text.encode()).hexdigest() != edit.original_text_sha256:
        raise StudyError("approved source legend text digest differs")
    targets = {channel: TARGET_NAMES[target] for channel, _, target in mapping}
    changes: list[tuple[int, int, str]] = []
    for replacement in edit.replacements:
        if replacement.channel not in targets:
            raise StudyError("annotation color replacement names an undeclared channel")
        hits = tuple(
            re.finditer(r"\b" + re.escape(replacement.old_word) + r"\b", edit.original_text)
        )
        if replacement.occurrence >= len(hits):
            raise StudyError("approved source color-word occurrence is absent")
        hit = hits[replacement.occurrence]
        changes.append((hit.start(), hit.end(), targets[replacement.channel]))
    if len({start for start, _, _ in changes}) != len(changes):
        raise StudyError("approved source color-word occurrence is repeated")
    result = edit.original_text
    for start, end, word in sorted(changes, reverse=True):
        result = result[:start] + word + result[end:]
    if result != edit.expected_text:
        raise StudyError(
            "approved legend amendment changes more than " + "its permitted color words"
        )
    return result


def amend_legends(
    root: ET.Element, request: SvgPresentation, mapping: tuple[tuple[str, str, str], ...]
) -> None:
    """Apply exact approved annotation edits before checking node fingerprints."""
    nodes = tuple(
        node
        for node in root.iter()
        if local(node.tag) in {"text", "tspan"} and node.text is not None
    )
    for edit in request.annotation_edits:
        if (
            edit.text_node_index >= len(nodes)
            or nodes[edit.text_node_index].text != edit.original_text
        ):
            raise StudyError("approved source legend node location/text differs")
        nodes[edit.text_node_index].text = _amend(edit, mapping)
    targets = {channel: TARGET_NAMES[target].casefold() for channel, _, target in mapping}
    for node in root.iter():
        if local(node.tag) not in {"text", "tspan"}:
            continue
        for text in (node.text or "", node.tail or ""):
            colors, clauses = tuple(WORDS.finditer(text)), tuple(CLAUSE.finditer(text))
            if len(colors) != len(clauses):
                raise StudyError(
                    "semantic color prose outside an explicit col" + "or-role legend needs a redraw"
                )
            for index, clause in enumerate(clauses):
                end = clauses[index + 1].start() if index + 1 < len(clauses) else len(text)
                description = text[clause.end() : end]
                roles = tuple(
                    channel for channel in request.channels if channel.legend_text in description
                )
                if len(roles) != 1 or clause.group(1).casefold() != targets[roles[0].channel]:
                    raise StudyError(
                        "source color-name legend disagrees with the presented channel role"
                    )
