"""Deterministic vector plates for measured text layers and native-layout observations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from crosstalk.study_language_records import StudyError, StudyFigure
from crosstalk.study_svg import canvas as _svg
from crosstalk.study_svg import footer as _footer
from crosstalk.study_svg import language_metadata as _language_metadata
from crosstalk.study_svg import text as _text

if TYPE_CHECKING:
    from crosstalk.study_language_records import ContrastResult, LanguageRun, Layer, LayerMeasure
    from crosstalk.study_layout_records import PageLayout


def _layer(run: LanguageRun, layer: Layer) -> LayerMeasure:
    selected = tuple(row for row in run.layers if row.layer == layer)
    if len(selected) != 1:
        raise StudyError("figure text layer is absent or ambiguous")
    return selected[0]


def frequency_figure(run: LanguageRun, layer: Layer) -> StudyFigure:
    """Compare frequency with issue prevalence; do not confuse a long issue with many issues."""
    measure = _layer(run, layer)
    selected = measure.frequencies[:12]
    maximum = max((row.per_1000_tokens for row in selected), default=1.0)
    body = [
        _text(
            (40, 86),
            f"{layer}: {measure.tokens:,} tokens; {measure.eligible_issues} positive-token issues",
        ),
        _text((310, 118), "Occurrences per 1,000 tokens"),
        _text((705, 118), "Issues with a match / eligible"),
    ]
    for index, row in enumerate(selected):
        y = 154 + index * 35
        body.extend(
            (
                _text((40, y), row.term[:24]),
                f'<rect x="310" y="{y - 18}" '
                + f'width="{280 * row.per_1000_tokens / maximum:.2f}" '
                + 'height="22" fill="#117f83"/>',
                _text((600, y), f"{row.per_1000_tokens:.2f}", 16),
                f'<rect x="710" y="{y - 18}" width="{170 * row.issue_prevalence:.2f}" '
                + 'height="22" fill="#cf684e"/>',
                _text((890, y), f"{row.observed_issues}/{row.eligible_issues}", 16),
            )
        )
    if not selected:
        body.append(_text((40, 190), "No positive-token frequency observations."))
    caption = (
        "Observed supplied text; no stopword exclusion. "
        + "Issue prevalence uses positive-token issues. "
        + "Native/OCR remain separate; article identity, reading order and accuracy require "
        + "external verification."
    )
    return StudyFigure(
        name=f"language-frequency-{layer}",
        caption=caption,
        svg=_svg(
            "Frequency and issue dispersion",
            "".join(body) + _footer(caption),
            _language_metadata(run),
        ),
    )


def diversity_figure(run: LanguageRun, layer: Layer) -> StudyFigure:
    """Show unit mean fixed-window diversity with every insufficient unit explicitly counted."""
    measure = _layer(run, layer)
    available = tuple(row for row in measure.units if row.mean_window_ttr is not None)
    bins = [0] * 10
    for row in available:
        value = row.mean_window_ttr
        if value is not None:
            bins[min(9, int(value * 10))] += 1
    maximum = max(bins, default=0) or 1
    body = [
        _text(
            (40, 90),
            f"{layer}: {len(available)} eligible units / {len(measure.units)} supplied; "
            + f"{run.settings.window_tokens}-token complete windows",
        ),
        _text(
            (40, 120),
            f"{sum(row.complete_windows for row in measure.units):,} windows; "
            + f"{sum(row.discarded_tokens for row in measure.units):,} tail tokens excluded",
        ),
    ]
    for index, count in enumerate(bins):
        height = 330 * count / maximum
        body.extend(
            (
                f'<rect x="{100 + index * 80}" y="{500 - height:.2f}" width="60" '
                + f'height="{height:.2f}" fill="#117f83"/>',
                _text((100 + index * 80, 532), f"{index / 10:.1f}", 16),
                _text((110 + index * 80, 485 - height), str(count), 16),
            )
        )
    caption = (
        "Each bar counts source units by mean type/token ratio of complete disjoint windows. "
        + "Windows restart at supplied unit boundaries. Short units are unavailable, "
        + "not zero-diversity observations."
    )
    return StudyFigure(
        name=f"language-diversity-{layer}",
        caption=caption,
        svg=_svg(
            "Equal-length lexical diversity",
            "".join(body) + _footer(caption),
            _language_metadata(run),
        ),
    )


def contrast_figure(result: ContrastResult) -> StudyFigure:
    """Display marginal conditional effect intervals alongside explicitly bounded cohorts."""
    selected = result.terms[:12]
    extent = (
        max(
            (
                abs(value)
                for row in selected
                for value in (row.lower, row.upper, row.log2_rate_ratio)
                if value is not None
            ),
            default=1.0,
        )
        or 1.0
    )
    body = [
        _text(
            (40, 86),
            f"{result.plan.name}: {result.plan.layer}; eligible issues "
            + f"A={len(result.eligible_a)}, B={len(result.eligible_b)}",
        ),
        _text(
            (40, 116),
            f"{result.tested_vocabulary:,} screened terms; shown by G² rank; "
            + "counts A:B; no token p-values",
        ),
        '<line x1="680" y1="132" x2="680" y2="570" stroke="#9ca9ad"/>',
    ]
    for index, row in enumerate(selected):
        y = 160 + index * 34
        x = 680 + row.log2_rate_ratio / extent * 240
        body.append(_text((40, y + 6), row.term[:26]))
        if row.lower is not None and row.upper is not None:
            body.append(
                f'<line x1="{680 + row.lower / extent * 240:.2f}" '
                + f'x2="{680 + row.upper / extent * 240:.2f}" y1="{y}" y2="{y}" '
                + 'stroke="#117f83" stroke-width="4"/>'
            )
        body.append(f'<circle cx="{x:.2f}" cy="{y}" r="6" fill="#cf684e"/>')
        body.append(_text((290, y + 6), f"{row.count_a:,}:{row.count_b:,}", 14))
    body.append(_text((420, 582), "log₂ token-rate ratio A/B; zero = equal rates", 17))
    denominators = (
        f"Token denominators A={selected[0].tokens_a:,}, B={selected[0].tokens_b:,}. "
        if selected
        else ""
    )
    caption = (
        denominators
        + "Points: binary-smoothed log2 rate ratios. Lines: nominal marginal 95% whole-issue "
        + "bootstrap diagnostics; absent lines indicate the cluster gate was unmet. "
        + "Exploratory; unadjusted for vocabulary selection, multiplicity or temporal dependence."
    )
    metadata = json.dumps(
        {
            "plan_sha256": result.plan_sha256,
            "input_sha256": result.language_input_sha256,
            "implementation_sha256": result.implementation_sha256,
            "plan": result.plan.model_dump(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return StudyFigure(
        name="language-keyness",
        caption=caption,
        svg=_svg("Exploratory lexical contrast", "".join(body) + _footer(caption), metadata),
    )


def layout_figure(page: PageLayout) -> StudyFigure:
    """Plot observed line geometry; printed meaning and reading order are not inferred."""
    frame = page.unrotated_frame
    scale = min(480 / (frame.x1 - frame.x0), 430 / (frame.y1 - frame.y0))
    body = [
        _text(
            (40, 87),
            f"Physical page index {page.page_index}; rotation {page.rotation}°; {page.text_status}",
        ),
        f'<rect x="60" y="130" width="{frame.x1 * scale:.2f}" '
        + f'height="{frame.y1 * scale:.2f}" fill="white" stroke="#132c42"/>',
    ]
    for line in page.lines[:2000]:
        left, top, right, bottom = line.bbox
        left, top = max(0.0, left), max(0.0, top)
        right, bottom = min(frame.x1, right), min(frame.y1, bottom)
        if right > left and bottom > top:
            body.append(
                f'<rect x="{60 + left * scale:.2f}" y="{130 + top * scale:.2f}" '
                + f'width="{(right - left) * scale:.2f}" '
                + f'height="{(bottom - top) * scale:.2f}" '
                + 'fill="none" stroke="#117f83" stroke-width="0.6"/>'
            )
    body.extend(
        (
            _text((580, 155), f"{len(page.lines):,} observed native lines"),
            _text((580, 190), f"{len(page.fonts)} reported font/size/flag groups"),
            _text((580, 225), f"{len(page.column_start_candidates)} repeated-start candidates"),
            _text((580, 260), f"Span union: {page.union_status}"),
            _text((580, 295), f"Outside-frame spans: {page.spans_outside_frame}"),
        )
    )
    caption = (
        "Native line map (up to 2,000 lines). Repeated starts can be indentation; "
        + "font flags are reported metadata. "
        + "No-native-spans is missing native typography, not an absence of printed text."
    )
    metadata = json.dumps(
        {
            "pdf_sha256": page.pdf_sha256,
            "page_index": page.page_index,
            "implementation_sha256": page.implementation_sha256,
            "pymupdf_version": page.pymupdf_version,
            "settings": page.settings.model_dump(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return StudyFigure(
        name=f"layout-page-{page.page_index:03d}",
        caption=caption,
        svg=_svg(
            "Native typography and layout observations", "".join(body) + _footer(caption), metadata
        ),
    )
