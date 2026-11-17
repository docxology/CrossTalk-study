"""Immutable native evidence and independent report seals remain separate from raw sources."""

from __future__ import annotations

import hashlib
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.extraction_method import EXTRACTION_IMPLEMENTATION_FILES
from crosstalk.locator_storage import EVENT_NAME, MAX_LOCATOR_EVENTS, publish_metadata
from crosstalk.models import AcquisitionError, file_digest, safe_directory
from crosstalk.native_layer_records import (
    NativeIssueObservation,
    NativeLayerReceipt,
    NativeLayerRun,
)
from crosstalk.records import write_records

if TYPE_CHECKING:
    from crosstalk.index_observe import IndexReader
    from crosstalk.native_layers.source import CurrentLayers

IMPLEMENTATION_FILES: Final = (
    "native_layer_records.py",
    "native_layer_variants.py",
    "native_layer_store.py",
    "native_layer_run.py",
    "native_layer_html.py",
    "native_layer_read.py",
    "text_source.py",
    "index_observe.py",
    "index_records.py",
    "metrics.py",
    "lexicon.py",
    "native_layers/__init__.py",
    "native_layers/records.py",
    "native_layers/wrapper.py",
    "native_layers/layers.py",
    "native_layers/cohort.py",
    "native_layers/cohort_records.py",
    "native_layers/handle_source.py",
    "native_layers/source.py",
    "statistical_records.py",
    "statistical_scope.py",
    "statistical_bootstrap.py",
    "statistical_source.py",
    "signposting_store.py",
    "signposting_custody.py",
    "signposting_parse.py",
    "signposting_records.py",
    "locator_records.py",
    "locator_storage.py",
    "index_identity.py",
    *EXTRACTION_IMPLEMENTATION_FILES,
)


def implementation_digest() -> str:
    """Bind actual native measurement, custody, lexical and resampling implementation files."""
    digest = hashlib.sha256()
    for name in IMPLEMENTATION_FILES:
        path = Path(__file__).parent / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise AcquisitionError("native-layer implementation is unavailable or oversized")
        digest.update(name.encode())
        digest.update(bytes.fromhex(file_digest(path)))
    return digest.hexdigest()


def locator_membership(reader: IndexReader) -> tuple[str, ...]:
    """Bind the independent response-authority ledger, including its exact finite membership."""
    directory = safe_directory(reader.root, "output/data/locator-ledger")
    paths = tuple(islice(directory.glob("*.json"), MAX_LOCATOR_EVENTS + 1))
    if len(paths) > MAX_LOCATOR_EVENTS or any(
        not EVENT_NAME.fullmatch(path.name) for path in paths
    ):
        raise AcquisitionError("native-layer locator ledger membership is invalid or oversized")
    names = tuple(sorted(path.relative_to(reader.root).as_posix() for path in paths))
    for name in names:
        _ = reader.digest(name)
    return names


def projection(current: CurrentLayers, path: str, digest: str) -> NativeIssueObservation:
    """Compact fields are projections of retained actual page/line/rule evidence."""
    layers, identity = current.layers, current.layers.identity
    return NativeIssueObservation(
        issue_id=identity.issue_id,
        title=identity.title,
        pdf_sha256=identity.pdf_sha256,
        page_artifact_sha256=identity.page_artifact_sha256,
        evidence_path=path,
        evidence_sha256=digest,
        physical_pdf_pages=identity.total_pdf_pages,
        extracted_pages=layers.observed_extracted_pages,
        raw_tokens=layers.raw.text.tokens,
        wrapper_minus_tokens=layers.wrapper_excluded.text.tokens,
        matched_wrapper_page_indexes=layers.wrapper_excluded.excluded_page_indexes,
        review_page_indexes=tuple(
            row.page_index for row in layers.observations if row.status == "candidate-review"
        ),
        zero_native_body=layers.zero_native_body,
    )


def publish_issue(root: Path, current: CurrentLayers) -> NativeIssueObservation:
    """Detailed derived evidence is content-addressed; no occupied unequal bytes are replaced."""
    raw = current.model_dump_json().encode() + b"\n"
    if len(raw) > 20_000_000:
        raise AcquisitionError("native-layer issue evidence exceeds its20MB publication bound")
    digest = hashlib.sha256(raw).hexdigest()
    name = f"{current.layers.identity.issue_id}-{digest}.jsonl"
    path = publish_metadata(safe_directory(root, "output/data/native-layers/issues"), name, raw)
    return projection(current, path.relative_to(root).as_posix(), digest)


def publish_run(root: Path, run: NativeLayerRun, document: str) -> NativeLayerReceipt:
    """Retain immutable summary/HTML generations before the independent current seal is written."""
    raw = run.model_dump_json().encode() + b"\n"
    if len(raw) > 20_000_000 or len(document.encode()) > 20_000_000:
        raise AcquisitionError("native-layer summary/HTML exceeds its20MB publication bound")
    digest = hashlib.sha256(raw).hexdigest()
    summary = publish_metadata(
        safe_directory(root, "output/data/native-layers/runs"), digest + ".jsonl", raw
    )
    html_bytes = document.encode()
    html_sha = hashlib.sha256(html_bytes).hexdigest()
    page = publish_metadata(
        safe_directory(root, "output/reports"), f"native-layers-{html_sha}.html", html_bytes
    )
    receipt = NativeLayerReceipt(
        summary_path=summary.relative_to(root).as_posix(),
        summary_sha256=digest,
        html_path=page.relative_to(root).as_posix(),
        html_sha256=html_sha,
    )
    write_records(root / "output/reports/native-layers.jsonl", (receipt,))
    return receipt
