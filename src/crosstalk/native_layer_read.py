"""Sealed native reports are current only while all source and producer bindings still agree."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.acquisition_lock import project_lock
from crosstalk.index_observe import IndexReader
from crosstalk.models import AcquisitionError
from crosstalk.native_layer_records import NativeLayerReceipt, NativeLayerRun
from crosstalk.native_layer_store import implementation_digest, locator_membership, projection
from crosstalk.native_layers.source import CurrentLayers

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class CurrentNativeReport:
    """A real held read guard accompanies every current report adoption."""

    run: NativeLayerRun
    receipt: NativeLayerReceipt
    reader: IndexReader


def _verify_details(reader: IndexReader, run: NativeLayerRun, bound: dict[str, str]) -> None:
    """Detailed immutable evidence and every source projection must agree."""
    for issue in run.issues:
        data = reader.read(issue.evidence_path)
        if hashlib.sha256(data).hexdigest() != issue.evidence_sha256:
            raise AcquisitionError("native-layer detailed evidence changed")
        current = CurrentLayers.model_validate_json(data.strip())
        if projection(current, issue.evidence_path, issue.evidence_sha256) != issue or any(
            bound.get(binding.path) != binding.sha256 for binding in current.bindings
        ):
            raise AcquisitionError("native-layer compact and detailed source observations disagree")


def _validate(reader: IndexReader) -> CurrentNativeReport:
    receipt = NativeLayerReceipt.model_validate_json(
        reader.read("output/reports/native-layers.jsonl").strip()
    )
    raw = reader.read(receipt.summary_path)
    if hashlib.sha256(raw).hexdigest() != receipt.summary_sha256:
        raise AcquisitionError("native-layer summary differs from its independent report seal")
    run = NativeLayerRun.model_validate_json(raw.strip())
    if run.implementation_sha256 != implementation_digest() or run.producer != reader.producer:
        raise AcquisitionError("native-layer code or actual runtime producer is stale")
    if locator_membership(reader) != run.locator_ledger_paths:
        raise AcquisitionError("native-layer independent locator authority membership changed")
    bound = {binding.path: binding.sha256 for binding in run.input_bindings}
    if len(bound) != len(run.input_bindings):
        raise AcquisitionError("native-layer source bindings are duplicated")
    for relative, expected in bound.items():
        if reader.digest(relative).sha256 != expected:
            raise AcquisitionError("native-layer source evidence changed")
    _verify_details(reader, run, bound)
    if reader.digest(receipt.html_path).sha256 != receipt.html_sha256:
        raise AcquisitionError("native-layer escaped HTML changed")
    reader.recheck()
    return CurrentNativeReport(run, receipt, reader)


@contextmanager
def current_native_layer_report(root: Path) -> Generator[CurrentNativeReport]:
    """Hold the actual operation lock through source validation, consumer work and final recheck."""
    with project_lock(root):
        current = _validate(IndexReader(root))
        yield current
        if (
            current.run.implementation_sha256 != implementation_digest()
            or locator_membership(current.reader) != current.run.locator_ledger_paths
        ):
            raise AcquisitionError("native-layer report scope changed during consumption")
        current.reader.recheck()
