"""Exact page joins retain text-layer/view denominators and issue-level aggregation units."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from crosstalk.study_cluster_records import ClusterBinding  # noqa: TC001 -- Pydantic runtime field.

if TYPE_CHECKING:
    from crosstalk.study_cluster_records import ClusterModel, ClusterRun
from crosstalk.study_language_records import Digest, Record, StudyError


class TargetCount(Record):
    """Declared lexical target counts are retrieval proxies, not validated meanings."""

    target: str = Field(min_length=1, max_length=120)
    count: int = Field(ge=0)


class PageLexicalCounts(Record):
    """One current PDF/page/text-view observation; unavailable is never a zero count."""

    issue_id: str
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    layer: Literal["native", "ocr"]
    view_name: str = Field(min_length=1, max_length=200)
    tokenizer_sha256: Digest
    status: Literal["measured", "view-excluded", "missing", "refused", "failed", "unattempted"]
    tokens: int | None = Field(default=None, ge=0)
    hits: tuple[TargetCount, ...] = ()
    source_bindings: tuple[ClusterBinding, ...] = Field(min_length=1, max_length=8)

    @property
    def page_key(self) -> str:
        """The join uses exact physical identity, never a coincident page number."""
        return f"{self.pdf_sha256}:{self.page_index}"

    @model_validator(mode="after")
    def denominator(self) -> PageLexicalCounts:
        """A target count cannot exceed its own token opportunities or impersonate missing data."""
        if self.status == "measured":
            if self.tokens is None or any(row.count > self.tokens for row in self.hits):
                raise StudyError("cluster-language target count exceeds its own opportunities")
        elif self.tokens is not None or self.hits:
            raise StudyError(
                "unavailable cluster-language rows cannot supply observed token counts"
            )
        if len({row.target for row in self.hits}) != len(self.hits):
            raise StudyError("cluster-language page repeats a target")
        return self


class PageLanguageFrame(Record):
    """One declared tokenizer/view/layer; a separate call is required for another layer."""

    layer: Literal["native", "ocr"]
    view_name: str = Field(min_length=1, max_length=200)
    tokenizer_sha256: Digest
    source_frame_receipt: ClusterBinding
    targets: tuple[str, ...] = Field(min_length=1, max_length=100)
    pages: tuple[PageLexicalCounts, ...] = Field(max_length=30_000)


class TargetRate(Record):
    """Raw numerator and denominator accompany every descriptive lexical rate."""

    target: str
    hits: int
    tokens: int
    per_1000_tokens: float | None


class IssueClusterLanguage(Record):
    """Within-issue aggregation prevents projecting page counts into independent replicates."""

    issue_id: str
    cluster_id: str
    assigned_visual_pages: int
    language_state_counts: tuple[tuple[str, int], ...]
    positive_token_pages: int
    zero_token_pages: int
    rates: tuple[TargetRate, ...]


class ClusterLanguageJoin(Record):
    """A descriptive source-matched view, not a significance test or semantic topic model."""

    clustering_frame_sha256: Digest
    clustering_k: int
    language_frame_sha256: Digest
    layer: Literal["native", "ocr"]
    view_name: str
    tokenizer_sha256: Digest
    source_frame_receipt: ClusterBinding
    issue_cluster_rows: tuple[IssueClusterLanguage, ...]
    language_pages_outside_visual_assignments: tuple[str, ...]
    interpretation: str = (
        "Source-matched descriptive rates; no causal or page-independent inference."
    )


def _admit_language(frame: PageLanguageFrame) -> dict[str, PageLexicalCounts]:
    """Refuse duplicate/aliased pages and nonuniform target opportunities."""
    if len(set(frame.targets)) != len(frame.targets):
        raise StudyError("cluster-language target names repeat")
    pages: dict[str, PageLexicalCounts] = {}
    issues: dict[str, str] = {}
    pdfs: dict[str, str] = {}
    for page in frame.pages:
        if (
            page.layer != frame.layer
            or page.view_name != frame.view_name
            or page.tokenizer_sha256 != frame.tokenizer_sha256
        ):
            raise StudyError("cluster-language frame mixes text layers, views or tokenizer methods")
        if (
            page.page_key in pages
            or issues.setdefault(page.issue_id, page.pdf_sha256) != page.pdf_sha256
            or pdfs.setdefault(page.pdf_sha256, page.issue_id) != page.issue_id
        ):
            raise StudyError("cluster-language physical source identity requires reconciliation")
        if page.status == "measured" and {row.target for row in page.hits} != set(frame.targets):
            raise StudyError(
                "cluster-language measured row omits a declared target, including explicit zeros"
            )
        pages[page.page_key] = page
    return pages


def _check_join_sources(run: ClusterRun, model: ClusterModel, frame: PageLanguageFrame) -> None:
    """Known issue/PDF aliases refuse even when their changed key would otherwise be unmatched."""
    sources = (*model.assignments, *run.excluded_pages)
    issues = {row.issue_id: row.pdf_sha256 for row in sources}
    pdfs = {row.pdf_sha256: row.issue_id for row in sources}
    for page in frame.pages:
        if (page.issue_id in issues and issues[page.issue_id] != page.pdf_sha256) or (
            page.pdf_sha256 in pdfs and pdfs[page.pdf_sha256] != page.issue_id
        ):
            raise StudyError("cluster-language issue/PDF identity disagrees across source families")


def join_language(
    run: ClusterRun, model: ClusterModel, frame: PageLanguageFrame
) -> ClusterLanguageJoin:
    """Aggregate declared target opportunities by issue/group without fusing native and OCR."""
    if model not in run.models or model.frame_sha256 != run.frame_sha256 or not model.assignments:
        raise StudyError(
            "cluster-language join requires one actual fitted model from the selected run"
        )
    frame = PageLanguageFrame.model_validate(frame.model_dump(mode="python"), strict=True)
    _check_join_sources(run, model, frame)
    language = _admit_language(frame)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    visual = {row.page_key: row for row in model.assignments}
    for assignment in model.assignments:
        source = language.get(assignment.page_key)
        if source is not None and source.issue_id != assignment.issue_id:
            raise StudyError("cluster-language issue identity disagrees across source families")
        groups[assignment.issue_id, assignment.cluster_id].append(assignment.page_key)
    results: list[IssueClusterLanguage] = []
    for (issue, cluster), keys in sorted(groups.items()):
        states: Counter[str] = Counter()
        totals: Counter[str] = Counter(dict.fromkeys(frame.targets, 0))
        tokens = positive = zero = 0
        for key in keys:
            page = language.get(key)
            states[page.status if page is not None else "not-supplied"] += 1
            if page is not None and page.status == "measured" and page.tokens is not None:
                tokens += page.tokens
                positive += int(page.tokens > 0)
                zero += int(page.tokens == 0)
                totals.update({row.target: row.count for row in page.hits})
        results.append(
            IssueClusterLanguage(
                issue_id=issue,
                cluster_id=cluster,
                assigned_visual_pages=len(keys),
                language_state_counts=tuple(sorted(states.items())),
                positive_token_pages=positive,
                zero_token_pages=zero,
                rates=tuple(
                    TargetRate(
                        target=target,
                        hits=totals[target],
                        tokens=tokens,
                        per_1000_tokens=1000 * totals[target] / tokens if tokens else None,
                    )
                    for target in frame.targets
                ),
            )
        )
    return ClusterLanguageJoin(
        clustering_frame_sha256=run.frame_sha256,
        clustering_k=model.k,
        language_frame_sha256=hashlib.sha256(frame.model_dump_json().encode()).hexdigest(),
        layer=frame.layer,
        view_name=frame.view_name,
        tokenizer_sha256=frame.tokenizer_sha256,
        source_frame_receipt=frame.source_frame_receipt,
        issue_cluster_rows=tuple(results),
        language_pages_outside_visual_assignments=tuple(sorted(set(language) - set(visual))),
    )
