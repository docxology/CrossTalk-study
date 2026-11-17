"""Fresh selected-page PDF geometry, independent of native metadata and image decoding."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, ClassVar

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from crosstalk.case_files import read_bytes
from crosstalk.case_records import CaseError
from crosstalk.index_observe import IndexReader
from crosstalk.pdf_adapter import document_info

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class Rectangle(BaseModel):
    """Actual PDF page rectangle dimensions at the native-library boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, allow_inf_nan=False)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class PageGeometry(BaseModel):
    """Only dimensions are checked; glyph placement and interpretation remain reviewed claims."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)
    rect: Rectangle


def check_pdf_geometry(
    root: Path,
    issue_id: str,
    expected_sha256: str,
    selected: Mapping[int, tuple[float, float]],
) -> None:
    """Open one exact PDF per issue and compare only the selected physical-page rectangles."""
    reader = IndexReader(root)
    raw = read_bytes(reader.path(f"data/raw/pdf/{issue_id}.pdf"), 100_000_000)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise CaseError("case PDF changed before selected-page geometry inspection")
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        info = document_info(document)
        if not info.is_pdf or info.needs_pass or info.page_count < 1:
            raise CaseError("case PDF geometry is unavailable or encrypted")
        for index, expected in selected.items():
            if not 0 <= index < info.page_count:
                raise CaseError("case physical page is outside the actual PDF page tree")
            page = PageGeometry.model_validate(document[index])
            if (page.rect.width, page.rect.height) != expected:
                raise CaseError("reviewed case dimensions differ from actual PDF page geometry")
    reader.recheck()
