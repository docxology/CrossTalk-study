"""Compile a dossier from live, digest-checked project evidence and manuscript."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from crosstalk.catalog import CatalogIssue, CatalogSummary
from crosstalk.dossier_cases import case_evidence
from crosstalk.dossier_markdown import manuscript_sections
from crosstalk.dossier_pdf import build_dossier
from crosstalk.dossier_records import (
    DossierAuthor,
    DossierBuild,
    DossierEvidence,
    DossierInput,
    DossierMethod,
    DossierReference,
    DossierSection,
    SourceBinding,
    YearCount,
)
from crosstalk.dossier_statistics import current_statistics
from crosstalk.dossier_supplement import supplemental_evidence
from crosstalk.index_identity import valid_manifest_binding
from crosstalk.index_read import read_corpus_index
from crosstalk.models import SERIES_ID, AcquisitionError, file_digest, load_manifest, safe_directory
from crosstalk.records import Record

if TYPE_CHECKING:
    from pathlib import Path


class ManuscriptReference(DossierReference):
    """A primary-source reference with its manuscript citation key."""

    key: str
    short_label: str


class DossierConfiguration(Record):
    """Editable document metadata; quantities are deliberately absent."""

    title: str = "CrossTalk"
    subtitle: str
    version: str
    case_ledger: Literal["manuscript/case-readings.json"] | None = None
    supplemental_figures: Literal["manuscript/supplemental-figures.json"] | None = None
    authors: Annotated[tuple[DossierAuthor, ...], Field(min_length=1, max_length=6)]
    references: tuple[ManuscriptReference, ...]
    methods: Annotated[tuple[DossierMethod, ...], Field(min_length=3, max_length=3)]


def _local_file(root: Path, relative: str) -> Path:
    """Require a bounded physical input inside the project directory."""
    path = root / relative
    _ = safe_directory(root, str(path.relative_to(root).parent))
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 250_000_000:
        raise AcquisitionError(
            f"Dossier input is unavailable or exceeds its byte bound: {relative}"
        )
    return path


def render_project_dossier(
    root: Path, source_revision: str = "Uncommitted working tree; exact input digests recorded"
) -> DossierBuild:
    """Recompute current metrics and bind every source before rendering pages."""
    config_path = _local_file(root, "manuscript/dossier.json")
    catalog_path = _local_file(root, "data/manifest/catalog.jsonl")
    observation_path = _local_file(root, "data/manifest/catalog-observation.jsonl")
    manifest_path = _local_file(root, "data/manifest/issues.jsonl")
    extraction_path = _local_file(root, "output/reports/extraction.jsonl")
    manuscripts = tuple(sorted((root / "manuscript").glob("[0-8][0-9]_*.md")))
    paths = {
        config_path,
        catalog_path,
        observation_path,
        manifest_path,
        extraction_path,
        *manuscripts,
    }
    for directory, pattern in (
        ("src/crosstalk", "*.py"),
        ("data/raw/pdf", "*.pdf"),
        ("data/processed/pages", "*.jsonl"),
        ("data/processed/images", "*"),
    ):
        _ = safe_directory(root, directory)
        paths.update(
            path
            for path in (root / directory).glob(pattern)
            if directory != "data/processed/images" or not path.name.startswith(".locator-")
        )
    paths.update(
        path
        for path in (
            root / "manuscript/references.bib",
            root / "manuscript/config.yaml",
            root / "pyproject.toml",
            root / "uv.lock",
        )
        if path.is_file()
    )
    if len(paths) > 20_000:
        raise AcquisitionError("Dossier input inventory exceeds the 20,000-file bound")
    before = {
        path: file_digest(_local_file(root, path.relative_to(root).as_posix()))
        for path in sorted(paths)
    }
    config = DossierConfiguration.model_validate_json(config_path.read_bytes())
    cases = case_evidence(root, config.case_ledger, before)
    before.update((root / row.path, row.sha256) for row in cases.bindings)
    rows = tuple(
        CatalogIssue.model_validate_json(line) for line in catalog_path.read_text().splitlines()
    )
    observation = CatalogSummary.model_validate_json(observation_path.read_bytes())
    ids = {row.issue_id for row in rows}
    if (
        len(ids) != len(rows)
        or observation.records != len(rows)
        or any(
            row.series_id != SERIES_ID or row.source_snapshot_sha256 != observation.snapshot_sha256
            for row in rows
        )
    ):
        raise AcquisitionError("Catalog observations disagree; dossier counts are unavailable")
    inventory = load_manifest(manifest_path)
    catalog_rows = {row.issue_id: row for row in rows}
    if any(
        issue.issue_id not in ids or not valid_manifest_binding(catalog_rows[issue.issue_id], issue)
        for issue in inventory
    ):
        raise AcquisitionError("Reviewed inventory disagrees with captured catalog identity")
    statistics = current_statistics(root)
    analysis = statistics.analysis
    if any(issue.issue_id not in {row.issue_id for row in inventory} for issue in analysis.issues):
        raise AcquisitionError("Analyzed PDFs lack reviewed inventory/catalog membership")
    years = Counter(
        int(row.issued_metadata[:4]) for row in rows if row.issued_metadata and not row.flags
    )
    downloaded = {
        row.issue_id for row in read_corpus_index(root) if row.pdf.integrity == "verified"
    }
    pilot = analysis.issues[0] if analysis.issues else None
    evidence = DossierEvidence(
        catalog_records=len(rows),
        downloaded_issues=len(downloaded),
        catalog_reported_total=observation.reported_total,
        catalog_capture_matches_reported=(
            len(rows) == observation.reported_total and observation.matches_reported_total
        ),
        analyzed_issues=len(analysis.issues),
        pages=sum(issue.pages for issue in analysis.issues),
        images=len({image.sha256 for issue in analysis.issues for image in issue.images}),
        tokens=analysis.corpus_text.tokens,
        unresolved_records=len(ids.difference(issue.issue_id for issue in inventory)),
        date_conflicts=sum("title-metadata-year-conflict" in row.flags for row in rows),
        low_text_pages=sum(issue.low_text_pages for issue in analysis.issues),
        year_counts=tuple(
            YearCount(year=year, count=count) for year, count in sorted(years.items())
        ),
        pilot_title=pilot.title if pilot else "No source-verified analysis available",
        pilot_url=pilot.source_url if pilot else None,
        pilot_sha256=pilot.source_sha256 if pilot else None,
    )
    quantities = {
        "CATALOG_ITEMS": str(evidence.catalog_records),
        "PILOT_ISSUES": str(evidence.analyzed_issues),
        "PILOT_PAGES": str(evidence.pages),
        "PILOT_DISTINCT_IMAGES": str(evidence.images),
        "PILOT_TOKENS": f"{evidence.tokens:,}",
        "CATALOG_CAPTURE_STATUS": (
            "The retained count agrees with the listing's reported total of "
            + f"{observation.reported_total}."
            if evidence.catalog_capture_matches_reported
            else f"The listing reported {observation.reported_total}; "
            + "the retained rows or observation do not establish a matching capture, "
            + "so catalog coverage remains partial or unavailable."
        ),
        "CURRENT_SOURCE_STATUS": (
            "Current source and extraction checks accept "
            + f"{evidence.analyzed_issues} source-distinct issue PDF(s), "
            + f"totaling {evidence.pages} physical pages."
            if analysis.issues
            else "Current checks accept no source-verified issue PDF. "
            + "Zero values below describe an unavailable accepted subset, "
            + "not a measured absence of journal material."
        ),
        "CURRENT_PIPELINE_STATUS": (
            "The accepted local subset supplies operational observations of "
            + "source-linked page extraction, embedded-image inventory, "
            + "lexical measurement and reporting."
            if analysis.issues
            else "No current source-verified subset is available to support a claim "
            + "that the journal-analysis path succeeded in this build. "
            + "Prior pilot results remain historical observations until revalidated."
        ),
    }
    citations = {
        **{reference.key: reference.short_label for reference in config.references},
        "sec:methods": "Methods",
        "sec:introduction": "Introduction",
        "sec:results": "Results and limitations",
        "sec:roadmap": "Implementation roadmap",
        "sec:rubric": "Review rubric",
    }
    if any(file_digest(path) != digest for path, digest in before.items()):
        raise AcquisitionError("Dossier inputs changed while compiling current evidence")
    analysis_path = _local_file(root, "output/reports/analysis.jsonl")
    before[analysis_path] = file_digest(analysis_path)
    for binding in statistics.bindings:
        path = _local_file(root, binding.path)
        if file_digest(path) != binding.sha256:
            raise AcquisitionError("Statistical dossier inputs changed during compilation")
        before[path] = binding.sha256
    supplement = supplemental_evidence(root, config.supplemental_figures, before)
    before.update((root / row.path, row.sha256) for row in supplement.bindings)
    bindings = tuple(
        SourceBinding(path=path.relative_to(root).as_posix(), sha256=digest)
        for path, digest in sorted(before.items())
    )
    content = DossierInput(
        title=config.title,
        subtitle=config.subtitle,
        observed_at=datetime.now(UTC).isoformat(),
        version=config.version,
        authors=config.authors,
        evidence=evidence,
        sections=(
            *manuscript_sections(manuscripts, quantities, citations),
            statistics.section,
            DossierSection(
                title="Current analyzed source inventory",
                paragraphs=tuple(
                    f"{issue.title}. Stable source: {issue.source_url or 'unavailable'}. "
                    + f"PDF SHA-256: {issue.source_sha256}. "
                    + f"Accepted extraction: {issue.pages} physical pages."
                    for issue in analysis.issues
                )
                or ("No current source-verified issue was accepted.",),
            ),
        ),
        references=tuple(
            DossierReference(label=ref.label, url=ref.url) for ref in config.references
        ),
        source_revision=source_revision,
        source_bindings=bindings,
        methods=config.methods,
        figures=(*statistics.figures, *supplement.figures),
    )
    cases.recheck(root)
    supplement.recheck(root)
    return build_dossier(root, content)
