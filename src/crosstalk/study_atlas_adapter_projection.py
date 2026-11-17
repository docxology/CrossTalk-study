"""Read selected appearance within64MB and retain shared custody checks."""

from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003 -- Pydantic field resolves at runtime.
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from crosstalk.atlas_records import ArtifactBinding
from crosstalk.locator_storage import read_metadata
from crosstalk.study_language_records import Digest, StudyError

if TYPE_CHECKING:
    from crosstalk.index_observe import IndexReader


class ProjectionRecord(BaseModel):
    """This typed projection intentionally omits observation time, as the original producer did."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="ignore", allow_inf_nan=False
    )


class ExternalFile(ProjectionRecord):
    """The historic manager path is retained; only the outer admitted reader may open/copy it."""

    path: Path
    sha256: Digest


class ProjectionSource(ProjectionRecord):
    """Exact original source membership survives the timestamp-free projection."""

    pdf_sha256: Digest
    representative_issue_id: str
    pdf_path: str
    total_pdf_pages: int = Field(ge=1)


class ProjectionFrame(ProjectionRecord):
    """Retain the timestamp-free frame without fabricating observation times."""

    catalog_records: int = Field(ge=0)
    sources: tuple[ProjectionSource, ...]
    exclusions: tuple[ProjectionRecord, ...]


class ProjectionEpoch(ProjectionRecord):
    """Bind a shared method/settings/runtime epoch distinct from page cache keys."""

    epoch_sha256: Digest
    engine_json: str
    source_selection_sha256: Digest
    runtime_sha256: Digest
    dependency_sha256: Digest
    settings_sha256: Digest


class ProjectionMeasurement(ProjectionRecord):
    """Pointers are enough to select exact original pairs; actual bytes are admitted separately."""

    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    epoch_sha256: Digest
    record: ExternalFile
    thumbnail: ExternalFile


class ProjectionAttempt(ProjectionRecord):
    """Fixture, out-of-frame, reused and refused attempts never inflate physical source units."""

    run_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    epoch_sha256: Digest
    source_kind: Literal["journal-page", "synthetic-fixture"]
    admission: Literal["fixture-excluded", "current-journal", "outside-current-frame"]
    status: Literal["appearance-produced", "policy-refused", "render-error"]
    reason: str | None


class AppearanceProjection(ProjectionRecord):
    """A historical accepted selection, not an automatic current corpus-admission certificate."""

    schema_version: Literal[1]
    frame: ProjectionFrame
    epochs: tuple[ProjectionEpoch, ...]
    measured: tuple[ProjectionMeasurement, ...]
    attempts: tuple[ProjectionAttempt, ...]
    accepted_receipts: tuple[ExternalFile, ...]
    unavailable_receipts: tuple[ProjectionRecord, ...]
    observed_files: tuple[ExternalFile, ...]


def selected_projection(reader: IndexReader, selected: ArtifactBinding) -> AppearanceProjection:
    """Read/hash this selected64MB artifact without changing the generic20MB reader."""
    raw = read_metadata(reader.path(selected.path), 64_000_000)
    if (
        hashlib.sha256(raw).hexdigest() != selected.sha256
        or reader.digest(selected.path).sha256 != selected.sha256
    ):
        raise StudyError("selected appearance projection differs from the retained digest")
    projected = AppearanceProjection.model_validate_json(raw)
    if projected.unavailable_receipts:
        raise StudyError(
            "appearance projection has unavailable selected receipts; "
            + "full-frame publication refused"
        )
    return projected


def local_pair_targets(row: ProjectionMeasurement) -> tuple[ArtifactBinding, ArtifactBinding]:
    """Plan no-replace copies without opening or changing manager evidence."""
    root = "output/data/study-v06/atlas-source-pairs/"
    return (
        ArtifactBinding(path=root + row.record.sha256 + ".json", sha256=row.record.sha256),
        ArtifactBinding(path=root + row.thumbnail.sha256 + ".png", sha256=row.thumbnail.sha256),
    )
