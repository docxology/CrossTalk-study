"""Hydrate manuscript quantities and references before document layout."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from crosstalk.dossier_records import DossierSection
from crosstalk.models import AcquisitionError

if TYPE_CHECKING:
    from pathlib import Path

HEADING: Final = re.compile(r"^#{1,6}\s+(.+?)(?:\s+\{[^}]+\})?$")
CITATION: Final = re.compile(r"\[@([^\]]+)\]")
VARIABLE: Final = re.compile(r"\{\{([A-Z_]+)\}\}")
LINK: Final = re.compile(r"\[([^\]]+)\]\([^)]*\)")
PUNCTUATION: Final = str.maketrans(
    {
        "\u2013": "-",
        "\u2014": "-",
        "\u2011": "-",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
)


def manuscript_sections(
    paths: tuple[Path, ...], replacements: dict[str, str], citations: dict[str, str]
) -> tuple[DossierSection, ...]:
    """Read headings and paragraphs without leaving unresolved scientific tokens."""
    sections: list[DossierSection] = []
    for path in paths:
        title = path.stem
        paragraphs: list[str] = []
        pending: list[str] = []
        for raw in (*path.read_text(encoding="utf-8").splitlines(), ""):
            heading = HEADING.fullmatch(raw)
            if not raw.strip() or heading:
                if pending:
                    paragraphs.append(_hydrate(" ".join(pending), replacements, citations))
                    pending = []
                if heading:
                    if paragraphs:
                        sections.append(DossierSection(title=title, paragraphs=tuple(paragraphs)))
                        paragraphs = []
                    title = _hydrate(heading.group(1), replacements, citations)
                continue
            if raw.startswith("|"):
                cells = [cell.strip() for cell in raw.strip("|").split("|")]
                if not all(re.fullmatch(r"[: -]+", cell) for cell in cells):
                    paragraphs.append(_hydrate(" | ".join(cells), replacements, citations))
            else:
                pending.append(raw.strip())
        if paragraphs:
            sections.append(DossierSection(title=title, paragraphs=tuple(paragraphs)))
    return tuple(sections)


def _hydrate(text: str, replacements: dict[str, str], citations: dict[str, str]) -> str:
    """Refuse missing substitutions rather than printing placeholders as evidence."""

    def variable(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in replacements:
            raise AcquisitionError(f"Unresolved manuscript quantity: {key}")
        return replacements[key]

    def citation(match: re.Match[str]) -> str:
        keys = [key.strip().removeprefix("@") for key in match.group(1).split(";")]
        missing = set(keys).difference(citations)
        if missing:
            raise AcquisitionError(
                "Unresolved manuscript references: " + ", ".join(sorted(missing))
            )
        return "(" + "; ".join(citations[key] for key in keys) + ")"

    value = VARIABLE.sub(variable, text)
    value = CITATION.sub(citation, value)
    value = LINK.sub(r"\1", value)
    return value.replace("**", "").replace("`", "").translate(PUNCTUATION)
