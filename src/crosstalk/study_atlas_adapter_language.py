"""Join whole-page language to visual sources while keeping native and OCR separate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from crosstalk.atlas_records import ArtifactBinding  # noqa: TC001 -- Pydantic field resolves at runtime.
from crosstalk.study_atlas_adapter_features import cluster_binding
from crosstalk.study_cluster_language import PageLanguageFrame, PageLexicalCounts, TargetCount
from crosstalk.study_language import implementation_digest, tokenize
from crosstalk.study_language_records import Digest, Record, SourceTextUnit, StudyError

if TYPE_CHECKING:
    from crosstalk.study_atlas_adapter_records import AtlasInputFrame


class TextPageObservation(Record):
    """Explicit opportunity state for one layer/view; absent OCR is not a zero-token page."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    status: Literal["measured", "view-excluded", "missing", "refused", "failed", "unattempted"]
    reason: str
    source: SourceTextUnit | None
    evidence: ArtifactBinding

    @model_validator(mode="after")
    def page_identity(self) -> TextPageObservation:
        """Admit only complete whole-page text units as lexical opportunities."""
        if (self.status == "measured") != (self.source is not None):
            raise StudyError("text opportunity status and actual source unit disagree")
        if self.source is not None and (
            self.source.issue_id != self.issue_id
            or self.source.pdf_sha256 != self.pdf_sha256
            or self.source.page_index != self.page_index
            or self.source.region_id is not None
            or self.source.article_id is not None
            or self.source.layer_artifact_sha256 != self.evidence.sha256
        ):
            raise StudyError(
                "whole-page cluster-language source identity or region/artifact "
                + "scope disagrees"
            )
        return self


class LanguageSelection(Record):
    """One predeclared tokenizer/layer/view and complete page-state frame per independent call."""

    layer: Literal["native", "ocr"]
    view_name: str
    tokenizer_sha256: Digest
    source_frame_receipt: ArtifactBinding
    targets: tuple[str, ...] = Field(min_length=1, max_length=100)
    pages: tuple[TextPageObservation, ...] = Field(min_length=1, max_length=30_000)


def language_frame(frame: AtlasInputFrame, selected: LanguageSelection) -> PageLanguageFrame:
    """Count exact tokens and hits; absent text supplies no inferred rate."""
    targets = selected.targets
    if selected.tokenizer_sha256 != implementation_digest():
        raise StudyError(
            "cluster-language tokenizer identity differs from the actual "
            + "frozen producer/runtime"
        )
    if len(set(targets)) != len(targets) or any(
        tokenize(target) != (target,) for target in targets
    ):
        raise StudyError("cluster-language targets must be distinct normalized single tokens")
    physical = {slot.page_key: slot.issue_id for slot in frame.pages}
    keys = tuple(f"{row.pdf_sha256}:{row.page_index}" for row in selected.pages)
    if len(set(keys)) != len(keys) or set(keys) != set(physical):
        raise StudyError("text state frame must retain every declared physical page exactly once")
    rows: list[PageLexicalCounts] = []
    for page in sorted(selected.pages, key=lambda item: (item.pdf_sha256, item.page_index)):
        if physical[f"{page.pdf_sha256}:{page.page_index}"] != page.issue_id:
            raise StudyError("text and visual frames disagree about PDF/issue identity")
        source = page.source
        if source is not None and source.layer != selected.layer:
            raise StudyError("native and OCR opportunities cannot be fused in one language frame")
        tokens = tokenize(source.text) if source is not None else None
        rows.append(
            PageLexicalCounts(
                issue_id=page.issue_id,
                pdf_sha256=page.pdf_sha256,
                page_index=page.page_index,
                layer=selected.layer,
                view_name=selected.view_name,
                tokenizer_sha256=selected.tokenizer_sha256,
                status=page.status,
                tokens=len(tokens) if tokens is not None else None,
                hits=tuple(
                    TargetCount(target=target, count=tokens.count(target)) for target in targets
                )
                if tokens is not None
                else (),
                source_bindings=(
                    cluster_binding(selected.source_frame_receipt),
                    cluster_binding(page.evidence),
                ),
            )
        )
    return PageLanguageFrame(
        layer=selected.layer,
        view_name=selected.view_name,
        tokenizer_sha256=selected.tokenizer_sha256,
        source_frame_receipt=cluster_binding(selected.source_frame_receipt),
        targets=targets,
        pages=tuple(rows),
    )
