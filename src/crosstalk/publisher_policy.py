"""Publisher-only policy content admission and explicit environment failures."""

from __future__ import annotations

import errno
from typing import TYPE_CHECKING, assert_never

from crosstalk.acquisition_policy import RobotsPolicy, parse_robots
from crosstalk.models import AcquisitionError

if TYPE_CHECKING:
    from crosstalk.acquisition_records import PublisherFailureKind
    from crosstalk.models import DownloadReceipt
    from crosstalk.publisher_acquisition_records import PublisherAttemptState


class PublisherPolicyError(AcquisitionError):
    """A failed fresh policy never permits a PDF request."""


class PublisherBudgetError(AcquisitionError):
    """The next permitted request cannot fit the finite publisher acquisition budget."""


def storage_unavailable(error: OSError) -> bool:
    """Known storage failures stop the environment rather than consuming more source attempts."""
    return error.errno in {errno.ENOSPC, errno.EDQUOT, errno.EIO, errno.EROFS}


def classify_publisher_failure(
    state: PublisherAttemptState,
    receipt: DownloadReceipt,
) -> PublisherFailureKind | None:
    """Environment failures remain immutable evidence without consuming a source retry slot."""
    if receipt.status != "failed":
        return None
    match state:
        case "none" | "source-failed" | "local-refusal":
            return "source"
        case (
            "policy-unavailable"
            | "network-unavailable"
            | "storage-unavailable"
            | "budget-exhausted"
        ):
            return "environment"
        case _:
            assert_never(state)


def parse_publisher_policy(body: bytes, content_type: str | None) -> RobotsPolicy:
    """A successful HTML/login response is unavailable policy rather than permission."""
    text = body.decode("utf-8", errors="strict")
    mime = (content_type or "").partition(";")[0].strip().lower()
    meaningful = tuple(
        content for line in text.splitlines() if (content := line.split("#", 1)[0].strip())
    )
    if mime not in {"", "text/plain", "application/octet-stream", "text/x-robots"}:
        raise PublisherPolicyError("publisher robots returned non-robots content")
    if "<" in text or ">" in text:
        raise PublisherPolicyError("publisher robots returned markup")
    if meaningful and not any(
        line.lower().startswith(("user-agent:", "sitemap:")) for line in meaningful
    ):
        raise PublisherPolicyError("publisher robots text lacks recognizable directives")
    return parse_robots(text)
