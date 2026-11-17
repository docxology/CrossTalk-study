"""Finite publisher request, pacing and failure bounds are checked before dataset or HTTP work."""

import math

from crosstalk.models import AcquisitionError


def validate_publisher_bounds(
    limit: int | None,
    delay: float,
    seconds: float,
    failures: int,
    maximum_source_failures: int = 3,
) -> None:
    """Reject unbounded configuration before a marker, inventory, attempt or request is written."""
    if not math.isfinite(delay) or delay < 10 or not 0 < seconds <= 240:
        raise AcquisitionError(
            "publisher pacing/time bounds must be finite and at most 240 seconds"
        )
    if limit is not None and not 1 <= limit <= 2000:
        raise AcquisitionError("publisher new-work limit must be between 1 and 2000")
    if not 1 <= failures <= 10:
        raise AcquisitionError("publisher consecutive failure limit must be between 1 and 10")
    if not 1 <= maximum_source_failures <= 10:
        raise AcquisitionError("publisher source failure cap must be between 1 and 10")
