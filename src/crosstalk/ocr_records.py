"""Typed source-bound OCR derivatives, batch limits and supervisor evidence inputs."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, ClassVar, Literal, override

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
IssueId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")]
SourceKind = Literal["journal-page", "synthetic-fixture"]
NativeVersion = Literal["2", "3", "synthetic-raster-fixture-1"]


class OcrError(ValueError):
    """A finite OCR custody or input refusal with a typed reason."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Retain the explicit custody refusal for structured boundary reporting."""
        self.reason = reason
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        return self.reason


def relative_file(value: str) -> str:
    """Admit one exact ordinary relative file name without traversal or secret paths."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or any(
            part in {".git", ".ssh", ".aws", "credentials"} or part.startswith(".env")
            for part in path.parts
        )
    ):
        raise OcrError("OCR file selection must be an ordinary exact relative pathname")
    return value


Relative = Annotated[str, AfterValidator(relative_file)]


class Record(BaseModel):
    """Immutable finite parsed evidence; native artifacts are never replaced."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class BoundFile(Record):
    """An independently selected byte identity, not a row's self-asserted source hash."""

    path: Relative
    sha256: Digest
    size: int = Field(ge=0, le=100_000_000)


class Settings(Record):
    """Finite English full-page OCR; page bounds are not a per-page time guarantee."""

    language: Literal["eng"] = "eng"
    dpi: int = Field(default=150, ge=72, le=300)
    maximum_pixels: int = Field(default=8_000_000, ge=1, le=20_000_000)
    maximum_batch_pages: int = Field(default=32, ge=1, le=500)
    geometry_tolerance_points: float = Field(default=0.5, ge=0, le=2)


class Task(Record):
    """One physical page selected from independently sealed native extraction bytes."""

    issue_id: IssueId
    source_kind: SourceKind
    pdf: BoundFile
    native: BoundFile
    page_index: int = Field(ge=0, le=499)
    native_page_sha256: Digest


class PriorArtifact(Record):
    """Exact previous successful managed-run evidence and one selected output artifact."""

    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    results: BoundFile
    compute_exit: BoundFile
    run_use: BoundFile
    artifact: BoundFile
    output_name: Relative


class BatchSpec(Record):
    """Reviewed finite isolated input selection; no directory or implicit host imports."""

    schema_version: Literal["1"] = "1"
    runtime_sha256: Digest
    source_files: Annotated[tuple[BoundFile, ...], Field(min_length=1, max_length=30)]
    dependencies: Annotated[tuple[BoundFile, ...], Field(min_length=1, max_length=1000)]
    model: BoundFile
    settings: Settings = Settings()
    tasks: Annotated[tuple[Task, ...], Field(min_length=1, max_length=500)]
    prior: Annotated[tuple[PriorArtifact, ...], Field(max_length=1000)] = ()


class EngineBinding(Record):
    """Exact selected engine closure; host Tesseract CLI version is not the native version."""

    producer_sha256: Digest
    source_selection_sha256: Digest
    runtime_sha256: Digest
    dependency_sha256: Digest
    model_sha256: Digest
    settings_sha256: Digest
    pymupdf_version: str
    mupdf_version: str
    tesseract_version: None = None
    model_semantic_version: None = None
    engine: Literal["MuPDF native Tesseract API"] = "MuPDF native Tesseract API"


class PageBinding(Record):
    """Physical source identity and the independent native-artifact/page selection."""

    issue_id: IssueId
    source_kind: SourceKind
    pdf_sha256: Digest
    native_artifact_sha256: Digest
    native_page_sha256: Digest
    page_index: int = Field(ge=0)


class Block(Record):
    """Unreviewed OCR block in unrotated physical PDF points, at 72 points per inch."""

    bbox: tuple[float, float, float, float]
    text: str
    number: int

    @model_validator(mode="after")
    def positive_area(self) -> Block:
        """Reject invalid rectangles without silently clamping or repairing coordinates."""
        left, top, right, bottom = self.bbox
        if right <= left or bottom <= top:
            raise OcrError("OCR block rectangle has no positive area")
        return self


class TextlessBlock(Record):
    """An omitted native textless block, retaining its original possibly sentinel rectangle."""

    bbox: tuple[float, float, float, float]
    text: str
    number: int
    reason: Literal["text-strip-empty"] = "text-strip-empty"

    @model_validator(mode="after")
    def textless(self) -> TextlessBlock:
        """Prevent nonempty recognition from bypassing ordinary block geometry validation."""
        if self.text.strip():
            raise OcrError("only textless OCR blocks may enter the omission record")
        return self


Status = Literal["ocr-produced", "ocr-empty", "engine-error", "bound-refused"]


class PageResult(Record):
    """A separate derivative, without transcription accuracy or reading-order claims."""

    schema_version: Literal["1"] = "1"
    cache_key: Digest
    source: PageBinding
    engine: EngineBinding
    status: Status
    native_characters: int = Field(ge=0)
    native_extractor_version: NativeVersion | None = None
    text: str
    blocks: tuple[Block, ...]
    omitted_textless_blocks: tuple[TextlessBlock, ...] = ()
    omitted_textless_block_count: int = Field(default=0, ge=0)
    page_width_points: float = Field(gt=0)
    page_height_points: float = Field(gt=0)
    rotation: int
    cropbox_unrotated: tuple[float, float, float, float]
    geometry_tolerance_points: float = Field(ge=0, le=2)
    geometry_status: Literal["within-declared-bounds", "out-of-bounds", "no-text-blocks"]
    rendered_width_pixels: int = Field(ge=1)
    rendered_height_pixels: int = Field(ge=1)
    elapsed_seconds: float = Field(ge=0)
    error: str | None = None
    coordinates: Literal["unrotated crop-relative PDF points; top-left origin; y down"] = (
        "unrotated crop-relative PDF points; top-left origin; y down"
    )
    quality: tuple[str, ...] = ("ocr-unreviewed", "reading-order-unverified", "geometry-unreviewed")
    corpus_accuracy: None = None

    @model_validator(mode="after")
    def native_kind(self) -> PageResult:
        """Preserve historical unannotated results without promoting fixtures to journal pages."""
        if self.native_extractor_version is not None:
            fixture = self.native_extractor_version == "synthetic-raster-fixture-1"
            if fixture != (self.source.source_kind == "synthetic-fixture"):
                raise OcrError("recorded native extractor version disagrees with source kind")
        return self

    @model_validator(mode="after")
    def omission_accounting(self) -> PageResult:
        """Require persisted omission counts and an explicit quality marker to agree."""
        if self.omitted_textless_block_count != len(self.omitted_textless_blocks):
            raise OcrError("textless OCR block count differs from retained omission records")
        if self.omitted_textless_blocks and "textless-ocr-blocks-omitted" not in self.quality:
            raise OcrError("textless OCR block omissions require an explicit quality marker")
        return self


class PageOutcome(Record):
    """Current batch effect; reused content retains its original recognition timing."""

    source: PageBinding
    output: BoundFile
    status: Status
    reused: bool
    prior_run_id: str | None = None


class BatchReport(Record):
    """Finite process outcome; successful execution does not mean every page produced text."""

    schema_version: Literal["1"] = "1"
    spec_sha256: Digest
    engine: EngineBinding
    settings: Settings
    outcomes: tuple[PageOutcome, ...]
    limitations: tuple[str, ...] = (
        "Native text remains separate and unchanged",
        "No corpus gold-standard accuracy or calibrated confidence is available",
        "Full PDF extraction and OCR-produced status do not establish complete text capture",
        "Only separately supervisor-sealed successful/reaped prior runs authorize reuse",
    )
