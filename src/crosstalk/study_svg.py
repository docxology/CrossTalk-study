"""Small escaped vector primitives and bounded, fully retained scientific captions."""

from __future__ import annotations

import json
import textwrap
from html import escape
from typing import TYPE_CHECKING

from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from crosstalk.study_language_records import LanguageRun


def text(position: tuple[float, float], value: str, size: int = 18) -> str:
    """Escape every displayed label before placing it in inert vector text."""
    return (
        f'<text x="{position[0]:.2f}" y="{position[1]:.2f}" font-size="{size}">'
        + escape(value)
        + "</text>"
    )


def canvas(title: str, body: str, metadata: str) -> str:
    """Compose a fixed print-ready page and escape its complete provenance metadata."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="680" '
        + 'viewBox="0 0 1000 680"><metadata>'
        + escape(metadata)
        + '</metadata><rect width="1000" height="680" fill="#faf8f1"/>'
        + '<g font-family="Helvetica,Arial,sans-serif" fill="#132c42">'
        + text((40, 48), title, 28)
        + body
        + "</g></svg>"
    )


def footer(caption: str) -> str:
    """Refuse oversized captions rather than silently discard interpretive limitations."""
    lines = textwrap.wrap(caption, width=114)
    if len(lines) > 4:
        raise StudyError("figure caption exceeds its bounded four-line footer")
    return "".join(text((40, 600 + index * 21), line, 16) for index, line in enumerate(lines))


def language_metadata(run: LanguageRun) -> str:
    """Serialize input, method and settings identity without embedding journal content."""
    return json.dumps(
        {
            "input_sha256": run.input_sha256,
            "implementation_sha256": run.implementation_sha256,
            "settings": run.settings.model_dump(),
            "method_version": run.method_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
