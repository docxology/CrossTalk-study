"""Deterministic cover-review queues never promote a first retained page automatically."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.article_records import ArticleError, text_digest
from crosstalk.article_validation import validate_evidence
from crosstalk.cover_records import CoverBinding, CoverDecision

if TYPE_CHECKING:
    from crosstalk.article_records import ArticlePage
    from crosstalk.cover_records import (
        CoverAssessment,
        CoverPageRender,
        CoverUnit,
        WrapperExclusion,
    )


def _wrappers(
    unit: CoverUnit,
    pages: tuple[ArticlePage, ...],
    exclusions: tuple[WrapperExclusion, ...],
) -> tuple[int, ...]:
    lookup = {page.page_index: page for page in pages}
    found: set[int] = set()
    for exclusion in exclusions:
        if exclusion.page_index in found:
            raise ArticleError("cover wrapper decisions repeat a physical page")
        page = lookup.get(exclusion.page_index)
        if (
            page is None
            or exclusion.pdf_sha256 != unit.pdf_sha256
            or exclusion.native_artifact.path != page.artifact_path
            or exclusion.native_artifact.sha256 != page.artifact_sha256
            or exclusion.page_text_sha256 != text_digest(page.text)
        ):
            raise ArticleError("cover wrapper exclusion differs from the current native source")
        found.add(exclusion.page_index)
    return tuple(sorted(found))


def _assessment(
    unit: CoverUnit,
    assessment: CoverAssessment,
    wrappers: tuple[int, ...],
) -> CoverPageRender | None:
    if assessment.unit_id != unit.unit_id or assessment.pdf_sha256 != unit.pdf_sha256:
        raise ArticleError("cover assessment belongs to another source unit")
    scope = set(assessment.inspected_page_indices)
    expected = set(range(unit.physical_pages))
    renders = {item.page_index: item for item in assessment.render_evidence}
    if len(renders) != len(assessment.render_evidence):
        raise ArticleError("cover render evidence repeats a physical page")
    if (
        not scope <= expected
        or set(renders) != scope
        or any(item.pdf_sha256 != unit.pdf_sha256 for item in renders.values())
    ):
        raise ArticleError("cover inspection and exact PDF/render scope disagree")
    if assessment.status == "not-located-in-inspected-pdf" and scope != expected:
        raise ArticleError("not-located cover decision requires the complete inspected PDF scope")
    index = assessment.selected_page_index
    if index is not None:
        if index not in renders or index in wrappers:
            raise ArticleError(
                "selected cover lacks source-image evidence or is an admitted wrapper"
            )
        return renders[index]
    return None


def _native_bindings(pages: tuple[ArticlePage, ...]) -> tuple[CoverBinding, ...]:
    """One current local artifact path cannot claim two different byte versions."""
    artifacts: dict[str, str] = {}
    for page in pages:
        if artifacts.setdefault(page.artifact_path, page.artifact_sha256) != page.artifact_sha256:
            raise ArticleError("cover native artifact path has conflicting byte identities")
    return tuple(CoverBinding(path=path, sha256=sha) for path, sha in sorted(artifacts.items()))


def cover_decision(
    unit: CoverUnit,
    native_pages: tuple[ArticlePage, ...],
    exclusions: tuple[WrapperExclusion, ...] = (),
    assessment: CoverAssessment | None = None,
    *,
    maximum_candidates: int = 3,
) -> CoverDecision:
    """Build a source-accounted slot; callers verify actual pixel and receipt custody."""
    if not 1 <= maximum_candidates <= 5:
        raise ArticleError("cover candidate capacity must be between one and five")
    _ = validate_evidence(native_pages, ())
    if any(
        page.issue_id != unit.issue_id
        or page.pdf_sha256 != unit.pdf_sha256
        or page.layer != "native"
        or page.page_index >= unit.physical_pages
        for page in native_pages
    ):
        raise ArticleError("cover native frame differs from its declared source")
    indices = {page.page_index for page in native_pages}
    complete = indices == set(range(unit.physical_pages))
    wrappers = _wrappers(unit, native_pages, exclusions)
    candidates = tuple(index for index in sorted(indices) if index not in wrappers)[
        :maximum_candidates
    ]
    evidence = (
        unit.catalog_evidence,
        *_native_bindings(native_pages),
        *(row.decision_evidence for row in exclusions),
    )
    if assessment is not None:
        selected = _assessment(unit, assessment, wrappers)
        return CoverDecision(
            unit=unit,
            status=assessment.status,
            candidate_page_indices=candidates,
            selected_page_index=assessment.selected_page_index,
            native_scope_complete=complete,
            selected_role=assessment.selected_role,
            excluded_wrapper_indices=wrappers,
            evidence=(*evidence, assessment.decision_evidence),
            selected_render=selected,
            note=assessment.rationale
            + " Source-image selection only; independent human agreement is unmeasured.",
        )
    return CoverDecision(
        unit=unit,
        status="candidate-first-retained-page" if candidates else "unavailable",
        candidate_page_indices=candidates,
        selected_page_index=None,
        native_scope_complete=complete,
        excluded_wrapper_indices=wrappers,
        evidence=evidence,
        note="Position supplies inspection candidates, not cover identity. "
        + "Unrecognized wrappers may remain; "
        + "missing native pages do not establish absent printed covers.",
    )


def validate_cover_catalog(
    decisions: tuple[CoverDecision, ...], expected_units: tuple[str, ...]
) -> dict[str, int]:
    """Retain all slots and refuse aliases; historical cover coverage remains unknown."""
    for row in decisions:
        _ = CoverDecision.model_validate(row.model_dump(), strict=True)
    if not 1 <= len(expected_units) <= 10_000 or len(set(expected_units)) != len(expected_units):
        raise ArticleError("declared cover source frame is empty, duplicate or oversized")
    units = tuple(row.unit.unit_id for row in decisions)
    pdfs = tuple(row.unit.pdf_sha256 for row in decisions)
    if len(set(units)) != len(units) or set(units) != set(expected_units):
        raise ArticleError("cover catalog does not retain each declared source exactly once")
    if len(set(pdfs)) != len(pdfs):
        raise ArticleError("cover source PDF aliases require source-association reconciliation")
    statuses = (
        "verified-cover",
        "candidate-first-retained-page",
        "not-located-in-inspected-pdf",
        "unavailable",
    )
    counts = {status: sum(row.status == status for row in decisions) for status in statuses}
    roles = {
        role: sum(row.selected_role == role for row in decisions)
        for role in ("front-cover", "issue-front-page")
    }
    return {"declared_source_units": len(units), **counts, **roles}
