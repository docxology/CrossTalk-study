"""Cross-field native/visual scope checks, independent from schema construction."""

from __future__ import annotations

from typing import Literal, Protocol


class IssueScope(Protocol):
    """Readonly issue fields avoid a schema-construction dependency cycle."""

    @property
    def visual_status(self) -> str:
        """Expose the declared visual coverage state."""
        ...

    @property
    def measured_distinct_assets(self) -> int | None:
        """Expose measured saved assets without inventing historical missingness."""
        ...


class RunScope(Protocol):
    """Only fields required to validate the new explicitly separate denominators."""

    method_version: Literal["2", "3"]
    native_text_issue_units: int | None
    pixel_measured_issue_units: int | None
    visual_partial_issue_units: int | None
    visual_unavailable_issue_units: int | None
    visual_complete_scope_issue_units: int | None

    @property
    def issues(self) -> tuple[IssueScope, ...]:
        """Expose a covariant readonly issue sequence."""
        ...


def require_native_visual_scope(run: RunScope) -> None:
    """Legacy missingness stays unavailable; current scope must equal its actual issue states."""
    observed = (
        run.native_text_issue_units,
        run.pixel_measured_issue_units,
        run.visual_partial_issue_units,
        run.visual_unavailable_issue_units,
        run.visual_complete_scope_issue_units,
    )
    if run.method_version == "2":
        if any(value is not None for value in observed) or any(
            issue.visual_status != "legacy-unobserved" for issue in run.issues
        ):
            message = "legacy statistics cannot carry new native/visual scope evidence"
            raise ValueError(message)
        return
    expected = (
        len(run.issues),
        sum(bool(issue.measured_distinct_assets) for issue in run.issues),
        sum(issue.visual_status == "partial" for issue in run.issues),
        sum(issue.visual_status == "unavailable" for issue in run.issues),
        sum(
            issue.visual_status in {"complete-declared-raster-scope", "empty-declared-raster-scope"}
            for issue in run.issues
        ),
    )
    if observed != expected or any(
        issue.visual_status == "legacy-unobserved" or issue.measured_distinct_assets is None
        for issue in run.issues
    ):
        message = "current native/visual statistical scope disagrees with accepted observations"
        raise ValueError(message)
