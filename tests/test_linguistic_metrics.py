"""Exact deterministic lexical diagnostics on real typed page records."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crosstalk.linguistic_metrics import (
    fixed_window_diversity,
    measure_pages,
    normalized_tokens,
)
from crosstalk.linguistic_records import LinguisticSettings
from crosstalk.records import PageRecord


def pages_from(texts: tuple[str, ...]) -> tuple[PageRecord, ...]:
    return tuple(
        PageRecord(
            issue_id="fixture",
            source_pdf="data/raw/pdf/fixture.pdf",
            source_sha256="a" * 64,
            extractor_version="2",
            page_index=index,
            page_label=str(index + 7),
            width=300,
            height=420,
            text=text,
            blocks=(),
            images=(),
            quality=("reading-order-unverified",),
        )
        for index, text in enumerate(texts)
    )


def test_normalization_handles_unicode_without_rewriting_source() -> None:
    # Given compatibility forms, case variants, apostrophes and decomposed accents.
    text = (
        "\uff33\uff2f\uff26\uff34\uff37\uff21\uff32\uff25"
        " Engineer\u2019s CAFE\u0301 software 42 re-use"
    )
    # When the normalized derivative is tokenized.
    tokens = normalized_tokens(text)
    # Then equivalent forms share counts while source text remains an input value.
    assert tokens == ("software", "engineer's", "café", "software", "re-use")


def test_top_frequencies_keep_full_token_denominator() -> None:
    # Given three words but a one-entry output bound.
    pages = pages_from(("Beta beta alpha",))
    # When normalized frequencies are measured.
    result = measure_pages(pages, LinguisticSettings(top_terms=1))
    # Then output truncation cannot alter the frequency denominator.
    assert (result.tokens, result.types) == (3, 2)
    assert tuple(item.token for item in result.frequencies) == ("beta",)
    assert result.frequencies[0].per_1000_tokens == pytest.approx(2000 / 3)
    assert len(result.frequencies) == 1


def test_ngrams_do_not_cross_page_boundaries() -> None:
    # Given a phrase repeated across pages and a tempting boundary adjacency.
    pages = pages_from(("alpha beta", "gamma delta alpha beta"))
    # When contiguous word sequences are counted.
    result = measure_pages(pages, LinguisticSettings())
    # Then repetition, opportunities and source pages reflect within-page positions only.
    alpha_beta = next(
        item for item in result.bigrams.frequencies if item.tokens == ("alpha", "beta")
    )
    assert (result.bigrams.opportunities, result.trigrams.opportunities) == (4, 2)
    assert (alpha_beta.count, alpha_beta.page_indexes) == (2, (0, 1))
    assert alpha_beta.per_1000_opportunities == 500
    assert ("beta", "gamma") not in {item.tokens for item in result.bigrams.frequencies}
    assert {item.tokens for item in result.trigrams.frequencies} == {
        ("gamma", "delta", "alpha"),
        ("delta", "alpha", "beta"),
    }


def test_fixed_windows_exclude_tail_and_use_equal_lengths() -> None:
    # Given five tokens containing two complete two-word windows.
    # When fixed-size lexical diversity is computed.
    result = fixed_window_diversity(("a", "a", "b", "b", "c"), 2)
    # Then the incomplete tail does not change either window's denominator.
    assert (result.complete_windows, result.tokens_used, result.tokens_discarded) == (2, 4, 1)
    assert (result.status, result.mean_type_token_ratio) == ("available", 0.5)


def test_short_pages_cannot_form_cross_page_diversity_windows() -> None:
    # Given enough words overall, but no individual page reaches the window size.
    # When the issue is measured.
    result = measure_pages(pages_from(("one", "two")), LinguisticSettings(window_size=2))
    # Then insufficient data is explicit rather than pooled across page boundaries.
    assert result.complete_windows == 0
    assert result.mean_window_type_token_ratio is None
    assert tuple(page.diversity.status for page in result.pages) == (
        "insufficient-data",
        "insufficient-data",
    )
    assert tuple(page.diversity.tokens_discarded for page in result.pages) == (1, 1)


def test_window_mean_weights_complete_windows_instead_of_pages() -> None:
    # Given two all-distinct windows on one page and a repeated-token window on another.
    # When issue and page distributions are measured.
    result = measure_pages(pages_from(("a b c d", "a a")), LinguisticSettings(window_size=2))
    # Then each complete equal-length window contributes once.
    assert result.mean_window_type_token_ratio == pytest.approx(5 / 6)
    assert result.pages[0].fraction_of_issue_tokens == pytest.approx(4 / 6)
    assert result.pages[1].quality == ("reading-order-unverified",)


def test_repeated_lines_count_distinct_pages_and_remain_in_text() -> None:
    # Given a repeated header appearing twice on one page and once on another.
    pages = pages_from(
        ("Shared Defense Journal\nShared Defense Journal", "SHARED defense journal\nbody", "other")
    )
    # When a two-page recurrence threshold is applied.
    result = measure_pages(
        pages, LinguisticSettings(boilerplate_min_pages=2, boilerplate_min_fraction=0.6)
    )
    # Then page prevalence uses distinct physical pages and candidates are retained in counts.
    candidate = result.boilerplate_candidates[0]
    assert (candidate.normalized_line, candidate.page_indexes) == ("shared defense journal", (0, 1))
    assert candidate.page_fraction == pytest.approx(2 / 3)
    assert result.tokens == 11


def test_candidate_truncation_discloses_full_candidate_count() -> None:
    # Given two repeated lines with equal page prevalence.
    pages = pages_from(("alpha beta gamma\ndelta epsilon zeta",) * 2)
    # When one candidate is retained for presentation.
    result = measure_pages(pages, LinguisticSettings(top_boilerplate=1, boilerplate_min_pages=2))
    # Then deterministic ranking and full accounting survive presentation truncation.
    assert result.boilerplate_candidates_total == 2
    assert tuple(item.normalized_line for item in result.boilerplate_candidates) == (
        "alpha beta gamma",
    )
    assert result.tokens == 12


def test_empty_text_has_unavailable_rates_and_diversity() -> None:
    # Given an empty extracted selection.
    # When diagnostics are computed.
    result = measure_pages((), LinguisticSettings())
    # Then no zero-denominator statistic is invented.
    assert (result.tokens, result.frequencies, result.bigrams.opportunities) == (0, (), 0)
    assert result.mean_window_type_token_ratio is None
    assert result.boilerplate_candidates == ()


def test_nonconsecutive_page_indexes_refuse_ambiguous_provenance() -> None:
    # Given two page records sharing the same physical page identity.
    page = pages_from(("one two three",))[0]
    # When the diagnostic boundary receives duplicated pages.
    with pytest.raises(ValueError, match="consecutive"):
        _ = measure_pages((page, page), LinguisticSettings())
    # Then page-level counts cannot double count an ambiguous source page.


def test_invalid_window_bound_refuses() -> None:
    # Given an impossible one-token diversity window.
    # When the sampling boundary is parsed.
    with pytest.raises(ValueError, match="at least two"):
        _ = fixed_window_diversity(("one",), 1)
    # Then an invalid denominator cannot enter the transform.


def test_invalid_candidate_bounds_refuse() -> None:
    # Given an impossible repeated-line length interval.
    # When the settings boundary is parsed.
    with pytest.raises(ValidationError, match="must not exceed"):
        _ = LinguisticSettings(boilerplate_min_tokens=4, boilerplate_max_tokens=3)
    # Then an empty length interval cannot silently exclude all candidates.
