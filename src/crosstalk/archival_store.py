"""Content-addressed archival quarantine and append-only attempts, separate from NPS issues."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from itertools import islice
from typing import TYPE_CHECKING, assert_never
from urllib.parse import urljoin
from uuid import uuid4

from crosstalk.acquisition_lock import project_lock
from crosstalk.archival_cdn import effective_archive_url
from crosstalk.archival_chain import effective_chain_url
from crosstalk.archival_links import IssueAnchors
from crosstalk.archival_pdf import inspect_archival_pdf
from crosstalk.archival_publication import complete_prepared, stage_payload
from crosstalk.archival_records import (
    ArchivalAttempt,
    ArchivalCandidate,
    ArchivalError,
    ArchivalResponse,
    PreparedPayload,
    candidate_key,
)
from crosstalk.archival_redirect import admit_redirect
from crosstalk.case_files import read_bytes
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import safe_directory

if TYPE_CHECKING:
    from pathlib import Path

    from crosstalk.archival_http import ArchivalBody, ArchivalHttp

__all__ = ["candidate_key", "download_archival_candidate", "read_attempt_paths", "save_response"]


def save_response(root: Path, body: ArchivalBody) -> str:
    """Retain actual bytes before the response receipt; preserve unequal occupied originals."""
    if (
        hashlib.sha256(body.raw).hexdigest() != body.response.body_sha256
        or len(body.raw) != body.response.byte_count
    ):
        raise ArchivalError("actual response bytes disagree with the independent capture")
    _ = publish_metadata(
        safe_directory(root, "output/data/archival/bodies"),
        f"{body.response.body_sha256}.bin",
        body.raw,
    )
    raw = body.response.model_dump_json().encode() + b"\n"
    digest = hashlib.sha256(raw).hexdigest()
    _ = publish_metadata(
        safe_directory(root, "output/data/archival/responses"), f"{digest}.json", raw
    )
    return digest


def _admit_link(root: Path, candidate: ArchivalCandidate) -> str:
    """Reproduce the retained HTML href relation before any request or resume."""
    prefix = root / "output/data/archival"
    response_raw = read_bytes(
        prefix / "responses" / f"{candidate.source_response_sha256}.json", 32_000
    )
    if hashlib.sha256(response_raw).hexdigest() != candidate.source_response_sha256:
        raise ArchivalError("retained source response receipt changed")
    response = ArchivalResponse.model_validate_json(response_raw)
    raw = read_bytes(prefix / "bodies" / f"{candidate.source_body_sha256}.bin", 3_000_000)
    if (
        hashlib.sha256(raw).hexdigest() != candidate.source_body_sha256
        or response.request_url != candidate.source_url
        or response.body_sha256 != candidate.source_body_sha256
        or response.status_code != 200
        or not response.complete
    ):
        raise ArchivalError("archival candidate source capture changed or is not complete HTTP200")
    parser = IssueAnchors()
    parser.feed(raw.decode("utf-8-sig"))
    if (" ".join(candidate.label.split()), candidate.href) not in parser.links:
        raise ArchivalError("candidate does not reproduce its actual retained publisher anchor")
    admit_redirect(root, candidate, urljoin(candidate.source_url, candidate.href))
    return effective_chain_url(root, candidate, effective_archive_url(root, candidate))


def _append(root: Path, attempt: ArchivalAttempt) -> None:
    _ = publish_metadata(
        safe_directory(root, f"output/data/archival/attempts/{attempt.candidate_key}"),
        f"{attempt.attempt_id}-{attempt.stage}.json",
        attempt.model_dump_json().encode() + b"\n",
    )


def read_attempt_paths(directory: Path, *, legacy: bool = False) -> tuple[Path, ...]:
    """Unavailable scans refuse; valid peer namespaces remain independently isolated."""
    if any(part.is_symlink() for part in (*directory.parents, directory)):
        raise ArchivalError("archival attempt directory contains an alias")
    with os.scandir(directory) as entries:
        observed = tuple(islice(entries, 20_001))
    if len(observed) > 20_000:
        raise ArchivalError("archival attempt directory exceeds its finite entry bound")
    paths: list[Path] = []
    for entry in observed:
        if (
            legacy
            and entry.is_dir(follow_symlinks=False)
            and re.fullmatch(r"[0-9a-f]{64}", entry.name)
        ):
            continue
        path = directory / entry.name
        if path.suffix != ".json":
            raise ArchivalError("unknown archival attempt entry is preserved")
        paths.append(path)
    return tuple(paths)


def _prior(root: Path, candidate: ArchivalCandidate) -> tuple[ArchivalAttempt, ...]:
    """New ledgers isolate candidates; preserved legacy flat receipts remain readable."""
    directory = safe_directory(root, "output/data/archival/attempts")
    selected = safe_directory(root, f"output/data/archival/attempts/{candidate_key(candidate)}")
    paths = read_attempt_paths(directory, legacy=True) + read_attempt_paths(selected)
    if len(paths) > 10000:
        raise ArchivalError("archival attempt ledger exceeds its finite row bound")
    rows: list[ArchivalAttempt] = []
    for path in paths:
        row = ArchivalAttempt.model_validate_json(read_bytes(path, 32_000))
        if path.name != f"{row.attempt_id}-{row.stage}.json":
            raise ArchivalError("archival attempt filename disagrees with its immutable identity")
        if path.parent == selected and row.candidate_key != candidate_key(candidate):
            raise ArchivalError("candidate-scoped archival receipt binds another source")
        if row.candidate_key == candidate_key(candidate):
            rows.append(row)
    return tuple(sorted(rows, key=lambda row: (row.observed_at, row.attempt_id), reverse=True))


def _recover_owned(root: Path, row: ArchivalAttempt) -> bool:
    """A current prepared record and original source relation authorize owned-link recovery."""
    if row.publication is None:
        return True
    path = root / (
        f"output/data/archival/attempts/{row.candidate_key}/" + f"{row.attempt_id}-prepared.json"
    )
    prepared = ArchivalAttempt.model_validate_json(read_bytes(path, 32_000))
    if prepared.publication != row.publication:
        raise ArchivalError("prepared and published payload custody disagree")
    _ = _admit_link(root, prepared.candidate)
    return complete_prepared(root, prepared)


def _resume(root: Path, candidate: ArchivalCandidate) -> ArchivalAttempt | None:
    """Recover only digest-proven prepared/published bytes; preserve all unknown originals."""
    for row in _prior(root, candidate):
        match row.stage:
            case "failed":
                continue
            case "prepared" | "published" | "reused":
                if row.pdf_sha256 is None or row.inspection is None:
                    raise ArchivalError("prepared archival provenance lacks an expected PDF digest")
                _ = _admit_link(root, row.candidate)
                if not _recover_owned(root, row):
                    continue
                pdf = root / "output/data/archival/pdfs" / f"{row.pdf_sha256}.pdf"
                if not pdf.exists():
                    continue
                raw = read_bytes(pdf, 50_000_000)
                if hashlib.sha256(raw).hexdigest() != row.pdf_sha256:
                    raise ArchivalError(
                        "previous archival PDF bytes changed; preserved for inspection"
                    )
                inspection = inspect_archival_pdf(raw, candidate)
                result = ArchivalAttempt(
                    attempt_id=uuid4().hex,
                    candidate_key=candidate_key(candidate),
                    candidate=candidate,
                    observed_at=datetime.now(UTC),
                    stage="reused",
                    pdf_sha256=row.pdf_sha256,
                    inspection=inspection,
                )
                _append(root, result)
                return result
            case _:
                assert_never(row.stage)
    return None


def _require_publication(root: Path, prepared: ArchivalAttempt) -> None:
    """A vanished prepared payload is an explicit failed attempt, never new content."""
    if not complete_prepared(root, prepared):
        raise ArchivalError("newly prepared archival payload disappeared")


def download_archival_candidate(
    root: Path, candidate: ArchivalCandidate, reader: ArchivalHttp
) -> ArchivalAttempt:
    """Acquire one observed locator idempotently, preserving policy/response/failure evidence."""
    with project_lock(root):
        actual_url = _admit_link(root, candidate)
        resumed = _resume(root, candidate)
        if resumed is not None:
            return resumed
        identifier = uuid4().hex
        try:
            body = reader.fetch(actual_url)
            for observed in reader.responses:
                _ = save_response(root, observed)
            inspection = inspect_archival_pdf(body.raw, candidate)
            publication = PreparedPayload(
                attempt_id=identifier,
                candidate_key=candidate_key(candidate),
                pdf_sha256=inspection.pdf_sha256,
                byte_count=len(body.raw),
                partial_path=(
                    f"output/data/archival/partials/{identifier}-{inspection.pdf_sha256}.part"
                ),
                target_path=f"output/data/archival/pdfs/{inspection.pdf_sha256}.pdf",
            )
            stage_payload(root, publication, body.raw)
            prepared = ArchivalAttempt(
                attempt_id=identifier,
                candidate_key=candidate_key(candidate),
                candidate=candidate,
                observed_at=datetime.now(UTC),
                stage="prepared",
                pdf_sha256=inspection.pdf_sha256,
                inspection=inspection,
                publication=publication,
            )
            _append(root, prepared)
            _require_publication(root, prepared)
            result = prepared.model_copy(update={"stage": "published"})
        except ArchivalError as error:
            for observed in reader.responses:
                _ = save_response(root, observed)
            result = ArchivalAttempt(
                attempt_id=identifier,
                candidate_key=candidate_key(candidate),
                candidate=candidate,
                observed_at=datetime.now(UTC),
                stage="failed",
                error=str(error),
            )
        _append(root, result)
        return result
