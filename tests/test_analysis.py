"""Real-PDF extraction and source-bound descriptive analysis tests."""

from __future__ import annotations

import hashlib
import io
import shutil
from typing import TYPE_CHECKING

import pymupdf
import pytest
from PIL import Image
from pydantic import ValidationError

from crosstalk.analysis import analyze_corpus, categorize, image_metrics, text_metrics
from crosstalk.extract import ImageOccurrence, PageRecord, extract_corpus, write_records
from crosstalk.models import Issue

from .registered_sources import register_source

if TYPE_CHECKING:
    from pathlib import Path


def make_pdf(path: Path, texts: tuple[str, ...], image_size: tuple[int, int] = (64, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", image_size, (180, 40, 20)) as image:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        payload = stream.getvalue()
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page(width=300, height=420)
            if text:
                page.insert_textbox(pymupdf.Rect(20, 20, 280, 200), text, fontsize=10)
            page.insert_image(pymupdf.Rect(20, 220, 148, 300), stream=payload)
        document.set_page_labels(
            [{"startpage": 0, "prefix": "folio-", "style": "D", "firstpagenum": 7}]
        )
        document.save(path)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    make_pdf(
        tmp_path / "data/raw/pdf/pilot.pdf",
        (
            "Software security testing may improve quality. Teams should verify systems and data.",
            "",
        ),
    )
    issue = Issue(
        issue_id="pilot",
        title="Pilot <script>alert(1)</script>",
        issued="2000-01",
        landing_url="https://calhoun.nps.edu/handle/10945/1",
        pdf_url="https://calhoun.nps.edu/server/api/core/bitstreams/1/content",
    )
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    return tmp_path


def test_extract_keeps_page_provenance_and_flags_image_only_page(corpus: Path) -> None:
    # Given an issue with text and an image-only second page.
    source = corpus / "data/raw/pdf/pilot.pdf"
    original = source.read_bytes()
    # When extracting the complete local issue.
    summary = extract_corpus(corpus)
    # Then page records retain coordinates, physical index, metadata label and OCR gap.
    pages = tuple(
        PageRecord.model_validate_json(line)
        for line in (corpus / "data/processed/pages/pilot.jsonl").read_text().splitlines()
    )
    assert summary.issues[0].status == "complete"
    assert summary.issues[0].extracted_pages == 2
    assert pages[0].page_index == 0
    assert pages[0].page_label == "folio-7"
    assert pages[0].blocks[0].bbox[0] == pytest.approx(20)
    assert "security" in pages[0].text
    assert "low-text-ocr-review" in pages[1].quality
    assert source.read_bytes() == original
    assert pages[0].source_sha256 == hashlib.sha256(original).hexdigest()
    assert len(list((corpus / "data/processed/images").iterdir())) == 1
    assert (corpus / "output/figures/contact_sheet.png").is_file()


def test_resume_preserves_valid_page_artifact(corpus: Path) -> None:
    # Given an extraction and its byte-stable page artifact.
    extract_corpus(corpus)
    artifact = corpus / "data/processed/pages/pilot.jsonl"
    before = artifact.stat().st_mtime_ns
    # When extracting the same source and scope again.
    summary = extract_corpus(corpus)
    # Then the verified artifact is resumed without rewriting it.
    assert summary.issues[0].resumed
    assert artifact.stat().st_mtime_ns == before


def test_page_limit_remains_explicit_and_expansion_reextracts(corpus: Path) -> None:
    # Given a bounded first-page extraction.
    first = extract_corpus(corpus, max_pages=1)
    # When expanding the extraction scope.
    expanded = extract_corpus(corpus)
    # Then the first run is partial and the expanded run is newly complete.
    assert first.issues[0].status == "partial"
    assert first.issues[0].total_pages == 2
    assert expanded.issues[0].extracted_pages == 2
    assert not expanded.issues[0].resumed


def test_corrupt_page_cache_regenerates(corpus: Path) -> None:
    # Given malformed generated JSONL, with original PDFs intact.
    extract_corpus(corpus)
    (corpus / "data/processed/pages/pilot.jsonl").write_text("{}\n")
    # When resuming extraction.
    summary = extract_corpus(corpus)
    # Then the corrupt cache is not treated as a successful prior extraction.
    assert summary.issues[0].status == "complete"
    assert not summary.issues[0].resumed


def test_corrupt_image_is_preserved_as_explicit_failure(corpus: Path) -> None:
    # Given a corrupted saved image.
    extract_corpus(corpus)
    image = next((corpus / "data/processed/images").iterdir())
    image.write_bytes(b"damaged")
    # When rechecking extraction.
    summary = extract_corpus(corpus)
    # Then corrupted evidence remains for inspection and the issue fails.
    assert summary.issues[0].status == "failed"
    assert image.read_bytes() == b"damaged"


def test_bad_pdf_does_not_discard_successful_peer(corpus: Path) -> None:
    # Given a malformed PDF adjacent to the valid issue.
    (corpus / "data/raw/pdf/broken.pdf").write_bytes(b"invalid PDF")
    # When extracting all local PDFs.
    summary = extract_corpus(corpus)
    # Then the successful issue and explicit failed issue coexist.
    assert {row.issue_id: row.status for row in summary.issues} == {
        "broken": "failed",
        "pilot": "complete",
    }


def test_small_image_is_recorded_without_payload(tmp_path: Path) -> None:
    # Given a small embedded image beneath the extraction threshold.
    make_pdf(tmp_path / "data/raw/pdf/small.pdf", ("Text",), (8, 8))
    # When extracting the document.
    extract_corpus(tmp_path)
    # Then provenance records the skipped image instead of inventing a saved image.
    page = PageRecord.model_validate_json(
        (tmp_path / "data/processed/pages/small.jsonl").read_text()
    )
    assert page.images[0].status == "small-skipped"
    assert page.images[0].path is None


def test_empty_input_writes_finite_empty_summary(tmp_path: Path) -> None:
    # Given an empty local collection.
    # When extracting it.
    summary = extract_corpus(tmp_path)
    # Then no contact sheet or issues are claimed.
    assert summary.issues == ()
    assert summary.contact_sheet is None


def test_invalid_page_limit_refuses(corpus: Path) -> None:
    # Given a zero-page request.
    # When applying the invalid bound.
    with pytest.raises(ValueError, match="positive"):
        extract_corpus(corpus, max_pages=0)
    # Then no extraction output was created.
    assert not (corpus / "data/processed/pages").exists()


def test_lexical_counts_use_stated_denominators() -> None:
    # Given repeated terms and known hedge/modal tokens.
    # When computing descriptive lexical metrics.
    metrics = text_metrics("May may software software should testing.")
    # Then counts and rates use the actual six-token denominator.
    assert metrics.tokens == 6
    assert metrics.types == 4
    assert metrics.hedge_tokens == 2
    assert metrics.modal_tokens == 3
    assert metrics.type_token_ratio == pytest.approx(4 / 6)
    assert metrics.hedge_per_1000 == pytest.approx(2000 / 6)
    assert text_metrics("").type_token_ratio is None


def test_issue_analysis_links_keywords_images_and_escaped_sources(corpus: Path) -> None:
    # Given source-linked extracted pages.
    extract_corpus(corpus)
    # When generating the exploratory report.
    summary = analyze_corpus(corpus)
    # Then measurements and retrieval labels retain page evidence and safe HTML.
    issue = summary.issues[0]
    assert issue.issued == "2000-01"
    assert issue.pages == 2
    assert issue.low_text_pages == 1
    assert {hit.category for hit in issue.categories} >= {"security-assurance", "testing-quality"}
    assert all(hit.page_indexes == (0,) for hit in issue.categories)
    assert issue.images[0].occurrence_count == 2
    assert issue.images[0].width == 64
    assert issue.images[0].height == 40
    assert issue.images[0].grayscale_entropy_bits == pytest.approx(0)
    assert issue.images[0].mean_rgb == pytest.approx((180, 40, 20))
    report = (corpus / "output/reports/analysis.html").read_text()
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert 'src="../figures/contact_sheet.png"' in report


def test_duplicate_pdf_is_excluded_from_corpus_counts(corpus: Path) -> None:
    # Given byte-identical PDFs under two issue IDs.
    shutil.copyfile(corpus / "data/raw/pdf/pilot.pdf", corpus / "data/raw/pdf/second.pdf")
    register_source(corpus, "second")
    extract_corpus(corpus)
    # When aggregating the issue corpus.
    summary = analyze_corpus(corpus)
    # Then one source-distinct issue supplies the denominator.
    assert summary.duplicate_issues == ("second",)
    assert len(summary.issues) == 1
    assert summary.corpus_text.tokens == summary.issues[0].text.tokens


def test_changed_pdf_invalidates_old_analysis(corpus: Path) -> None:
    # Given extraction from an earlier PDF revision.
    extract_corpus(corpus)
    (corpus / "data/raw/pdf/pilot.pdf").write_bytes(b"changed source")
    # When analyzing saved extracted pages.
    summary = analyze_corpus(corpus)
    # Then historical extraction is unavailable for the changed source.
    assert summary.issues == ()
    assert summary.unavailable_issues == ("pilot",)
    report = (corpus / "output/reports/analysis.html").read_text()
    assert 'src="../figures/contact_sheet.png"' not in report


def test_unavailable_and_missing_metadata_remain_explicit(tmp_path: Path) -> None:
    # Given a valid unregistered PDF and a malformed peer.
    make_pdf(tmp_path / "data/raw/pdf/unregistered.pdf", ("No matched subject vocabulary",))
    (tmp_path / "data/raw/pdf/broken.pdf").write_bytes(b"broken")
    extract_corpus(tmp_path)
    # When analyzing the local subset.
    summary = analyze_corpus(tmp_path)
    # Then absent manifest custody refuses current text without fabricating archive metadata.
    assert summary.issues == ()
    assert summary.unavailable_issues == ("broken", "unregistered")
    unregistered = next(
        failure for failure in summary.unavailable_details if failure.issue_id == "unregistered"
    )
    assert unregistered.stage == "provenance"


def test_keyword_labels_preserve_word_boundaries(corpus: Path) -> None:
    # Given a page containing an unrelated substring.
    extract_corpus(corpus)
    page = PageRecord.model_validate_json(
        (corpus / "data/processed/pages/pilot.jsonl").read_text().splitlines()[0]
    ).model_copy(update={"text": "Database processes unmapped", "images": ()})
    # When applying the retrieval lexicon.
    labels = categorize((page,))
    # Then data/process matches are not invented from substrings.
    assert labels == ()
    assert image_metrics(corpus, (page,)) == ()


def test_generated_image_paths_refuse_traversal() -> None:
    # Given an attempted path outside the generated image pool.
    # When parsing a saved occurrence boundary.
    with pytest.raises(ValidationError):
        ImageOccurrence(
            bbox=(0, 0, 1, 1),
            width=1,
            height=1,
            xref=1,
            status="saved",
            path="data/processed/images/../../secret",
        )
    # Then the boundary rejects it before any file is read.


def test_pdf_symlink_is_an_explicit_refusal(corpus: Path) -> None:
    # Given a second issue path that aliases another source PDF.
    (corpus / "data/raw/pdf/alias.pdf").symlink_to("pilot.pdf")
    # When extracting the corpus.
    summary = extract_corpus(corpus)
    # Then symlink input is refused while its physical peer succeeds.
    assert {row.issue_id: row.status for row in summary.issues} == {
        "alias": "failed",
        "pilot": "complete",
    }


def test_deleted_image_is_recreated_from_original_pdf(corpus: Path) -> None:
    # Given extraction whose generated image was removed.
    extract_corpus(corpus)
    image = next((corpus / "data/processed/images").iterdir())
    image.unlink()
    # When extracting again.
    summary = extract_corpus(corpus)
    # Then source bytes regenerate the missing derived artifact.
    assert summary.issues[0].status == "complete"
    assert not summary.issues[0].resumed
    assert image.is_file()


def test_image_integrity_failure_preserves_successful_peer(corpus: Path) -> None:
    # Given two issues, one with a later corrupt generated image.
    make_pdf(corpus / "data/raw/pdf/peer.pdf", ("Independent peer research",), (8, 8))
    register_source(corpus, "peer")
    extract_corpus(corpus)
    next((corpus / "data/processed/images").iterdir()).write_bytes(b"changed")
    # When analyzing measurements.
    summary = analyze_corpus(corpus)
    # Then visual damage cannot discard either source's independently valid native text.
    assert {issue.issue_id for issue in summary.issues} == {"peer", "pilot"}
    assert summary.unavailable_issues == ()
    pilot = next(issue for issue in summary.issues if issue.issue_id == "pilot")
    assert pilot.visual is not None
    assert pilot.visual.failures[0].stage == "image-integrity"


def test_source_replacement_invalidates_resume(corpus: Path) -> None:
    # Given extraction before a changed PDF replaces the local source.
    extract_corpus(corpus)
    replacement = corpus / "replacement.pdf"
    make_pdf(replacement, ("Updated requirement and acquisition research",))
    replacement.replace(corpus / "data/raw/pdf/pilot.pdf")
    # When resuming extraction.
    summary = extract_corpus(corpus)
    # Then extraction reflects the new one-page source rather than cached pages.
    assert summary.issues[0].extracted_pages == 1
    assert not summary.issues[0].resumed


def test_empty_analysis_preserves_unknown_denominators(tmp_path: Path) -> None:
    # Given an empty extraction receipt.
    extract_corpus(tmp_path)
    # When analyzing the absent corpus.
    summary = analyze_corpus(tmp_path)
    # Then an empty denominator remains unavailable rather than a measured rate.
    assert summary.issues == ()
    assert summary.corpus_text.tokens == 0
    assert summary.corpus_text.hedge_per_1000 is None
