"""Project-owned Markdown and TeX composition; native Template remains the PDF renderer."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never

from crosstalk.template_inventory import latex
from crosstalk.template_records import Artifact, ProjectionError

TOKEN: Final = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


class Target(StrEnum):
    """Authored source contexts require different escaping."""

    MARKDOWN = "markdown"
    YAML = "yaml"


@dataclass(frozen=True, slots=True)
class TokenValue:
    """Only generator-owned structural fragments bypass plain-text escaping."""

    key: str
    value: str
    structural: bool = False


@dataclass(frozen=True, slots=True)
class Figure:
    """A pinned source asset and its immutable project-local render path."""

    source: Artifact
    path: str


def markdown(value: str) -> str:
    """Prevent plain source metadata from becoming Markdown, math or raw HTML."""
    return "".join("\\" + char if char in r"\`*_{}[]<>#$|^~" else char for char in value)


def substitute(source: str, values: tuple[TokenValue, ...], target: Target) -> str:
    """Every live source token must have exactly one explicitly supplied value."""
    mapping = {row.key: row for row in values}
    if len(mapping) != len(values):
        raise ProjectionError("provided/generated token names collide")

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        row = mapping.get(key)
        if row is None:
            raise ProjectionError("manuscript contains an unprovided variable: " + key)
        match target:
            case Target.MARKDOWN:
                return row.value if row.structural else markdown(row.value)
            case Target.YAML:
                if row.structural:
                    raise ProjectionError("structural manuscript fragment cannot enter YAML")
                return json.dumps(row.value, ensure_ascii=False)[1:-1]
            case _:
                assert_never(target)

    return TOKEN.sub(replace, source)


def graphical_frontmatter(figures: tuple[Figure, ...]) -> str:
    """The native cover owns GA01; three TeX pages precede the original native contents macro.

    This is manuscript input, not a PDF override or a pre-rendered book. Physical page positions
    must still pass the real Template/XeLaTeX render check.
    """
    if len(figures) != 4:
        raise ProjectionError("graphical front matter requires four declared figures")
    lines: list[str] = []
    for index, figure in enumerate(figures[1:], 2):
        lines.extend(
            (
                r"\thispagestyle{empty}",
                r"\noindent{\small\ttfamily CROSSTALK / 0"
                + str(index)
                + r"\hfill GRAPHICAL ABSTRACT}\par",
                r"\vspace{0.3em}\hrule\vspace{0.6em}",
                r"\begin{center}",
                r"\includegraphics[width=\textwidth,height=.83\textheight,keepaspectratio]"
                + r"{\detokenize{"
                + figure.path
                + "}}",
                r"\par\vspace{0.6em}",
                r"\begin{minipage}{\textwidth}",
                r"\small\sffamily " + latex(figure.source.caption),
                r"\end{minipage}",
                r"\end{center}",
                r"\clearpage",
                "",
            )
        )
    return "\n".join(lines)


def body_figures(figures: tuple[Figure, ...]) -> str:
    """Render declared figures and captions; full source hashes remain in the build manifest."""
    lines: list[str] = []
    for figure in figures:
        lines.extend(
            (
                "## " + markdown(figure.source.title),
                "",
                "!["
                + markdown(figure.source.caption)
                + "]("
                + figure.path
                + ")"
                + "{#fig:"
                + figure.source.key
                + " width=100%}",
                "",
                r"\clearpage",
                "",
            )
        )
    return "\n".join(lines)
