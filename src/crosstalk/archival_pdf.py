"""Bounded PDF syntax admission and native period evidence, independent of corpus membership."""

from __future__ import annotations

import hashlib
import re
from typing import Final

import pymupdf
from pydantic import TypeAdapter

from crosstalk.archival_records import (
    ArchivalCandidate,
    ArchivalError,
    ArchivalInspection,
    PdfPeriodWitness,
)
from crosstalk.pdf_adapter import document_info, text_blocks

MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
BOOLEAN: Final = TypeAdapter(bool)


def inspect_archival_pdf(raw: bytes, candidate: ArchivalCandidate) -> ArchivalInspection:
    """Refuse invalid PDF syntax and scope; leave publication identity for source review."""
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
        raise ArchivalError("archival body lacks a complete PDF header/end marker")
    try:
        with pymupdf.open(stream=raw, filetype="pdf") as document:
            info = document_info(document)
            if (
                not info.is_pdf
                or info.needs_pass
                or not 1 <= info.page_count <= 500
                or BOOLEAN.validate_python(document.is_repaired)
            ):
                raise ArchivalError(
                    "archival PDF is encrypted, repaired or outside the finite physical scope"
                )
            pattern = re.compile(
                r"\b" + MONTHS[candidate.month - 1] + r"\s+" + str(candidate.year) + r"\b",
                re.IGNORECASE,
            )
            witnesses: list[PdfPeriodWitness] = []
            name_seen = False
            for index in range(min(6, info.page_count)):
                text = "\n".join(
                    block[4] for block in text_blocks(document[index]) if block[6] == 0
                )
                name_seen = name_seen or "crosstalk" in text.casefold()
                matches = tuple(match.group() for match in pattern.finditer(text))
                if matches:
                    witnesses.append(
                        PdfPeriodWitness(
                            page_index=index,
                            page_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                            matched_text=matches[:12],
                        )
                    )
    except (RuntimeError, ValueError) as error:
        raise ArchivalError(str(error)) from error
    return ArchivalInspection(
        pdf_sha256=hashlib.sha256(raw).hexdigest(),
        page_count=info.page_count,
        native_period_witnesses=tuple(witnesses),
        crosstalk_name_seen=name_seen,
    )
