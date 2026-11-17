"""Layer-specific denominators and explicit missing states survive visual-group joins."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crosstalk.study_cluster_language import (
    PageLanguageFrame,
    PageLexicalCounts,
    TargetCount,
    join_language,
)
from crosstalk.study_clustering import cluster_pages
from crosstalk.study_language_records import StudyError

from .fixtures import BINDING, frame, plan


def test_issue_group_rates_keep_missing_zero_and_view_excluded_separate() -> None:
    source = frame()
    run = cluster_pages(source, plan())
    a, c = source.pages[0], source.pages[2]

    def row(
        page_index: int, *, status: str, tokens: int | None, hits: int | None
    ) -> PageLexicalCounts:
        page = source.pages[page_index]
        return PageLexicalCounts.model_validate(
            {
                "issue_id": page.issue_id,
                "pdf_sha256": page.pdf_sha256,
                "page_index": page.page_index,
                "status": status,
                "tokens": tokens,
                "layer": "native",
                "view_name": "synthetic-view",
                "tokenizer_sha256": "c" * 64,
                "hits": (TargetCount(target="measurement", count=hits),)
                if hits is not None
                else (),
                "source_bindings": (BINDING,),
            },
            strict=True,
        )

    language = PageLanguageFrame(
        layer="native",
        view_name="synthetic-view",
        tokenizer_sha256="c" * 64,
        source_frame_receipt=BINDING,
        targets=("measurement",),
        pages=(
            row(0, status="measured", tokens=10, hits=2),
            row(1, status="measured", tokens=0, hits=0),
            row(2, status="view-excluded", tokens=None, hits=None),
        ),
    )
    result = join_language(run, run.models[-1], language)
    first = next(row for row in result.issue_cluster_rows if row.issue_id == a.issue_id)
    assert first.assigned_visual_pages == 2
    assert first.positive_token_pages == first.zero_token_pages == 1
    assert first.rates[0].hits == 2
    assert first.rates[0].tokens == 10
    assert first.rates[0].per_1000_tokens == 200.0
    second = next(row for row in result.issue_cluster_rows if row.issue_id == c.issue_id)
    assert dict(second.language_state_counts) == {"not-supplied": 1, "view-excluded": 1}
    assert second.rates[0].per_1000_tokens is None
    assert result.layer == "native"


def lexical_frame() -> PageLanguageFrame:
    source = frame()
    pages = tuple(
        PageLexicalCounts(
            issue_id=page.issue_id,
            pdf_sha256=page.pdf_sha256,
            page_index=page.page_index,
            status="measured",
            tokens=10,
            layer="ocr",
            view_name="synthetic-ocr-only",
            tokenizer_sha256="c" * 64,
            hits=(TargetCount(target="measurement", count=1),),
            source_bindings=(BINDING,),
        )
        for page in source.pages
    )
    return PageLanguageFrame(
        layer="ocr",
        view_name="synthetic-ocr-only",
        tokenizer_sha256="c" * 64,
        source_frame_receipt=BINDING,
        targets=("measurement",),
        pages=pages,
    )


def test_language_frame_identity_and_targets_are_checked_before_join() -> None:
    run = cluster_pages(frame(), plan())
    language = lexical_frame()
    for changed in (
        language.model_copy(update={"pages": (*language.pages, language.pages[0])}),
        language.model_copy(update={"targets": ("measurement", "another")}),
        language.model_copy(
            update={"pages": (language.pages[0].model_copy(update={"pdf_sha256": "d" * 64}),)}
        ),
    ):
        with pytest.raises(ValueError, match=r"cluster|validation error"):
            _ = join_language(run, run.models[-1], changed)


def test_different_text_layers_require_separate_frames_and_remain_labelled() -> None:
    run = cluster_pages(frame(), plan())
    language = lexical_frame()
    ocr = join_language(run, run.models[-1], language)
    with pytest.raises(StudyError, match="mixes text layers"):
        _ = join_language(run, run.models[-1], language.model_copy(update={"layer": "native"}))
    native_frame = language.model_copy(
        update={
            "layer": "native",
            "view_name": "synthetic-native-only",
            "pages": tuple(
                page.model_copy(update={"layer": "native", "view_name": "synthetic-native-only"})
                for page in language.pages
            ),
        }
    )
    native = join_language(run, run.models[-1], native_frame)
    assert ocr.layer == "ocr"
    assert native.layer == "native"
    assert ocr.language_frame_sha256 != native.language_frame_sha256


def test_unavailable_lexical_counts_cannot_be_zero_imputed() -> None:
    source = lexical_frame().pages[0]
    with pytest.raises(ValidationError, match="unavailable"):
        _ = PageLexicalCounts.model_validate(
            source.model_copy(update={"status": "missing"}).model_dump(mode="python"), strict=True
        )


def test_tokenizer_or_view_mixing_refuses_before_any_rate_is_computed() -> None:
    run = cluster_pages(frame(), plan())
    language = lexical_frame()
    for changes in ({"tokenizer_sha256": "d" * 64}, {"view_name": "different-view"}):
        changed = language.model_copy(
            update={"pages": (language.pages[0].model_copy(update=changes),)}
        )
        with pytest.raises(StudyError, match="mixes text layers"):
            _ = join_language(run, run.models[-1], changed)


def test_language_outside_visual_assignment_is_retained_as_unmatched() -> None:
    run = cluster_pages(frame(), plan())
    language = lexical_frame()
    extra = language.pages[0].model_copy(update={"issue_id": "new-source", "pdf_sha256": "e" * 64})
    result = join_language(
        run, run.models[-1], language.model_copy(update={"pages": (*language.pages, extra)})
    )
    assert result.language_pages_outside_visual_assignments == (extra.page_key,)
