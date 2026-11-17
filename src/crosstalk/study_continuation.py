"""A schematic witness graph shows noncontiguous reading order without fabricating page regions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.study_briefing_svg import BLACK, GRAY, RED, line, number, section
from crosstalk.study_graphical_svg import paragraph, text

if TYPE_CHECKING:
    from crosstalk.study_continuation_records import ContinuationWitness


def continuation_diagram(witness: ContinuationWitness) -> str:
    """Draw physical order; red identifies textual continuation, without region ownership."""
    ordered = tuple(sorted(witness.pages, key=lambda page: page.physical_page_index))
    stride = 660 / len(ordered)
    positions = {page.step_id: 510 + (index + 0.5) * stride for index, page in enumerate(ordered)}
    body = section((500, 258), "CONTINUATION / PHYSICAL ORDER")
    body += paragraph((500, 272, 680, 60), witness.article_label, 20)
    for page in ordered:
        center = positions[page.step_id]
        left, width = center - stride * 0.43, stride * 0.86
        body += (
            '<rect x="'
            + f"{left:.2f}"
            + '" y="350" width="'
            + f"{width:.2f}"
            + '" height="130" fill="#ffffff" stroke="'
            + f"{BLACK}"
            + '" stroke-width="1"/>'
        )
        body += text((left + 8, 375), "PDF INDEX", 18) + number(
            (left + 8, 413), page.physical_page_index, 30
        )
        body += paragraph(
            (left + 8, 431, width - 16, 43), "Printed " + (page.printed_label or "unknown"), 18
        )
        if page.shared_page_note is not None:
            body += (
                '<rect x="'
                + f"{left:.2f}"
                + '" y="486" width="'
                + f"{width:.2f}"
                + '" height="12" fill="url(#brief-refused)"/>'
            )
    for index, edge in enumerate(witness.edges):
        start, end = positions[edge.source_step], positions[edge.target_step]
        explicit = edge.basis == "explicit-text-marker"
        shade = RED if explicit else BLACK
        bend = 530 + index * 22
        anchor = 480
        body += (
            '<path d="M'
            + f"{start:.2f}"
            + ","
            + f"{anchor}"
            + " L"
            + f"{start:.2f}"
            + ","
            + f"{bend}"
            + " L"
            + f"{end:.2f}"
            + ","
            + f"{bend}"
            + " L"
            + f"{end:.2f}"
            + ","
            + f"{anchor}"
            + '" fill="none" stroke="'
            + f"{shade}"
            + '" stroke-width="2"/>'
        )
        tip = anchor + 9
        body += (
            '<polygon points="'
            + f"{end - 5:.2f}"
            + ","
            + f"{tip}"
            + " "
            + f"{end:.2f}"
            + ","
            + f"{anchor}"
            + " "
            + f"{end + 5:.2f}"
            + ","
            + f"{tip}"
            + '" fill="'
            + f"{shade}"
            + '"/>'
        )
        body += (
            f'<g fill="{shade}">'
            + paragraph(
                (500, 636 + index * 49, 680, 43),
                f"{edge.source_step} → {edge.target_step}: " + edge.marker,
                18,
            )
            + "</g>"
        )
    body += line((500, 620, 1180, 620), GRAY)
    shared = tuple(page.shared_page_note for page in ordered if page.shared_page_note is not None)
    if shared:
        body += paragraph((500, 915, 680, 80), "Shared-page text witness: " + " ".join(shared), 18)
    body += paragraph(
        (500, 1014, 680, 45),
        (
            "Schematic text-located edges. Actual page-re"
            + "gion ownership is not geometry-verified."
        ),
        18,
    )
    return body
