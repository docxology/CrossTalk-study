"""Corpus/historical and language/OCR abstract pages use distinct evidence flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.study_graphical_svg import (
    CORAL,
    TEAL,
    Drawing,
    arrow,
    histogram,
    panel,
    paragraph,
    stat,
    text,
    years,
)

if TYPE_CHECKING:
    from crosstalk.study_graphical_records import AbstractInputs


def corpus_page(data: AbstractInputs) -> Drawing:
    """Show captured sources and unknown historical coverage."""
    source = data.corpus
    body = paragraph(
        (40, 82, 1120, 62),
        (
            "Originals, metadata and derivatives stay lin"
            + "ked; captured holdings are not an expected h"
            + "istorical census."
        ),
        24,
    )
    body += stat((40, 150, 230, 145), source.captured_catalog_rows, "Captured NPS metadata rows")
    body += stat((315, 150, 230, 145), source.verified_pdf_sources, "Verified PDF sources")
    body += stat((590, 150, 230, 145), source.physical_pages, "Physical PDF pages")
    body += arrow((272, 225), (310, 225)) + arrow((547, 225), (585, 225))
    body += panel((855, 150, 305, 185), "Separate publisher frame")
    for index, row in enumerate(
        (
            f"{source.publisher_cards} cards",
            f"{source.publisher_public_candidates} public candidates",
            f"{source.publisher_contact_only} contact-only",
            f"{source.publisher_verified_pdfs} verified PDFs",
        )
    ):
        body += paragraph((873, 223 + index * 28, 269, 28), row, 22)
    body += paragraph(
        (40, 310, 800, 65),
        (
            "Current native extraction: "
            + f"{source.current_native_pages:,}"
            + " physical pages. Historical expected holding"
            + "s: unknown."
        ),
        24,
    )
    body += years((40, 386, 1120, 190), source.catalog_years, source.undated_catalog_rows)
    note = (
        source.historical_findings[0]
        if source.historical_findings
        else "No additional historical finding supplied in this snapshot."
    )
    witness = (
        f"Historical witness: 1 of {len(source.historical_findings)} shown"
        if source.historical_findings
        else "Historical witness: unavailable"
    )
    body += text((40, 596), witness, 22)
    body += paragraph((40, 601, 535, 89), note, 22)
    body += text((625, 596), "Publisher access / preservation", 22)
    body += paragraph((625, 601, 535, 89), source.publisher_note, 22)
    body += paragraph(
        (40, 694, 1120, 23),
        ("Empty catalog-year bars mean no captured row" + "s, not proof of a missing issue."),
        18,
    )
    return Drawing("01 Corpus: captured sources and historical limits", body, 720)


def language_page(data: AbstractInputs) -> Drawing:
    """Separate native/OCR observations and operational coverage."""
    scope = data.language
    native, ocr, workload = scope.native, scope.ocr, scope.ocr_workload
    body = paragraph((40, 87, 1120, 60), scope.normalization_note, 22)
    body += stat(
        (40, 158, 540, 165),
        native.tokens,
        (
            "Native: "
            + f"{native.supplied_units:,}"
            + " physical pages / "
            + f"{native.observed_issues}"
            + " issues; "
            + f"{native.zero_token_units:,}"
            + " tokenless pages"
        ),
    )
    body += stat(
        (620, 158, 540, 165),
        ocr.tokens,
        (
            "Accepted OCR: "
            + f"{ocr.supplied_units:,}"
            + " physical pages / "
            + f"{ocr.observed_issues}"
            + " issues; "
            + f"{ocr.zero_token_units:,}"
            + " tokenless pages"
        ),
    )
    body += panel(
        (40, 347, 1120, 138), "OCR is targeted coverage; operational success is not accuracy"
    )
    body += text(
        (58, 418),
        (
            "Targeted "
            + f"{workload.targeted_pages:,}"
            + " / "
            + f"{workload.total_physical_pages:,}"
            + " physical pages; untargeted "
            + f"{workload.untargeted_pages:,}"
        ),
        22,
    )
    values = (
        ("Produced", workload.produced_pages, TEAL),
        ("Accepted empty", workload.accepted_empty_pages, "#888888"),
        ("Failed", workload.failed_pages, CORAL),
    )
    at = 58.0
    for _, count, color in values:
        span = 1084 * count / workload.targeted_pages if workload.targeted_pages else 0.0
        body += (
            '<rect x="'
            + f"{at:.2f}"
            + '" y="426" width="'
            + f"{span:.2f}"
            + '" height="18" fill="'
            + f"{color}"
            + '"/>'
        )
        at += span
    for index, (label, count, color) in enumerate(values):
        left = 58 + index * 355
        body += f'<circle cx="{left + 5}" cy="464" r="5" fill="{color}"/>'
        body += text((left + 18, 471), f"{label}: {count:,}", 22)
    body += text(
        (40, 512),
        ("Native sensitivity frames: observed selectio" + "ns, not paired causal effects"),
        24,
    )
    if scope.native_views:
        for index, view in enumerate(scope.native_views):
            left = 40 + index * 380
            body += paragraph((left, 523, 355, 56), view.label, 22)
            body += text((left, 600), f"{view.tokens:,} tokens", 20)
            body += text((left, 628), f"{view.units:,} physical pages", 20)
            body += text((left, 653), f"{view.positive_token_issues} positive-token issues", 18)
    else:
        body += paragraph(
            (40, 550, 1120, 80),
            (
                "No additional native sensitivity rows suppli"
                + "ed in this snapshot; raw distributions remai"
                + "n measured above."
            ),
            22,
        )
    body += histogram((40, 665, 540, 370), native.diversity)
    body += histogram((620, 665, 540, 370), ocr.diversity, CORAL)
    body += paragraph(
        (40, 1050, 1120, 45),
        (
            "Complete fixed-length windows control text l"
            + "ength; short units stay unavailable. Native "
            + "and OCR overlap physically and are never add"
            + "ed into one corpus. OCR accuracy remains unm"
            + "easured."
        ),
        18,
    )
    return Drawing("02 Language: separate native and accepted OCR layers", body, 1100)
