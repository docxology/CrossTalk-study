"""Conservative contents witnesses and corroboration, never a fabricated article census."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from crosstalk.article_records import (
    ArticleError,
    ArticleObservation,
    ArticlePage,
    standalone_folio,
    text_digest,
    witness,
)
from crosstalk.article_validation import validate_evidence

_MARKER = re.compile(r"\b(?:table\s+of\s+contents|contents|in\s+this\s+issue)\b", re.IGNORECASE)
_PREFIX = re.compile(r"^\s*(\d{1,3})\s*[.\t ]\s*([A-Za-z].{0,180})$")
_SUFFIX = re.compile(r"^\s*([A-Za-z].{0,180}?)\s*(?:\.{2,}|\t| {2,})\s*(\d{1,3})\s*$")
_DEPARTMENT = re.compile(
    r"^(?:from the|about the|contents|table of|crosstalk|back ?talk|subscription|"
    + r"letters|call for|calendar|upcoming|contact|departments?|copyright)\b",
    re.IGNORECASE,
)
_DESCRIPTION = re.compile(
    r"^(?:describes|makes the case|provides|details|focuses|examines|explores|highlights|"
    + r"discusses|presents|analy[sz]es|includes|reviews|demonstrates|introduces)\b",
    re.IGNORECASE,
)


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _plausible(title: str) -> bool:
    words = title.split()
    return 1 <= len(words) <= 32 and not re.search(r"https?://|@|www\.", title)


def contents_observations(page: ArticlePage) -> tuple[ArticleObservation, ...]:
    """Parse only explicit title/page-number rows on marker-bearing pages.

    These are observed entries, not verified genres or body boundaries. The marker may
    occur in an annual index or a retrospective. The raw exact witness is retained.
    """
    if not _MARKER.search(page.text):
        return ()
    records: list[ArticleObservation] = []
    offset = 0
    for raw in page.text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        prefix, suffix = _PREFIX.match(line), _SUFFIX.match(line)
        parsed: tuple[str, str] | None = None
        if prefix:
            parsed = (prefix[2].strip(), prefix[1])
        elif suffix:
            parsed = (suffix[1].strip(), suffix[2])
        if parsed and _plausible(parsed[0]):
            title, printed = parsed
            evidence = witness(page, offset, offset + len(line))
            identity = text_digest(
                f"contents-v1\0{page.pdf_sha256}\0{page.page_index}\0"
                + f"{page.layer}\0{offset}\0{line}"
            )
            records.append(
                ArticleObservation(
                    observation_id=identity,
                    issue_id=page.issue_id,
                    title_observed=title,
                    printed_start_observed=printed,
                    kind="contents-entry",
                    witnesses=(evidence,),
                    discovery_flags=("department-or-administrative-label-needs-review",)
                    if _DEPARTMENT.search(title)
                    else (),
                )
            )
        offset += len(raw)
    return (*records, *_aligned_entries(page, tuple(records)))


def _aligned_entries(
    page: ArticlePage,
    existing: tuple[ArticleObservation, ...],
) -> tuple[ArticleObservation, ...]:
    """Retain separately aligned folio/title blocks as provisional entries."""
    records: list[ArticleObservation] = []
    # Some publisher contents put the folio in its own native block. Match only
    # aligned rectangles and retain both the folio and title as exact witnesses.
    for folio in page.blocks:
        printed = folio.text.strip()
        if not re.fullmatch(r"\d{1,3}", printed):
            continue
        adjacent = sorted(
            (
                b
                for b in page.blocks
                if b.bbox[0] > folio.bbox[0] and abs(b.bbox[1] - folio.bbox[1]) <= 12
            ),
            key=lambda b: b.bbox[0],
        )
        if not adjacent:
            continue
        raw_title = _title_prefix(adjacent[0].text)
        title = " ".join(raw_title.split())
        if not _plausible(title) or any(
            _normal(r.title_observed) == _normal(title) and r.printed_start_observed == printed
            for r in existing
        ):
            continue
        start = page.text.find(raw_title)
        number = standalone_folio(page, printed)
        if start < 0 or number is None:
            continue
        records.append(
            ArticleObservation(
                observation_id=text_digest(
                    f"aligned-contents-v1\0{page.pdf_sha256}\0{page.page_index}\0"
                    + f"{page.layer}\0{printed}\0{title}"
                ),
                issue_id=page.issue_id,
                title_observed=title,
                printed_start_observed=printed,
                kind="contents-entry",
                discovery_method="aligned-native-block-folio-title-v1",
                discovery_flags=("department-or-administrative-label-needs-review",)
                if _DEPARTMENT.search(title)
                else (),
                witnesses=(
                    witness(page, start, start + len(raw_title)),
                    number,
                ),
            )
        )
    return tuple(records)


def _title_prefix(text: str) -> str:
    """Observe up to four title lines before an explicit contents-description verb."""
    retained: list[str] = []
    for line in text.splitlines(keepends=True)[:4]:
        if not line.strip() or _DESCRIPTION.search(line.strip()):
            break
        retained.append(line)
    return "".join(retained).rstrip("\r\n")


def corroborate_start(
    observation: ArticleObservation,
    pages: tuple[ArticlePage, ...],
    *,
    threshold: float = 0.92,
    excluded_discovery_pages: tuple[int, ...] = (),
) -> ArticleObservation:
    """Search actual page text; never interpret a printed page number as a PDF index."""
    if not 0.8 <= threshold <= 1:
        raise ArticleError("title corroboration threshold is outside the declared range")
    title = _normal(observation.title_observed)
    found: list[tuple[ArticlePage, int, int, float]] = []
    discovery_page = observation.witnesses[0].page_index
    discovery = tuple(p for p in observation.witnesses if p.page_index == discovery_page)
    # Old body witnesses can legitimately disappear during recomputation. Admit
    # the current frame and retained discovery, then search the body anew.
    _ = validate_evidence(pages, (observation.model_copy(update={"witnesses": discovery}),))
    excluded = {discovery_page, *excluded_discovery_pages}
    if not excluded <= {page.page_index for page in pages}:
        raise ArticleError("excluded contents pages are outside the supplied source frame")
    for page in pages:
        if page.issue_id != observation.issue_id:
            raise ArticleError("start corroboration crossed issue identity")
        if page.page_index in excluded:
            continue
        found.extend(
            (page, start, end, score)
            for start, end, score in _page_matches(page.text, title, threshold)
        )
    if not found:
        return observation.model_copy(
            update={
                "witnesses": discovery,
                "target_page_indices": (),
                "target_layer": None,
                "title_match_score": None,
                "boundary_status": "unresolved",
            }
        )
    best: dict[tuple[int, str], tuple[ArticlePage, int, int, float]] = {}
    for item in found:
        key = (item[0].page_index, item[0].layer)
        if key not in best or item[3] > best[key][3]:
            best[key] = item
    physical = tuple(sorted({key[0] for key in best}))
    layers = {row[0].layer for row in best.values()}
    additions = tuple(witness(p, a, b) for p, a, b, _ in best.values())
    return observation.model_copy(
        update={
            "witnesses": (*discovery, *additions),
            "target_page_indices": physical,
            "target_layer": next(iter(layers)) if len(layers) == 1 else None,
            "title_match_score": max(row[3] for row in best.values()),
            "boundary_status": "start-corroborated"
            if len(physical) == len(layers) == 1
            else "unresolved",
        }
    )


def _page_matches(text: str, title: str, threshold: float) -> tuple[tuple[int, int, float], ...]:
    """Compare short contiguous native sequences, retaining their unmodified offsets."""
    matches: list[tuple[int, int, float]] = []
    offset = 0
    lines = text.splitlines(keepends=True)
    for index, raw in enumerate(lines):
        for count in range(1, min(20, len(lines) - index) + 1):
            sample = "".join(lines[index : index + count]).rstrip("\r\n")
            normal = _normal(sample)
            if len(normal) > len(title) * 1.5 + 10:
                break
            if not normal or min(len(normal), len(title)) / max(len(normal), len(title)) < 0.8:
                continue
            if not set(title.split()[:2]) & set(normal.split()[:3]):
                continue
            score = SequenceMatcher(None, title, normal, autojunk=False).ratio()
            if score >= threshold:
                matches.append((offset, offset + len(sample), score))
        offset += len(raw)
    return tuple(matches)
