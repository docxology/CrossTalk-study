"""One conservative publication-identity boundary shared by index and dossier consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crosstalk.catalog import CatalogIssue
    from crosstalk.models import Issue


def valid_manifest_binding(catalog_row: CatalogIssue, issue: Issue | None) -> bool:
    """Require the exact captured locator; alternate locators need reviewed equivalence evidence."""
    return (
        issue is not None
        and issue.issue_id == catalog_row.issue_id
        and issue.series_id == catalog_row.series_id
        and issue.landing_url == catalog_row.landing_url
        and (issue.item_id is None or issue.item_id == catalog_row.item_id)
    )
