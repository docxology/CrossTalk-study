"""Retain source-bound native sensitivity drawings without replacing prior vector evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.dossier_records import DossierFigure
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import AcquisitionError, safe_directory
from crosstalk.native_view_figure import NativeFigureProof, native_view_svg

if TYPE_CHECKING:
    from crosstalk.native_layer_read import CurrentNativeReport

RENDER_FILES: Final = (
    "native_view_figure.py",
    "native_view_store.py",
    "statistical_svg.py",
    "statistical_visual_records.py",
    "dossier_records.py",
    "locator_storage.py",
    "acquisition_ledger.py",
    "models.py",
    "records.py",
)


def implementation_digest() -> str:
    """Frame each local rendering member by name, length and actual content digest."""
    members: list[tuple[str, int, str]] = []
    for name in RENDER_FILES:
        path = Path(__file__).parent / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise AcquisitionError("native vector implementation is unavailable or oversized")
        raw = path.read_bytes()
        members.append((name, len(raw), hashlib.sha256(raw).hexdigest()))
    return hashlib.sha256(json.dumps(members, separators=(",", ":")).encode()).hexdigest()


def publish_native_view(root: Path, current: CurrentNativeReport) -> DossierFigure:
    """Adopt only a held current report and preserve immutable SVG generations by digest."""
    run = current.run
    proof = NativeFigureProof(
        native_report_sha256=current.receipt.summary_sha256,
        implementation_sha256=implementation_digest(),
        settings_sha256=hashlib.sha256(run.settings.model_dump_json().encode()).hexdigest(),
        input_bindings_sha256=hashlib.sha256(
            ("[" + ",".join(row.model_dump_json() for row in run.input_bindings) + "]").encode()
        ).hexdigest(),
    )
    raw = native_view_svg(run, proof).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = publish_metadata(
        safe_directory(root, "output/figures/statistics"), f"native-views-{digest}.svg", raw
    )
    if implementation_digest() != proof.implementation_sha256:
        raise AcquisitionError("native vector implementation changed during drawing")
    relative = path.relative_to(root).as_posix()
    if current.reader.digest(relative).sha256 != digest:
        raise AcquisitionError("native vector bytes changed after publication")
    return DossierFigure(
        title="Native-text view sensitivity",
        path=relative,
        sha256=digest,
        caption=(
            "Teal: pooled token rate. Coral: equal-issue mean. Each mark has its own eligible n; "
            + "workflow-selected n is shown separately. Threshold rows share the wrapper-minus "
            + "basis: low-text page fraction is extraction-flagged low-text pages divided by "
            + "physical pages retained in that view. Circles and bars show "
            + f"{run.settings.bootstrap.confidence:.0%} nominal marginal conditional whole-issue "
            + "percentile diagnostics. Squares retain below-gate points without intervals; "
            + "NA means undefined. Eligible frames can differ across views. These are lexical "
            + "proxies, without joint-family coverage, paired differences, causal effects, or "
            + "extraction/template-rule uncertainty. "
            + f"Source kind: {run.settings.source_kind}. Native report SHA-256: "
            + current.receipt.summary_sha256
        ),
    )
