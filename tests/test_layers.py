"""Generated-PDF controls exercise reversible selections without journal fixtures."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

import pymupdf
import pytest
from PIL import Image
from pydantic import TypeAdapter

from crosstalk.extract import extract_corpus
from crosstalk.metrics import text_metrics
from crosstalk.native_layers.layers import measure_layers
from crosstalk.native_layers.records import HandleEvidence, NativeIdentity, NativePage
from crosstalk.native_layers.wrapper import observe_wrapper
from crosstalk.records import PageRecord

if TYPE_CHECKING:
    from pathlib import Path

TITLE = "CrossTalk / May 1996"
HANDLE = "https://hdl.handle.net/10945/999999"


def test_absent_observed_handle_is_missing_even_when_expected_handle_is_known(
    tmp_path: Path,
) -> None:
    # Given an actual image-only generated page with independently declared fixture identity.
    identity, pages = source_at(tmp_path, ("",))
    # When no native URI or Link-to-Item claim was observed on that page.
    observation = observe_wrapper(pages[0], identity)
    # Then absent evidence is not mislabeled as a contradictory observed handle.
    assert observation.status == "no-signature"
    assert observation.handle_status == "missing-or-inconsistent"


def wrapper() -> str:
    return f"""{TITLE}

Title
{TITLE}

Item Type
Journal

Citation
Software fixture, May 1996

URI
{HANDLE}

Publisher
Software fixture

Date Issued
1996-05

Rights
Fixture material may be reused.

Download date
2026-11-05 12:00:00

Link to Item
{HANDLE}

Downloaded from NPS Archive: Calhoun
"""


def source_at(
    root: Path, texts: tuple[str, ...], issue_id: str = "fixture"
) -> tuple[NativeIdentity, tuple[NativePage, ...]]:
    directory = root / "data/raw/pdf"
    directory.mkdir(parents=True)
    with Image.new("RGB", (32, 32), (30, 40, 50)) as image:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        payload = stream.getvalue()
    pdf = directory / f"{issue_id}.pdf"
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page(width=612, height=792)
            if text:
                fit = TypeAdapter(float).validate_python(
                    getattr(page, "insert_textbox")(  # noqa: B009 - parsed dependency boundary.
                        pymupdf.Rect(25, 25, 580, 700), text, fontsize=8
                    )
                )
                assert fit >= 0
            else:
                _ = TypeAdapter(int).validate_python(
                    getattr(page, "insert_image")(pymupdf.Rect(25, 25, 65, 65), stream=payload)  # noqa: B009 - parsed dependency boundary.
                )
        _ = TypeAdapter(type(None)).validate_python(getattr(document, "save")(pdf))  # noqa: B009
    summary = extract_corpus(root)
    outcome = summary.issues[0]
    assert outcome.source_sha256 is not None
    assert outcome.page_artifact_sha256 is not None
    raw = (root / "data/processed/pages" / f"{issue_id}.jsonl").read_bytes()
    pages = tuple(
        NativePage(
            page=PageRecord.model_validate_json(line),
            record_line_sha256=hashlib.sha256(line).hexdigest(),
        )
        for line in raw.splitlines(keepends=True)
    )
    evidence = HandleEvidence(
        handle_url=HANDLE,
        publication_url="https://example.invalid/fixture",
        request_url="https://example.invalid/fixture/linkset",
        snapshot_path="fixture-linkset.json",
        snapshot_sha256="a" * 64,
        body_sha256="b" * 64,
        catalog_sha256="c" * 64,
        robots_sha256="d" * 64,
        provenance="software-fixture",
    )
    identity = NativeIdentity(
        issue_id=issue_id,
        title=TITLE,
        issued="1996-05",
        landing_url="https://example.invalid/fixture",
        catalog_sha256="c" * 64,
        pdf_sha256=outcome.source_sha256,
        page_artifact_sha256=outcome.page_artifact_sha256,
        total_pdf_pages=len(texts),
        extraction_status="complete",
        source_kind="software-fixture",
        handle_evidence=evidence,
    )
    return identity, pages


def test_generated_pdf_selection_preserves_raw_metrics_and_originals(tmp_path: Path) -> None:
    # Given an exact template, genuine May prose and an image-only physical page.
    identity, pages = source_at(tmp_path, (wrapper(), "May software teams may test systems.", ""))
    pdf = tmp_path / "data/raw/pdf/fixture.pdf"
    artifact = tmp_path / "data/processed/pages/fixture.jsonl"
    originals = (pdf.read_bytes(), artifact.read_bytes())
    baseline = text_metrics("\n".join(native.page.text for native in pages))
    # When selecting a separately named sensitivity layer.
    result = measure_layers(identity, pages)
    # Then original bytes and raw metrics survive while only physical page zero is excluded.
    assert result.raw.text == baseline
    assert result.wrapper_excluded.excluded_page_indexes == (0,)
    assert result.wrapper_excluded.included_page_indexes == (1, 2)
    assert result.wrapper_excluded.text.hedge_tokens == 2
    assert result.wrapper_excluded.low_text_pages == 2
    assert (pdf.read_bytes(), artifact.read_bytes()) == originals
    assert result.observations[0].record_line_sha256 == pages[0].record_line_sha256


def test_wrapper_only_text_leaves_unavailable_rates(tmp_path: Path) -> None:
    # Given a matched wrapper followed by an image-only page.
    identity, pages = source_at(tmp_path, (wrapper(), ""))
    # When deriving the wrapper-excluded view.
    result = measure_layers(identity, pages)
    # Then a zero native denominator is unavailable, not a zero lexical rate.
    assert result.raw.text.tokens > 0
    assert result.wrapper_excluded.text.tokens == 0
    assert result.wrapper_excluded.text.hedge_per_1000 is None
    assert result.wrapper_excluded.text.modal_per_1000 is None
    assert result.zero_native_body
    assert not result.wrapper_excluded.exploratory_native_rich


@pytest.mark.parametrize(
    "texts",
    [
        ("", wrapper()),
        (wrapper().replace("Rights\n", ""),),
        (wrapper().replace(f"Title\n{TITLE}", "Title\n"),),
        (
            wrapper().replace(
                f"Link to Item\n{HANDLE}", "Link to Item\nhttps://hdl.handle.net/10945/111111"
            ),
        ),
        ("May may mean a month; software should be tested.",),
    ],
)
def test_negative_controls_preserve_every_page(tmp_path: Path, texts: tuple[str, ...]) -> None:
    # Given a later signature, partial template, contradictory handle, or genuine May prose.
    identity, pages = source_at(tmp_path, texts)
    # When observing the proposed mechanical template rule.
    result = measure_layers(identity, pages)
    # Then no page is deleted from the sensitivity selection.
    assert result.wrapper_excluded.excluded_page_indexes == ()
    assert result.wrapper_excluded.text == result.raw.text


def test_repeated_handle_without_independent_evidence_stays_included(tmp_path: Path) -> None:
    # Given the wrapper's internally repeated URI but no separately retained linkset evidence.
    identity, pages = source_at(tmp_path, (wrapper(), ""))
    identity = identity.model_copy(update={"handle_evidence": None})
    # When evaluating the first-page signature.
    result = measure_layers(identity, pages)
    # Then repetition is an observation, not independent confirmation.
    assert result.observations[0].handle_status == "observed-repeated-only"
    assert result.observations[0].status == "candidate-review"
    assert result.wrapper_excluded.excluded_page_indexes == ()
