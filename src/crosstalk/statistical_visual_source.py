"""Revalidate statistical receipts, live source bytes and guarded catalog coverage."""

from __future__ import annotations

import hashlib
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from crosstalk.acquisition_lock import project_lock
from crosstalk.extraction_method import EXTRACTION_IMPLEMENTATION_FILES
from crosstalk.index_observe import IndexReader
from crosstalk.index_read import current_corpus_index
from crosstalk.index_records import CorpusIndexSummary
from crosstalk.models import AcquisitionError
from crosstalk.statistical_analysis import IMPLEMENTATION_FILES
from crosstalk.statistical_bootstrap import principal_issue
from crosstalk.statistical_records import StatisticalRun
from crosstalk.statistical_source import SAFE_ID, read_artifact
from crosstalk.statistical_visual_records import CoverageObservation

if TYPE_CHECKING:
    from collections.abc import Generator

    from crosstalk.index_records import IndexBinding

RENDER_FILES: Final = (
    "statistical_visual_records.py",
    "statistical_visual_source.py",
    "statistical_svg.py",
    "statistical_distribution_charts.py",
    "statistical_interval_charts.py",
    "statistical_visual_html.py",
    "statistical_scope_report.py",
    "statistical_visual_report.py",
    "statistical_bootstrap.py",
    "index_read.py",
    "index_observe.py",
    "index_identity.py",
    "index_implementation.py",
    "index_records.py",
    "acquisition_lock.py",
    "models.py",
    "records.py",
    *EXTRACTION_IMPLEMENTATION_FILES,
)
CSV_FILES: Final = (
    "statistical_issues.csv",
    "statistical_pages.csv",
    "statistical_images.csv",
    "statistical_bootstrap.csv",
    "statistical_distributions.csv",
    "statistical_decades.csv",
)


def implementation_digest(files: tuple[str, ...]) -> str:
    """Bind the exact imported implementation files, including declared dependencies."""
    digest = hashlib.sha256()
    for filename in files:
        digest.update(filename.encode())
        digest.update(read_artifact(Path(__file__).with_name(filename)))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class VisualInputs:
    """One guarded input snapshot; its reader is a mutable custody accumulator."""

    reader: IndexReader
    statistics_sha256: str
    rendering_sha256: str
    coverage: CoverageObservation

    def snapshot_digest(self) -> str:
        """Hash path/digest pairs and explicit negative observations canonically."""
        digest = hashlib.sha256()
        for binding in self.reader.source_bindings():
            digest.update(binding.model_dump_json().encode())
        for relative in sorted(self.reader.missing):
            digest.update(b"missing\0" + relative.encode())
        return digest.hexdigest()

    def recheck(self, run: StatisticalRun) -> None:
        """All files and both implementations must remain unchanged before publication."""
        self.reader.recheck()
        if (
            implementation_digest(RENDER_FILES) != self.rendering_sha256
            or implementation_digest(IMPLEMENTATION_FILES) != run.implementation_sha256
        ):
            raise AcquisitionError("statistical or rendering implementation changed")


def _expected(reader: IndexReader, relative: str, expected: str) -> None:
    """Admit a current physical file only under its exact recorded digest."""
    if reader.digest(relative).sha256 != expected:
        raise AcquisitionError(f"statistical input changed: {relative}")


def _coverage(reader: IndexReader, run: StatisticalRun, stack: ExitStack) -> CoverageObservation:
    """Keep the current index guard held until the dashboard finishes publication."""
    relative = "data/processed/index/index-summary.jsonl"
    if not reader.path(relative).exists():
        _ = stack.enter_context(project_lock(reader.root))
        reader.missing.add(relative)
        return CoverageObservation(
            available=False,
            reason="Current corpus index unavailable; "
            + "rebuild it to show catalog/acquisition coverage.",
        )
    rows = stack.enter_context(current_corpus_index(reader.root))
    summary = CorpusIndexSummary.model_validate_json(reader.read(relative).strip())
    _ = reader.digest(summary.jsonl_path)
    _ = reader.digest(summary.sqlite_path)
    for binding in summary.source_bindings:
        _expected(reader, binding.path, binding.sha256)
    for missing in summary.missing_inputs:
        if reader.path(missing).exists():
            raise AcquisitionError("index negative observation changed")
        reader.missing.add(missing)
    ids = {row.issue_id for row in rows}
    accepted = {row.issue_id for row in run.issues}
    return CoverageObservation(
        available=True,
        catalog_records=len(rows),
        catalog_reported_total=summary.catalog_reported_total,
        capture_matches_reported=summary.catalog_capture_matches_reported,
        resolved_locators=sum(row.locator_status == "manifest-resolved" for row in rows),
        verified_pdfs=sum(row.pdf.integrity == "verified" for row in rows),
        current_extractions=sum(row.extraction.current for row in rows),
        accepted_indexed_issues=len(accepted & ids),
        uncataloged_accepted_issues=len(accepted - ids),
    )


