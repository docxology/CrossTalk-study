"""Cover and corpus-coverage graphical abstracts from current dossier evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.dossier_layout import (
    CORAL,
    MUTED,
    PALE,
    TEAL,
    WHITE,
    Card,
    Label,
    PageCanvas,
    TextStyle,
)

if TYPE_CHECKING:
    from crosstalk.dossier_records import DossierInput


def draw_cover(canvas: PageCanvas, content: DossierInput) -> None:
    """Compose the author block and an evidence-bearing overview on page one."""
    evidence = content.evidence
    canvas.text(
        Label(
            (42, 53, 553, 75),
            "DEFENSE SOFTWARE ENGINEERING / LONGITUDINAL RESEARCH",
            TextStyle(9, "hebo", TEAL),
        )
    )
    canvas.text(Label((42, 88, 553, 168), content.title, TextStyle(44, "tibo")))
    canvas.text(Label((42, 170, 553, 232), content.subtitle, TextStyle(17)))
    names = "  |  ".join(author.name for author in content.authors)
    canvas.text(Label((42, 241, 553, 268), names, TextStyle(14, "hebo")))
    identifiers = "  |  ".join(
        f"ORCID {author.orcid}" for author in content.authors if author.orcid
    )
    canvas.text(Label((42, 273, 553, 297), identifiers, TextStyle(9.5, color=MUTED)))
    canvas.text(
        Label(
            (42, 306, 553, 331),
            "Research protocol and local evidence  /  "
            + f"{content.observed_at[:10]}  /  v{content.version}",
            TextStyle(9.5, color=TEAL),
        )
    )
    canvas.line((42, 340), (553, 340))
    canvas.text(
        Label(
            (42, 356, 553, 377),
            "GRAPHICAL ABSTRACT 01 / THE RESEARCH SYSTEM",
            TextStyle(9, "hebo", TEAL),
        )
    )
    canvas.text(
        Label((42, 382, 553, 422), "From archive to accountable evidence", TextStyle(21, "tibo"))
    )
    cards = (
        Card(
            (42, 433, 205, 570),
            "01  DISCOVER",
            "Capture issue metadata; resolve official PDF locators; "
            + "preserve dates, rights and uncertainty.",
        ),
        Card(
            (216, 433, 379, 570),
            "02  DESCRIBE",
            "Bind native text, measured raster assets and page coordinates to exact digests. "
            + "Keep unavailable visuals explicit.",
        ),
        Card(
            (390, 433, 553, 570),
            "03  INTERPRET",
            "Validate article labels and visual evidence, "
            + "then synthesize claims with contrary cases.",
            CORAL,
        ),
    )
    for card in cards:
        canvas.card(card)
    canvas.arrow((206, 501), (215, 501))
    canvas.arrow((380, 501), (389, 501))
    metrics = (
        (f"{evidence.catalog_records:,}", "catalog records"),
        (f"{evidence.analyzed_issues:,}", "native-text issues"),
        (f"{evidence.pages:,}", "cohort PDF pages"),
        (f"{evidence.images:,}", "measured raster digests"),
    )
    for index, (number, label) in enumerate(metrics):
        left = 42 + index * 130
        canvas.text(Label((left, 594, left + 121, 636), number, TextStyle(25, "hebo", TEAL)))
        canvas.text(Label((left, 638, left + 121, 669), label, TextStyle(9, color=MUTED)))
    canvas.rectangle((42, 690, 553, 766), PALE)
    canvas.text(
        Label(
            (55, 701, 540, 753),
            "Observed scope: counts describe the captured NPS listing and accepted native text. "
            + "Raster measurements use a separate subset. Historical holdings and comprehensive "
            + "article-level review remain unverified.",
            TextStyle(10),
        )
    )


def draw_coverage(canvas: PageCanvas, content: DossierInput) -> None:
    """Show distinct coverage denominators and the catalog metadata distribution."""
    evidence = content.evidence
    reported = (
        str(evidence.catalog_reported_total)
        if evidence.catalog_reported_total is not None
        else "unavailable"
    )
    capture = (
        "capture matches listing total"
        if evidence.catalog_capture_matches_reported
        else "partial or unverified capture"
    )
    canvas.heading(
        "Corpus coverage and its limits",
        f"Graphical abstract 02 / Listing reported {reported}; {capture}.",
    )
    stages = (
        (
            "CAPTURED CATALOG",
            evidence.catalog_records,
            "Unique publication records in the rendered series snapshot.",
        ),
        (
            "VERIFIED LOCAL PDFS",
            evidence.downloaded_issues,
            "Integrity-checked issue sources available to this project.",
        ),
        (
            "NATIVE-TEXT COHORT",
            evidence.analyzed_issues,
            "Source-distinct issues admitted independently of visual decoder success.",
        ),
    )
    for index, (title, number, body) in enumerate(stages):
        top = 176 + index * 86
        canvas.rectangle((42, top, 334, top + 73), WHITE)
        canvas.rectangle((42, top, 47, top + 73), TEAL)
        canvas.text(Label((58, top + 10, 249, top + 29), title, TextStyle(8, "hebo", TEAL)))
        canvas.text(
            Label((255, top + 8, 320, top + 44), str(number), TextStyle(20, "hebo", TEAL, 2))
        )
        canvas.text(Label((58, top + 34, 319, top + 69), body, TextStyle(9)))
        if index < 2:
            canvas.arrow((184, top + 75), (184, top + 84))
    canvas.card(
        Card(
            (349, 176, 553, 421),
            "ANALYTICAL UNITS",
            f"{evidence.pages:,} native-cohort PDF pages\n"
            + f"{evidence.tokens:,} alphabetic tokens\n"
            + f"{evidence.images:,} measured raster digests\n"
            + f"{evidence.low_text_pages:,} low-text review flags\n\n"
            + "Raster coverage is separate. Article boundaries and expected historical "
            + "holdings remain unverified.",
        )
    )
    canvas.text(
        Label((42, 451, 553, 474), "CAPTURED CATALOG BY METADATA YEAR", TextStyle(10, "hebo", TEAL))
    )
    chart_bottom, chart_height = 625.0, 127.0
    years = tuple(sorted(evidence.year_counts, key=lambda row: row.year))
    if years:
        first, last = years[0].year, years[-1].year
        counts = {row.year: row.count for row in years}
        span = last - first + 1
        step = 499 / span
        maximum = max(row.count for row in years) or 1
        last_tick_x = -35.0
        canvas.line((48, chart_bottom), (547, chart_bottom))
        for year in range(first, last + 1):
            count = counts.get(year, 0)
            left = 48 + (year - first) * step
            if count:
                height = count / maximum * chart_height
                canvas.rectangle(
                    (left, chart_bottom - height, left + max(step - 2, 0.5), chart_bottom), TEAL
                )
            spaced = left - last_tick_x >= 35 and (last - year) * step >= 35
            if year in {first, last} or (year % 5 == 0 and spaced):
                canvas.text(
                    Label(
                        (left - 8, 634, min(left + 30, 553), 657),
                        str(year),
                        TextStyle(7.5, color=MUTED),
                    )
                )
                last_tick_x = left
        canvas.text(
            Label(
                (48, 479, 250, 497), f"Largest annual count: {maximum}", TextStyle(8, color=MUTED)
            )
        )
    else:
        canvas.text(
            Label(
                (48, 514, 547, 554),
                "No unambiguous catalog-year observations are available.",
                TextStyle(11),
            )
        )
    share = (
        f"{evidence.downloaded_issues / evidence.catalog_records:.1%}"
        if evidence.catalog_records
        else "unavailable"
    )
    canvas.rectangle((42, 680, 553, 775), PALE)
    canvas.text(
        Label(
            (55, 691, 540, 763),
            f"Acquired share of captured catalog: {share}. "
            + f"Unresolved PDF records: {evidence.unresolved_records:,}. "
            + f"Date conflicts retained: {evidence.date_conflicts:,}.\n\n"
            + "The histogram excludes conflicting or absent dates. It describes catalog "
            + "metadata, not article production, journal frequency "
            + "or complete historical holdings.",
            TextStyle(9.5),
        )
    )
