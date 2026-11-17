"""Graphical abstracts for measurement and human review pathways."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.dossier_layout import CORAL, MUTED, PALE, TEAL, Card, Label, PageCanvas, TextStyle

if TYPE_CHECKING:
    from crosstalk.dossier_records import DossierInput


def draw_methods(canvas: PageCanvas, content: DossierInput) -> None:
    """Separate implemented descriptors, proposed interpretation and validation."""
    canvas.heading(
        "Three views of the same evidence",
        "Graphical abstract 03 / Text, images and their relationships require different tests.",
    )
    canvas.text(
        Label((42, 172, 292, 197), "TEAL: IMPLEMENTED DESCRIPTORS", TextStyle(9, "hebo", TEAL))
    )
    canvas.text(Label((306, 172, 553, 197), "CORAL: PLANNED RESEARCH", TextStyle(9, "hebo", CORAL)))
    for index, method in enumerate(content.methods):
        top = 200 + index * 174
        canvas.text(Label((42, top, 553, top + 23), method.name, TextStyle(12, "hebo", TEAL)))
        canvas.card(Card((42, top + 24, 287, top + 139), "MEASURE", method.implemented))
        canvas.card(
            Card(
                (307, top + 24, 553, top + 139), "INTERPRET AFTER VALIDATION", method.planned, CORAL
            )
        )
        canvas.arrow((289, top + 87), (305, top + 87))
        canvas.text(
            Label(
                (54, top + 145, 540, top + 168),
                "Validation: " + method.validation,
                TextStyle(8, color=MUTED),
            )
        )
    canvas.rectangle((42, 729, 553, 778), PALE)
    canvas.text(
        Label(
            (54, 739, 541, 771),
            "Descriptor values are observations. Keyword hits are screening aids. "
            + "Color, entropy and embedding proximity do not establish sentiment, "
            + "meaning or historical influence.",
            TextStyle(9),
        )
    )


def draw_review(canvas: PageCanvas, content: DossierInput) -> None:
    """Explain the planned source-to-claim review graph and its release gates."""
    canvas.heading(
        "How observations become claims",
        "Graphical abstract 04 / Source checks, independent review "
        + "and synthesis use different gates.",
    )
    nodes = (
        Card(
            (42, 180, 202, 315),
            "1  VERIFY SOURCE",
            "Stable record, PDF digest, issue identity, rights and physical page coordinates.",
        ),
        Card(
            (218, 180, 378, 315),
            "2  ANNOTATE",
            "Two reviewers code article boundaries, genre, topic, claims and figure roles.",
            CORAL,
        ),
        Card(
            (394, 180, 553, 315),
            "3  COMPARE",
            "Measure agreement and held-out extraction or classification errors.",
            CORAL,
        ),
        Card(
            (130, 355, 291, 490),
            "4  ADJUDICATE",
            "Retain disagreements, alternatives and uncertain units. Revise the codebook.",
            CORAL,
        ),
        Card(
            (307, 355, 468, 490),
            "5  SYNTHESIZE",
            "Link claims to exact pages, contrary examples and historical context.",
            CORAL,
        ),
    )
    for card in nodes:
        canvas.card(card)
    canvas.arrow((204, 247), (216, 247))
    canvas.arrow((380, 247), (392, 247))
    canvas.arrow((472, 318), (214, 352))
    canvas.arrow((293, 423), (305, 423))
    canvas.text(
        Label(
            (42, 520, 553, 544), "FOUR GATES FOR A DEFENSIBLE REVIEW", TextStyle(11, "hebo", TEAL)
        )
    )
    gates = (
        Card(
            (42, 557, 287, 647),
            "COVERAGE",
            "Expected holdings, reviewed gaps, versions and failed acquisitions.",
        ),
        Card(
            (307, 557, 553, 647),
            "MEASUREMENT",
            "OCR, reading order, image masks, boundaries and caption alignment.",
        ),
        Card(
            (42, 663, 287, 753),
            "INFERENCE",
            "Issue/article sampling, uncertainty, time splits and sensitivity analyses.",
        ),
        Card(
            (307, 663, 553, 753),
            "INTERPRETATION",
            "Evidence quality, contradictions, close reading and rights review.",
        ),
    )
    for card in gates:
        canvas.card(card)
    canvas.text(
        Label(
            (42, 764, 553, 785),
            f"Current source bindings: {len(content.source_bindings)} files. "
            + "Reviewer agreement and article-level evidence ratings have not yet been measured.",
            TextStyle(8, color=MUTED),
        )
    )
