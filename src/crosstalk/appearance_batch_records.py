"""Finite managed appearance batches retain explicit journal and fixture source families."""

import hashlib
from typing import Annotated, Literal, Self, assert_never

from pydantic import Field, model_validator

from .appearance_audit_records import ResourceAudit
from .appearance_records import (
    AntiAliasState,
    AppearanceError,
    AppearanceSettings,
    Digest,
    PageAppearance,
    Record,
)
from .ocr_records import BoundFile, PriorArtifact


class AppearanceTask(Record):
    """One selected original PDF page; outer catalog associations are independently admitted."""

    issue_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")]
    source_kind: Literal["journal-page", "synthetic-fixture"]
    pdf: BoundFile
    page_index: int = Field(ge=0, le=99_999)


class PriorAppearance(Record):
    """Both record and thumbnail require one actual successful manager output selection."""

    record: PriorArtifact
    thumbnail: BoundFile
    thumbnail_output_name: str


class AppearanceBatchSpec(Record):
    """A closed finite input selection; batch size does not alter an individual pixel cache."""

    schema_version: Literal[1] = 1
    runtime_sha256: Digest
    source_files: Annotated[tuple[BoundFile, ...], Field(min_length=1, max_length=30)]
    dependencies: Annotated[tuple[BoundFile, ...], Field(min_length=1, max_length=1000)]
    settings: AppearanceSettings = AppearanceSettings()
    maximum_batch_pages: int = Field(default=500, ge=1, le=500)
    tasks: Annotated[tuple[AppearanceTask, ...], Field(min_length=1, max_length=500)]
    prior: Annotated[tuple[PriorAppearance, ...], Field(max_length=1000)] = ()


class AppearanceEngine(Record):
    """Actual selected implementation, dependency, interpreter and native rendering state."""

    producer_sha256: Digest
    source_selection_sha256: Digest
    runtime_sha256: Digest
    dependency_sha256: Digest
    settings_sha256: Digest
    pymupdf_version: str
    mupdf_version: str
    pillow_version: str
    python_version: str
    antialias: AntiAliasState


class AppearanceArtifact(Record):
    """A producer record awaits the supervisor seal; its own digest never authorizes reuse."""

    cache_key: Digest
    engine: AppearanceEngine
    page: PageAppearance

    @model_validator(mode="after")
    def measured_context(self) -> Self:
        """A record cannot relabel measured pixels as another native/interpreter context."""
        if (
            self.page.renderer_version != self.engine.pymupdf_version
            or self.page.pillow_version != self.engine.pillow_version
            or self.page.python_version != self.engine.python_version
            or self.page.antialias != self.engine.antialias
        ):
            raise AppearanceError("appearance artifact and actual measured engine disagree")
        if (
            hashlib.sha256(self.page.settings.model_dump_json().encode()).hexdigest()
            != self.engine.settings_sha256
        ):
            raise AppearanceError("appearance artifact settings differ from the bound engine")
        return self


class AppearanceOutcome(Record):
    """Per-page missingness cannot silently exclude valid native text or become a zero metric."""

    task: AppearanceTask
    status: Literal["appearance-produced", "render-error", "policy-refused"]
    record: BoundFile | None = None
    thumbnail: BoundFile | None = None
    reused: bool = False
    prior_run_id: str | None = None
    reason: str | None = None
    resource_audit: ResourceAudit | None = None

    @model_validator(mode="after")
    def output_consistency(self) -> Self:
        """Successful pages have both files; failed pages cannot carry fabricated outputs."""
        match self.status:
            case "appearance-produced":
                if self.record is None or self.thumbnail is None or self.reason is not None:
                    raise AppearanceError(
                        "produced appearance requires both complete output identities"
                    )
                if self.reused != (self.prior_run_id is not None):
                    raise AppearanceError("appearance reuse flag lacks matching prior run identity")
                if self.resource_audit is not None:
                    raise AppearanceError(
                        "produced metadata audit belongs to the measured artifact"
                    )
            case "render-error" | "policy-refused":
                if (
                    self.record is not None
                    or self.thumbnail is not None
                    or self.reused
                    or self.prior_run_id is not None
                    or self.reason is None
                ):
                    raise AppearanceError(
                        "failed appearance must retain a reason without successful outputs"
                    )
                if (self.status == "policy-refused") != (self.resource_audit is not None):
                    raise AppearanceError("policy refusal requires its attributed metadata audit")
                if self.resource_audit is not None and self.resource_audit.status == "passed":
                    raise AppearanceError("refused appearance cannot carry a passed metadata audit")
            case _:
                assert_never(self.status)
        return self


class AppearanceBatchReport(Record):
    """Only supervisor-sealed journal-family outcomes may enter the later journal atlas."""

    spec_sha256: Digest
    engine: AppearanceEngine
    settings: AppearanceSettings
    outcomes: tuple[AppearanceOutcome, ...]
    semantic_validation: None = None
    corpus_accuracy: None = None
