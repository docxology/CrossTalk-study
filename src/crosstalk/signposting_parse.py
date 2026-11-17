"""Parse exact observed PDF relations from an official item-specific linkset."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit
from uuid import UUID

from crosstalk.models import AcquisitionError, require_nps_url
from crosstalk.signposting_custody import read_bound_metadata
from crosstalk.signposting_records import LinksetDocument, LocatorObservation

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.catalog import CatalogIssue
    from crosstalk.signposting_records import LinkContext, SignpostingSnapshot

REQUEST_PATH: Final = re.compile(r"^/server/signposting/linksets/([0-9a-fA-F-]{36})/json$")
PDF_PATH: Final = re.compile(
    r"^/(?:bitstreams/([0-9a-fA-F-]{36})/download|server/api/core/bitstreams/([0-9a-fA-F-]{36})/content)$"
)


def requested_item(snapshot: SignpostingSnapshot) -> str:
    """Bind an observation to an exact, supported item-specific request URI."""
    parsed = urlsplit(require_nps_url(snapshot.request_url))
    found = REQUEST_PATH.fullmatch(parsed.path)
    if parsed.hostname != "calhoun.nps.edu" or parsed.query or found is None:
        raise AcquisitionError("locator snapshot must name the exact official item linkset route")
    if snapshot.final_url is not None and snapshot.final_url != snapshot.request_url:
        raise AcquisitionError("locator response was redirected away from its recorded item route")
    return str(UUID(found.group(1)))


def content_url(published: str) -> str:
    """Transform only an actually observed official bitstream UUID into its content route."""
    parsed = urlsplit(require_nps_url(published))
    found = PDF_PATH.fullmatch(parsed.path)
    if parsed.hostname != "calhoun.nps.edu" or parsed.query or found is None:
        raise AcquisitionError("observed PDF relation uses an unsupported official bitstream path")
    identifier = str(UUID(found.group(1) or found.group(2)))
    return f"https://calhoun.nps.edu/server/api/core/bitstreams/{identifier}/content"


def _handle(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "hdl.handle.net"
        and bool(re.fullmatch(r"/10945/\d+", parsed.path))
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
    )


def _contexts(document: LinksetDocument, row: CatalogIssue) -> tuple[LinkContext, ...]:
    exact = tuple(context for context in document.linkset if context.anchor == row.landing_url)
    if exact:
        return exact
    # The exact request UUID supplies identity; an alternate anchor must explicitly be cite-as.
    handles = tuple(
        context
        for context in document.linkset
        if _handle(context.anchor)
        and any(target.href == context.anchor for target in context.cite_as)
    )
    if len(handles) == 1:
        return handles
    raise AcquisitionError("linkset has no unambiguous publication or self-linked handle anchor")


def parse_observation(
    root: Path, snapshot: SignpostingSnapshot, row: CatalogIssue
) -> LocatorObservation:
    """Retain refusal states rather than guessing among missing, unknown or multiple PDFs."""
    identity = requested_item(snapshot)
    if identity != row.item_id:
        raise AcquisitionError("item request UUID disagrees with its catalog member")
    base = LocatorObservation(
        snapshot_sha256=hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest(),
        body_sha256=snapshot.body_sha256,
        catalog_sha256=snapshot.catalog_sha256,
        robots_sha256=snapshot.robots_sha256,
        observed_at=snapshot.observed_at,
        request_url=snapshot.request_url,
        item_id=identity,
        issue_id=row.issue_id,
        status="invalid-response",
    )
    try:
        if snapshot.status_code != 200 or snapshot.content_type.split(";", 1)[
            0
        ].strip().casefold() not in {"application/linkset+json", "application/json"}:
            raise AcquisitionError("linkset response status or media type is unavailable")
        raw = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
        document = LinksetDocument.model_validate_json(raw)
        contexts = _contexts(document, row)
        candidates: dict[str, str] = {}
        for context in contexts:
            for target in context.items:
                if (
                    target.media_type is not None
                    and target.media_type.split(";", 1)[0].strip().casefold() == "application/pdf"
                ):
                    _ = candidates.setdefault(content_url(target.href), target.href)
        _ = read_bound_metadata(root, snapshot.body_path, snapshot.body_sha256)
        if len(candidates) != 1:
            return base.model_copy(
                update={
                    "status": "no-pdf" if not candidates else "ambiguous-pdf",
                    "reason": "No unique typed application/pdf item relation was observed",
                }
            )
        canonical, published = next(iter(candidates.items()))
        return base.model_copy(
            update={
                "status": "resolved",
                "pdf_url": canonical,
                "published_pdf_url": published,
                "cite_as": tuple(
                    sorted({target.href for context in contexts for target in context.cite_as})
                ),
                "license_links": tuple(
                    sorted({target.href for context in contexts for target in context.licenses})
                ),
            }
        )
    except (OSError, ValueError) as error:
        return base.model_copy(update={"reason": str(error)})
