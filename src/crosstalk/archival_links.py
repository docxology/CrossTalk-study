"""Observe actual issue anchors; no monthly URL pattern ever generates a locator."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from typing import TYPE_CHECKING, override
from urllib.parse import urljoin

from crosstalk.archival_records import ArchivalCandidate, ArchivalError, archive_url
from crosstalk.holdings_reconcile import record_sha256

if TYPE_CHECKING:
    from crosstalk.archival_http import ArchivalBody
    from crosstalk.holdings_records import IssueAssertion


class IssueAnchors(HTMLParser):
    """Mutable HTML token accumulator retaining exact href values and visible anchor labels."""

    href: str | None
    text: list[str]
    links: list[tuple[str, str]]

    def __init__(self) -> None:
        """Observe ordinary anchors without executing scripts or requesting resources."""
        super().__init__(convert_charrefs=True)
        self.href = None
        self.text = []
        self.links = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Retain a real href when an HTML anchor begins."""
        if tag == "a":
            self.href = next((value for name, value in attrs if name == "href"), None)
            self.text = []

    @override
    def handle_data(self, data: str) -> None:
        """Anchor text can span nested presentation elements."""
        if self.href is not None:
            self.text.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        """Finish the observed link without inventing missing labels or targets."""
        if tag == "a" and self.href is not None:
            self.links.append((" ".join("".join(self.text).split()), self.href))
            self.href = None


def observed_candidates(
    body: ArchivalBody, expected: tuple[IssueAssertion, ...]
) -> tuple[ArchivalCandidate, ...]:
    """Match explicit source assertion labels to actual source-family hrefs in retained HTML."""
    if (
        not body.response.complete
        or body.response.status_code != 200
        or hashlib.sha256(body.raw).hexdigest() != body.response.body_sha256
    ):
        raise ArchivalError(
            "candidate discovery requires complete independently hashed HTTP200 HTML"
        )
    parser = IssueAnchors()
    try:
        parser.feed(body.raw.decode("utf-8-sig"))
    except UnicodeError as error:
        raise ArchivalError("retained archive HTML is not UTF-8") from error
    response_sha = hashlib.sha256(body.response.model_dump_json().encode() + b"\n").hexdigest()
    result: list[ArchivalCandidate] = []
    for assertion in expected:
        if len(assertion.period.months) != 1:
            raise ArchivalError(
                "this bounded archival tranche requires an explicit single-month assertion"
            )
        links = {
            (href, urljoin(body.response.request_url, href))
            for label, href in parser.links
            if label.casefold() == " ".join(assertion.raw_label.split()).casefold()
        }
        if len(links) > 1:
            raise ArchivalError("publisher issue label has conflicting observed hrefs")
        for href, url in links:
            _ = archive_url(url)
            if not url.lower().endswith(".pdf"):
                raise ArchivalError("observed issue title does not link to an archival PDF")
            result.append(
                ArchivalCandidate(
                    assertion_id=assertion.assertion_id,
                    label=assertion.raw_label,
                    year=assertion.period.year,
                    month=assertion.period.months[0],
                    source_url=body.response.request_url,
                    source_body_sha256=body.response.body_sha256,
                    source_response_sha256=response_sha,
                    source_assertion_sha256=record_sha256(assertion),
                    href=href,
                    pdf_url=url,
                )
            )
    return tuple(result)
