"""Admit observed official PDF locators without replacing reviewed inventory rows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.acquisition_lock import project_lock
from crosstalk.models import AcquisitionError, Issue, safe_directory
from crosstalk.signposting_custody import read_bound_metadata, require_retained_policy
from crosstalk.signposting_parse import content_url, parse_observation, requested_item
from crosstalk.signposting_records import LocatorImportResult, LocatorObservation
from crosstalk.signposting_store import atomic_bytes, immutable_bytes, read_catalog, read_manifest

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.catalog import CatalogIssue
    from crosstalk.signposting_records import SignpostingSnapshot
    from crosstalk.signposting_store import CatalogState, ManifestState


@dataclass(frozen=True, slots=True)
class AdmissionContext:
    """The independently bound original inputs used by one conditional append."""

    snapshot: SignpostingSnapshot
    row: CatalogIssue
    observation: LocatorObservation
    catalog: CatalogState
    manifest: ManifestState


def _compatible(existing: Issue, row: CatalogIssue, pdf_url: str) -> bool:
    """Unknown item metadata alone cannot establish publication identity."""
    try:
        return (
            existing.issue_id == row.issue_id
            and existing.item_id in {None, row.item_id}
            and existing.landing_url == row.landing_url
            and content_url(existing.pdf_url) == pdf_url
        )
    except ValueError:
        return False


def _retained_observation(root: Path, observation: LocatorObservation) -> None:
    """Keep each normalized result once, independently of whether an append follows."""
    payload = (observation.model_dump_json() + "\n").encode()
    digest = hashlib.sha256(payload).hexdigest()
    directory = safe_directory(root, "output/data/locator-observations")
    immutable_bytes(directory / f"{digest}.json", payload)


def _append_issue(root: Path, admission: AdmissionContext) -> bytes:
    """Revalidate originals immediately before the atomic new-row append."""
    snapshot, row, observation = admission.snapshot, admission.row, admission.observation
    catalog, manifest = admission.catalog, admission.manifest
    if read_catalog(root).sha256 != catalog.sha256 or read_manifest(root).raw != manifest.raw:
        raise AcquisitionError("locator inputs changed before manifest admission")
    if observation.pdf_url is None:
        raise AcquisitionError("resolved locator lacks its observed PDF URL")
    _ = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
    require_retained_policy(root, snapshot)
    issue = Issue(
        issue_id=row.issue_id,
        item_id=row.item_id,
        title=row.title,
        issued=row.issued_metadata,
        landing_url=row.landing_url,
        pdf_url=observation.pdf_url,
    )
    original = manifest.raw or b""
    separator = b"\n" if original and not original.endswith(b"\n") else b""
    payload = original + separator + (issue.model_dump_json() + "\n").encode()
    directory = safe_directory(root, "data/manifest")
    # This exact catalog binding was checked above; response metadata never supplies titles.
    if snapshot.catalog_sha256 != catalog.sha256:
        raise AcquisitionError("locator snapshot catalog binding changed")
    _ = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
    require_retained_policy(root, snapshot)
    atomic_bytes(directory / "issues.jsonl", payload)
    return payload


def admit_signposting_snapshot_locked(
    root: Path, snapshot: SignpostingSnapshot
) -> LocatorImportResult:
    """Internal admission called only while the resolver holds the actual project lock.

    The network resolver and the public wrapper share this operation; no boolean
    bypass or nested non-reentrant lock is used. A retained response proves only
    its recorded locator observation, never PDF-byte integrity or corpus coverage.
    """
    identity = requested_item(snapshot)
    catalog = read_catalog(root)
    if snapshot.catalog_sha256 != catalog.sha256:
        raise AcquisitionError("locator response is bound to a different current catalog")
    row = next((row for row in catalog.rows if row.item_id == identity), None)
    if row is None:
        raise AcquisitionError("locator request UUID is outside the current CrossTalk catalog")
    require_retained_policy(root, snapshot)
    observation = parse_observation(root, snapshot, row)
    manifest = read_manifest(root)
    existing = next((issue for issue in manifest.rows if issue.issue_id == row.issue_id), None)
    # A second slug for the same publication is a conflict, never a new independent issue.
    alias = any(
        issue.issue_id != row.issue_id
        and (issue.item_id == row.item_id or issue.landing_url == row.landing_url)
        for issue in manifest.rows
    )
    resolved = observation.status == "resolved" and observation.pdf_url is not None
    if resolved and (
        alias
        or (existing is not None and not _compatible(existing, row, observation.pdf_url or ""))
    ):
        observation = observation.model_copy(
            update={
                "status": "manifest-conflict",
                "reason": "Reviewed manifest identity or PDF differs; original row was preserved",
            }
        )
    _retained_observation(root, observation)
    added = observation.status == "resolved" and existing is None and not alias
    raw = (
        _append_issue(root, AdmissionContext(snapshot, row, observation, catalog, manifest))
        if added
        else manifest.raw
    )
    return LocatorImportResult(
        observation=observation,
        added=added,
        manifest_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
    )


def import_signposting_snapshot(root: Path, snapshot: SignpostingSnapshot) -> LocatorImportResult:
    """Import one retained response under the same lock used by network acquisition."""
    with project_lock(root):
        return admit_signposting_snapshot_locked(root, snapshot)
