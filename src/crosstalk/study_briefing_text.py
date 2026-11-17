"""Direct source and language diagrams replace decorative summary cards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.study_briefing_svg import (
    BLACK,
    GRAY,
    LIGHT,
    BriefingPage,
    histogram,
    line,
    metric,
    number,
    section,
    years,
)
from crosstalk.study_graphical_svg import paragraph, text

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractInputs


def source_frame(data: AbstractInputs) -> BriefingPage:
    """Show captured-year density and separate source families."""
    scope = data.corpus
    body = ""
    values = (
        (scope.captured_catalog_rows, "CAPTURED NPS ROWS"),
        (scope.verified_pdf_sources, "VERIFIED PDF SOURCES"),
        (scope.physical_pages, "PHYSICAL PDF PAGES"),
        (scope.current_native_pages, "CURRENT NATIVE PAGES"),
    )
    for index, (count, label) in enumerate(values):
        left = 20 + index * 295
        body += metric((left, 106, 245, 135), count, label)
        if index < 3:
            body += line((left + 251, 160, left + 284, 160))
            body += (
                '<polygon points="'
                + f"{left + 278}"
                + ",155 "
                + f"{left + 288}"
                + ",160 "
                + f"{left + 278}"
                + ',165" fill="'
                + f"{BLACK}"
                + '"/>'
            )
    body += years((20, 266, 1160, 225), scope.catalog_years, scope.undated_catalog_rows)
    body += paragraph(
        (20, 500, 500, 58), f"SEPARATE PUBLISHER FRAME / {scope.publisher_cards} CARDS", 22
    )
    body += paragraph(
        (560, 500, 620, 58),
        (
            f"{scope.publisher_public_candidates}"
            + " public candidates / "
            + f"{scope.publisher_contact_only}"
            + " contact-only / "
            + f"{scope.publisher_verified_pdfs}"
            + " verified PDFs"
        ),
        20,
    )
    body += line((20, 565, 1180, 565), GRAY)
    body += paragraph(
        (20, 580, 550, 102),
        scope.historical_findings[0]
        if scope.historical_findings
        else ("Historical publication extent is not establi" + "shed by this captured frame."),
        22,
    )
    body += paragraph((630, 580, 550, 102), scope.publisher_note, 22)
    body += line((20, 689, 1180, 689))
    body += text(
        (20, 713),
        ("Catalog-year gaps = uncaptured rows. Expecte" + "d historical holdings remain unknown."),
        18,
    )
    return BriefingPage("01 / SOURCE FRAME", "captured NPS source frame", body, 720)


def language(data: AbstractInputs) -> BriefingPage:
    """Use observed physical-page denominators and retain native/OCR channel separation."""
    scope = data.language
    body = metric(
        (20, 111, 550, 145),
        scope.native.tokens,
        (
            "NATIVE TOKENS / "
            + f"{scope.native.supplied_units:,}"
            + " physical pages / "
            + f"{scope.native.observed_issues}"
            + " issues"
        ),
    )
    body += metric(
        (630, 111, 550, 145),
        scope.ocr.tokens,
        (
            "ACCEPTED OCR TOKENS / "
            + f"{scope.ocr.supplied_units:,}"
            + " physical pages / "
            + f"{scope.ocr.observed_issues}"
            + " issues"
        ),
    )
    body += paragraph((20, 271, 1160, 57), scope.normalization_note, 20)
    body += section((20, 354), "OCR WORKLOAD / PHYSICAL PAGES") + line((20, 369, 1180, 369))
    work = scope.ocr_workload
    values = (
        ("ORIGINAL", work.total_physical_pages),
        ("UNTARGETED", work.untargeted_pages),
        ("TARGETED", work.targeted_pages),
        ("PRODUCED", work.produced_pages),
        ("ACCEPTED EMPTY", work.accepted_empty_pages),
        ("FAILED", work.failed_pages),
    )
    for index, (label, count) in enumerate(values):
        left = 20 + index * 195
        body += number((left, 416), count, 36) + paragraph((left, 429, 175, 50), label, 18)
    total = work.total_physical_pages
    at = 20.0
    for count, fill in (
        (work.produced_pages, BLACK),
        (work.accepted_empty_pages, GRAY),
        (work.failed_pages, "url(#brief-failed)"),
        (work.untargeted_pages, LIGHT),
    ):
        span = 1160 * count / total if total else 0.0
        body += (
            '<rect x="'
            + f"{at:.2f}"
            + '" y="492" width="'
            + f"{span:.2f}"
            + '" height="16" fill="'
            + f"{fill}"
            + '" stroke="'
            + f"{BLACK}"
            + '" stroke-width="0.5"/>'
        )
        at += span
    body += section((20, 535), "NATIVE SELECTION FRAMES / SUBSETS, NOT ADDITIVE CORPORA")
    for index, view in enumerate(scope.native_views):
        left = 20 + index * 395
        body += paragraph((left, 550, 370, 50), view.label, 18)
        body += number((left, 624), view.tokens, 28)
        body += text((left + 260, 624), "TOKENS", 18)
        body += text(
            (left, 651),
            (
                f"{view.units:,}"
                + " pages / "
                + f"{view.positive_token_issues}"
                + " positive issues"
            ),
            18,
        )
    if not scope.native_views:
        body += text((20, 604), "No additional native selection frame supplied.", 20)
    body += histogram((20, 673, 550, 385), scope.native.diversity)
    body += histogram((630, 673, 550, 385), scope.ocr.diversity)
    body += text(
        (20, 1084),
        (
            "Native and OCR overlap physically. Tokenless"
            + " pages and short-window exclusions are disti"
            + "nct states."
        ),
        18,
    )
    return BriefingPage("02 / LANGUAGE", "accepted OCR channel", body, 1100)
