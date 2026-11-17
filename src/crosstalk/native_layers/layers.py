"""Reversible native-text sensitivity uses the unchanged declared lexical measurements."""

from __future__ import annotations

from crosstalk.metrics import text_metrics
from crosstalk.models import AcquisitionError
from crosstalk.native_layers.records import (
    IssueLayers,
    LayerSettings,
    LayerView,
    NativeIdentity,
    NativePage,
)
from crosstalk.native_layers.wrapper import observe_wrapper
from crosstalk.records import EXTRACTOR_VERSION


def _view(
    pages: tuple[NativePage, ...], excluded: tuple[int, ...], settings: LayerSettings
) -> LayerView:
    """Retain physical selection and real token/character denominators for each derivative."""
    selected = tuple(native.page for native in pages if native.page.page_index not in excluded)
    text = "\n".join(page.text for page in selected)
    measured = text_metrics(text)
    low_text = sum("low-text-ocr-review" in page.quality for page in selected)
    fraction = low_text / len(selected) if selected else None
    return LayerView(
        name="native-minus-matched-repository-wrapper" if excluded else "raw-native",
        included_page_indexes=tuple(page.page_index for page in selected),
        excluded_page_indexes=excluded,
        text=measured,
        native_characters=sum(len(page.text) for page in selected),
        low_text_pages=low_text,
        low_text_fraction=fraction,
        rate_status="available-native-proxy" if measured.tokens else "zero-native-tokens",
        exploratory_native_rich=measured.tokens > 0
        and fraction is not None
        and fraction <= settings.maximum_low_text_fraction,
    )


def measure_layers(
    identity: NativeIdentity, pages: tuple[NativePage, ...], settings: LayerSettings | None = None
) -> IssueLayers:
    """Observe exact page selections without rewriting originals or interpreting lexical hits."""
    if (
        not pages
        or len(pages) > min(identity.total_pdf_pages, 500)
        or any(
            native.page.issue_id != identity.issue_id
            or native.page.source_sha256 != identity.pdf_sha256
            or native.page.page_index != index
            or native.page.extractor_version != EXTRACTOR_VERSION
            or native.page.source_pdf != f"data/raw/pdf/{identity.issue_id}.pdf"
            for index, native in enumerate(pages)
        )
    ):
        raise AcquisitionError("native layer identity, page order or extraction scope disagrees")
    if identity.extraction_status == "complete" and len(pages) != identity.total_pdf_pages:
        raise AcquisitionError("complete native layer scope disagrees with physical PDF count")
    chosen = settings or LayerSettings()
    observations = tuple(observe_wrapper(page, identity) for page in pages)
    excluded = tuple(row.page_index for row in observations if row.status == "matched-wrapper")
    raw = _view(pages, (), chosen)
    sensitivity = _view(pages, excluded, chosen).model_copy(
        update={"name": "native-minus-matched-repository-wrapper"}
    )
    return IssueLayers(
        identity=identity,
        observations=observations,
        raw=raw,
        wrapper_excluded=sensitivity,
        settings=chosen,
        matched_wrapper_pages=len(excluded),
        observed_extracted_pages=len(pages),
        zero_native_body=sensitivity.text.tokens == 0,
    )
