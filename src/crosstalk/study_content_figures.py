"""Print-ready vector summaries of disclosed term screens and adjacent-pair sensitivity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from crosstalk.study_language_records import StudyError, StudyFigure
from crosstalk.study_svg import canvas, footer, text

if TYPE_CHECKING:
    from crosstalk.study_content_records import ContentLayer, ContentRun
    from crosstalk.study_language_records import Layer


def _layer(run: ContentRun, layer: Layer) -> ContentLayer:
    selected = tuple(row for row in run.layers if row.layer == layer)
    if len(selected) != 1:
        raise StudyError("content figure layer is absent or ambiguous")
    return selected[0]


def _metadata(run: ContentRun, view_label: str) -> str:
    directory = Path(__file__).parent
    files = ("study_content_figures.py", "study_svg.py", "study_language_records.py")
    if len(view_label) > 50 or "\n" in view_label:
        raise StudyError("content figure selection label exceeds its one-line layout")
    return json.dumps(
        {
            "source_frame_sha256": run.unit_frame_sha256,
            "supplied_selection_label": view_label,
            "content_implementation_sha256": run.implementation_sha256,
            "content_run_record_sha256": hashlib.sha256(run.model_dump_json().encode()).hexdigest(),
            "figure_source_files": tuple(
                (name, hashlib.sha256((directory / name).read_bytes()).hexdigest())
                for name in files
            ),
            "settings": run.settings.model_dump(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def content_frequency_figure(
    run: ContentRun, layer: Layer, view_label: str = "Supplied source units"
) -> StudyFigure:
    """Show token rates, issue prevalence and concentration after display screening."""
    measured = _layer(run, layer)
    rows = measured.terms[:12]
    maximum = max((row.frequency.per_1000_tokens for row in rows), default=1.0)
    body = [
        text((40, 86), view_label),
        text(
            (40, 115),
            (
                f"{layer}"
                + ": "
                + f"{measured.tokens:,}"
                + " full tokens; "
                + f"{measured.positive_token_issues}"
                + " positive-token issues"
            ),
        ),
        text(
            (40, 145),
            (
                f"{measured.screened_terms:,}"
                + " terms passed disclosed display screen; show"
                + "ing "
                + f"{len(rows)}"
                + " by count"
            ),
            17,
        ),
        text((300, 175), "Per 1,000 full tokens", 16),
        text((655, 175), "Issue matches/N", 16),
        text((860, 175), "Max issue share", 16),
    ]
    for index, row in enumerate(rows):
        term = row.frequency
        y = 208 + index * 31
        body.extend(
            (
                text((40, y), term.term),
                (
                    '<rect x="300" y="'
                    + f"{y - 17}"
                    + '" width="'
                    + f"{220 * term.per_1000_tokens / maximum:.2f}"
                    + '" height="21" fill="#117f83"/>'
                ),
                text((530, y), f"{term.per_1000_tokens:.2f}", 16),
                (
                    '<rect x="655" y="'
                    + f"{y - 17}"
                    + '" width="'
                    + f"{100 * term.issue_prevalence:.2f}"
                    + '" height="21" fill="#cf684e"/>'
                ),
                text((765, y), f"{term.observed_issues}/{term.eligible_issues}", 16),
                text((885, y), f"{100 * row.maximum_issue_count_share:.1f}%", 16),
            )
        )
    if not rows:
        body.append(text((40, 220), "No terms passed the declared display screen."))
    caption = (
        ("Display only: explicit " + f"{len(run.settings.stoplist)}" + "-entry stoplist; lengths ")
        + (
            f"{run.settings.minimum_characters}"
            + "-"
            + f"{run.settings.maximum_display_characters}"
            + "; at least "
        )
        + (
            f"{run.settings.minimum_issue_support}"
            + " matched issues. Full token denominators are"
            + " unchanged. "
        )
        + (
            "Max issue share is a term's largest single-i"
            + "ssue count fraction. No semantic or accuracy"
            + " labels."
        )
    )
    return StudyFigure(
        name="content-terms-" + layer,
        caption=caption,
        svg=canvas(
            "Term frequency, prevalence and concentration",
            "".join(body) + footer(caption),
            _metadata(run, view_label),
        ),
    )


def adjacent_pair_figure(
    run: ContentRun, layer: Layer, view_label: str = "Supplied source units"
) -> StudyFigure:
    """Plot pair counts/support and deletion ranges without interpreting them as inference."""
    measured = _layer(run, layer)
    rows = measured.pairs[:12]
    values = tuple(
        value
        for row in rows
        for value in (
            row.log_dice,
            row.leave_one_issue_out_log_dice_min,
            row.leave_one_issue_out_log_dice_max,
        )
        if value is not None
    )
    lower, upper = min(values, default=0.0), max(values, default=1.0)
    if lower == upper:
        lower, upper = lower - 0.5, upper + 0.5

    def point(value: float) -> float:
        return 750 + 185 * (value - lower) / (upper - lower)

    body = [
        text((40, 86), view_label),
        text(
            (40, 115),
            (
                f"{layer}"
                + ": "
                + f"{measured.pair_opportunities:,}"
                + " full within-unit pair opportunities; "
                + f"{measured.eligible_pair_issues}"
                + " eligible issues"
            ),
        ),
        text(
            (40, 145),
            (
                f"{measured.screened_pairs:,}"
                + " pairs passed display screen; showing "
                + f"{len(rows)}"
                + " by count"
            ),
            17,
        ),
        text((540, 175), "Count", 16),
        text((625, 175), "Issues/N", 16),
        text((750, 175), "LogDice + deletion range", 16),
    ]
    for index, row in enumerate(rows):
        y = 208 + index * 31
        body.extend(
            (
                text((40, y), row.left + " → " + row.right, 16),
                text((540, y), f"{row.count:,}", 16),
                text((625, y), f"{row.observed_issues}/{row.eligible_pair_issues}", 16),
            )
        )
        if (
            row.leave_one_issue_out_log_dice_min is not None
            and row.leave_one_issue_out_log_dice_max is not None
        ):
            body.append(
                '<line x1="'
                + f"{point(row.leave_one_issue_out_log_dice_min):.2f}"
                + '" x2="'
                + f"{point(row.leave_one_issue_out_log_dice_max):.2f}"
                + '" y1="'
                + f"{y - 5}"
                + '" y2="'
                + f"{y - 5}"
                + '" stroke="#117f83" stroke-width="4"/>'
            )
        body.append(
            '<circle cx="'
            + f"{point(row.log_dice):.2f}"
            + '" cy="'
            + f"{y - 5}"
            + '" r="5" fill="#cf684e"/>'
        )
    body.extend((text((750, 580), f"{lower:.2f}", 15), text((905, 580), f"{upper:.2f}", 15)))
    if not rows:
        body.append(text((40, 220), "No adjacent pairs passed the declared display screen."))
    caption = (
        (
            "Count-ranked adjacent pairs restart at page/"
            + "region boundaries; full positional endpoints"
            + " "
        )
        + (
            "define LogDice. Lines remove each eligible i"
            + "ssue once and retain defined values only; "
        )
        + (
            "deletion N is in the data. These are sensiti"
            + "vity ranges, not confidence intervals. "
        )
        + (
            "The disclosed word/pair screen does not esta"
            + "blish linguistic or semantic relations."
        )
    )
    return StudyFigure(
        name="content-pairs-" + layer,
        caption=caption,
        svg=canvas(
            "Adjacent-pair association and issue support",
            "".join(body) + footer(caption),
            _metadata(run, view_label),
        ),
    )