def _receipts(reader: IndexReader, run: StatisticalRun) -> bytes:
    """Admit one current statistical receipt and its producer/scope observations."""
    raw = reader.read("output/reports/statistics.jsonl")
    if StatisticalRun.model_validate_json(raw.strip()) != run:
        raise AcquisitionError("statistics receipt does not match the requested run")
    if implementation_digest(IMPLEMENTATION_FILES) != run.implementation_sha256:
        raise AcquisitionError("statistical implementation differs from the current receipt")
    for relative, digest in (
        ("output/reports/analysis.jsonl", run.analysis_receipt_sha256),
        ("output/reports/linguistics.jsonl", run.linguistics_receipt_sha256),
        ("output/reports/extraction.jsonl", run.extraction_receipt_sha256),
    ):
        _expected(reader, relative, digest)
    manifest = "data/manifest/issues.jsonl"
    if run.manifest_sha256 is None:
        if reader.path(manifest).exists():
            raise AcquisitionError("statistical manifest appeared after computation")
        reader.missing.add(manifest)
    else:
        _expected(reader, manifest, run.manifest_sha256)
    return raw


def _source_files(reader: IndexReader, run: StatisticalRun) -> None:
    """Admit current observational units and exact PDF/page/image bytes."""
    binding = hashlib.sha256()
    binding.update(run.extraction_receipt_sha256.encode())
    binding.update((run.manifest_sha256 or "missing-manifest").encode())
    if len({row.issue_id for row in run.issues}) != len(run.issues):
        raise AcquisitionError("statistical issue identities are duplicated")
    for issue in run.issues:
        if not SAFE_ID.fullmatch(issue.issue_id):
            raise AcquisitionError("statistical issue identifier is unsafe")
        _expected(reader, f"data/raw/pdf/{issue.issue_id}.pdf", issue.pdf_sha256)
        _expected(
            reader, f"data/processed/pages/{issue.issue_id}.jsonl", issue.page_artifact_sha256
        )
        binding.update(
            issue.model_dump_json(
                include={"issue_id", "pdf_sha256", "page_artifact_sha256"}
            ).encode()
        )
    if binding.hexdigest() != run.source_binding_sha256:
        raise AcquisitionError("statistical source-binding aggregate is malformed")
    for image in run.images:
        if not image.path.startswith("data/processed/images/") or len(Path(image.path).parts) != 4:
            raise AcquisitionError("statistical image path is outside the generated asset pool")
        _expected(reader, image.path, image.image_sha256)
    for filename in CSV_FILES:
        _ = reader.digest("output/data/" + filename)
    _coherent_units(run)


def _coherent_units(run: StatisticalRun) -> None:
    """Keep physical pages and asset pairs on the accepted issue provenance frame."""
    if (
        sum(row.extraction_status == "complete" for row in run.issues)
        != run.complete_extraction_issue_units
        or sum(row.extraction_status == "partial" for row in run.issues)
        != run.partial_extraction_issue_units
        or sum(row.total_pdf_pages is None for row in run.issues)
        != run.unknown_page_coverage_issue_units
        or sum(principal_issue(row) for row in run.issues) != run.principal_diagnostic_issue_units
    ):
        raise AcquisitionError("statistical extraction-scope accounting is inconsistent")
    sources = {row.issue_id: (row.pdf_sha256, row.page_artifact_sha256) for row in run.issues}
    if any(
        sources.get(row.issue_id) != (row.pdf_sha256, row.page_artifact_sha256)
        for row in (*run.pages, *run.images)
    ):
        raise AcquisitionError("statistical page/image units disagree with accepted issue sources")
    counts = Counter(row.issue_id for row in run.pages)
    if any(counts[row.issue_id] != row.pages for row in run.issues) or len(
        {(row.issue_id, row.page_index) for row in run.pages}
    ) != len(run.pages):
        raise AcquisitionError("statistical physical-page scope is duplicated or incomplete")
    pairs = {(row.issue_id, row.image_sha256) for row in run.images}
    if (
        len(pairs) != len(run.images)
        or len({row.image_sha256 for row in run.images}) != run.unique_saved_assets
    ):
        raise AcquisitionError("statistical image pair/asset accounting is inconsistent")


@contextmanager
def statistical_visual_inputs(root: Path, run: StatisticalRun) -> Generator[VisualInputs]:
    """Refuse stale results before scientific values can become published figures."""
    reader = IndexReader(root)
    raw = _receipts(reader, run)
    _source_files(reader, run)
    with ExitStack() as stack:
        coverage = _coverage(reader, run, stack)
        inputs = VisualInputs(
            reader, hashlib.sha256(raw).hexdigest(), implementation_digest(RENDER_FILES), coverage
        )
        inputs.recheck(run)
        yield inputs
        inputs.recheck(run)


def binding_rows(inputs: VisualInputs) -> tuple[IndexBinding, ...]:
    """Expose the immutable source snapshot used in HTML and the report receipt."""
    return inputs.reader.source_bindings()
