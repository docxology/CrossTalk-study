"""Label-invariant partition agreement is exploratory stability, not semantic validation."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Literal

from crosstalk.study_cluster_records import ClusterModel
from crosstalk.study_language_records import Digest, Record, StudyError


class PartitionComparison(Record):
    """ARI on matched pages; shared issue dependence remains outside this statistic."""

    frame_sha256: Digest
    k_a: int
    k_b: int
    status_a: str
    status_b: str
    scope: Literal["all-eligible", "algorithmic-heldout-common"]
    matched_pages: int
    matched_issues: int
    adjusted_rand_index: float
    interpretation: str = (
        "Matched-page partition stability; not semantic or independent-unit validation."
    )
    degenerate_rule: str = "Identical degenerate partitions score1; empty matched scope refuses."


def _pairs(count: int) -> int:
    """Count unordered pairs without constructing a quadratic page-pair array."""
    return count * (count - 1) // 2


def compare_partitions(
    left: ClusterModel,
    right: ClusterModel,
    scope: Literal["all-eligible", "algorithmic-heldout-common"] = "all-eligible",
) -> PartitionComparison:
    """Compare independently bound fits only on matching current physical page identities."""
    left = ClusterModel.model_validate(left.model_dump(mode="python"), strict=True)
    right = ClusterModel.model_validate(right.model_dump(mode="python"), strict=True)
    if left.frame_sha256 != right.frame_sha256:
        raise StudyError("cluster stability comparison requires one exact feature frame")
    a = {row.page_key: row for row in left.assignments}
    b = {row.page_key: row for row in right.assignments}
    if len(a) != len(left.assignments) or len(b) != len(right.assignments):
        raise StudyError("cluster comparison received duplicate assignment identities")
    if set(a) != set(b) or not a:
        raise StudyError("cluster comparison requires complete matching fitted assignment frames")
    keys = tuple(
        sorted(
            key
            for key in a
            if scope == "all-eligible" or (a[key].role == b[key].role == "heldout-issue")
        )
    )
    if not keys:
        raise StudyError("cluster stability scope contains no matched pages")
    if any(
        (a[key].issue_id, a[key].pdf_sha256, a[key].page_index, a[key].source_bindings)
        != (b[key].issue_id, b[key].pdf_sha256, b[key].page_index, b[key].source_bindings)
        for key in keys
    ):
        raise StudyError("cluster matched page source identities disagree")
    table = Counter((a[key].cluster_id, b[key].cluster_id) for key in keys)
    rows = Counter(a[key].cluster_id for key in keys)
    columns = Counter(b[key].cluster_id for key in keys)
    joint = sum(_pairs(value) for value in table.values())
    first, second = (
        sum(_pairs(value) for value in rows.values()),
        sum(_pairs(value) for value in columns.values()),
    )
    possible = _pairs(len(keys))
    expected = Fraction(first * second, possible) if possible else Fraction()
    denominator = Fraction(first + second, 2) - expected
    ari = float((joint - expected) / denominator) if denominator else 1.0
    return PartitionComparison(
        frame_sha256=left.frame_sha256,
        k_a=left.k,
        k_b=right.k,
        status_a=left.status,
        status_b=right.status,
        scope=scope,
        matched_pages=len(keys),
        matched_issues=len({a[key].issue_id for key in keys}),
        adjusted_rand_index=ari,
    )
