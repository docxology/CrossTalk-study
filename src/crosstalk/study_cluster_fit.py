"""Bounded deterministic alternate k-medoids; no global optimum or semantic class claim."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from crosstalk.study_language_records import StudyError

type Vector = tuple[float, ...]
type Distances = tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class Fit:
    """Medoid indices refer to the caller's canonical source-identity training order."""

    medoids: tuple[int, ...]
    assigned_medoids: tuple[int, ...]
    status: Literal["converged", "iteration-limit", "cycle-detected"]
    iterations: int
    objective_history: tuple[float, ...]


def _check_matrix(matrix: Distances) -> None:
    """Reject malformed distance input before interpreting its separation structure."""
    count = len(matrix)
    if count > 1024 or any(len(row) != count for row in matrix):
        raise StudyError("cluster distance matrix requires a bounded square frame")
    for left, row in enumerate(matrix):
        if row[left] != 0:
            raise StudyError("cluster distance matrix diagonal must be zero")
        if any(not math.isfinite(value) or not 0 <= value <= 1e18 for value in row):
            raise StudyError("cluster distance matrix requires finite nonnegative distances")
        if any(value != matrix[right][left] for right, value in enumerate(row)):
            raise StudyError("cluster distance matrix must be symmetric")


def distance(left: Vector, right: Vector, weights: tuple[float, ...]) -> float:
    """Weighted Euclidean distance after declared transforms and training-only scaling."""
    if len(left) != len(right) or len(left) != len(weights) or not weights:
        raise StudyError("cluster distance dimensions disagree")
    if any(not math.isfinite(value) or abs(value) > 1e18 for value in (*left, *right)) or any(
        not math.isfinite(weight) or not 0 < weight <= 1000 for weight in weights
    ):
        raise StudyError(
            "cluster distance requires finite bounded coordinates and positive weights"
        )
    result = math.sqrt(
        math.fsum(weight * (a - b) ** 2 for a, b, weight in zip(left, right, weights, strict=True))
        / math.fsum(weights)
    )
    if not math.isfinite(result):
        raise StudyError("cluster distance exceeds finite arithmetic")
    return result


def distance_matrix(vectors: tuple[Vector, ...], weights: tuple[float, ...]) -> Distances:
    """Caller capacity admission precedes this exact symmetric triangular computation."""
    if len(vectors) > 1024:
        raise StudyError("cluster distance matrix exceeds its absolute capacity")
    for point in vectors:
        _ = distance(point, point, weights)
    matrix = [[0.0] * len(vectors) for _ in vectors]
    for left in range(len(vectors)):
        for right in range(left + 1, len(vectors)):
            value = distance(vectors[left], vectors[right], weights)
            matrix[left][right] = matrix[right][left] = value
    return tuple(tuple(row) for row in matrix)


def assign(matrix: Distances, medoids: tuple[int, ...]) -> tuple[int, ...]:
    """Source-order tie breaking is explicit; labels do not measure confidence."""
    return tuple(min(medoids, key=lambda medoid: (row[medoid], medoid)) for row in matrix)


def objective(matrix: Distances, assignments: tuple[int, ...], weights: tuple[float, ...]) -> float:
    """Each fit issue has one total vote through reciprocal selected-page weights."""
    return math.fsum(
        weights[index] * matrix[index][medoid] for index, medoid in enumerate(assignments)
    ) / math.fsum(weights)


def fit(matrix: Distances, weights: tuple[float, ...], k: int, maximum_iterations: int) -> Fit:
    """Farthest-first initialization then alternate assignment/within-group medoid updates."""
    _check_matrix(matrix)
    if (
        not matrix
        or len(weights) != len(matrix)
        or not 1 <= k <= len(matrix)
        or not 1 <= maximum_iterations <= 100
        or any(not math.isfinite(value) or not 0 < value <= 1 for value in weights)
    ):
        raise StudyError("cluster fitting received an unsupported training frame")
    initial = [0]
    while len(initial) < k:
        candidates = tuple(index for index in range(len(matrix)) if index not in initial)
        chosen = min(
            candidates,
            key=lambda index: (
                -min(matrix[index][medoid] for medoid in initial),
                index,
            ),
        )
        if min(matrix[chosen][medoid] for medoid in initial) == 0:
            raise StudyError("cluster k exceeds distinct training vectors")
        initial.append(chosen)
    medoids = tuple(sorted(initial))
    history: list[float] = []
    seen = {medoids}
    status: Literal["converged", "iteration-limit", "cycle-detected"] = "iteration-limit"
    iterations = 0
    for iteration in range(1, maximum_iterations + 1):
        iterations = iteration
        assignments = assign(matrix, medoids)
        history.append(objective(matrix, assignments, weights))
        updated: list[int] = []
        for medoid in medoids:
            members = tuple(index for index, group in enumerate(assignments) if group == medoid)
            if not members:
                raise StudyError("cluster medoid has no assigned training observations")
            updated.append(
                min(
                    members,
                    key=lambda candidate: (
                        math.fsum(weights[index] * matrix[candidate][index] for index in members),
                        candidate,
                    ),
                )
            )
        after = tuple(sorted(updated))
        if after == medoids:
            status = "converged"
            break
        medoids = after
        if medoids in seen:
            status = "cycle-detected"
            break
        seen.add(medoids)
    assignments = assign(matrix, medoids)
    final = objective(matrix, assignments, weights)
    if not history or final != history[-1]:
        history.append(final)
    return Fit(medoids, assignments, status, iterations, tuple(history))


def silhouettes(matrix: Distances, assignments: tuple[int, ...]) -> tuple[float, ...] | None:
    """Classical page silhouette; singleton and zero maximum distance yield zero."""
    _check_matrix(matrix)
    if len(assignments) != len(matrix) or any(group < 0 for group in assignments):
        raise StudyError("silhouette assignments disagree with their complete matrix frame")
    groups = tuple(sorted(set(assignments)))
    if len(groups) < 2:
        return None
    values: list[float] = []
    for index, own in enumerate(assignments):
        others = tuple(j for j, group in enumerate(assignments) if group == own and j != index)
        if not others:
            values.append(0.0)
            continue
        within = math.fsum(matrix[index][j] for j in others) / len(others)
        between = min(
            math.fsum(matrix[index][j] for j, group in enumerate(assignments) if group == candidate)
            / sum(group == candidate for group in assignments)
            for candidate in groups
            if candidate != own
        )
        maximum = max(within, between)
        values.append((between - within) / maximum if maximum else 0.0)
    return tuple(values)
