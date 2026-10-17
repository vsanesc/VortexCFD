"""Residual history for the live chart: initial residual of every field per iteration (no Qt)."""

import math
from collections.abc import Iterable

from vortexcfd.foam.logparse import TimeStep

# About this many points per series are drawn; longer series are decimated.
MAX_POINTS = 2000

Point = tuple[float, float]  # (iteration, initial residual)


def decimate(points: list[Point], max_points: int = MAX_POINTS) -> list[Point]:
    """At most ``max_points`` points keeping the shape of a residual curve.

    The series is cut into max_points / 2 consecutive buckets and each bucket keeps its minimum and
    maximum (in iteration order), so spikes and dips survive; the first and last points always stay.
    """
    n = len(points)
    if n <= max_points:
        return list(points)
    buckets = max(1, (max_points - 2) // 2)
    inner = points[1:-1]
    size = len(inner) / buckets
    out = [points[0]]
    for b in range(buckets):
        chunk = inner[int(b * size):int((b + 1) * size)]
        if not chunk:
            continue
        lo = min(chunk, key=lambda p: p[1])
        hi = max(chunk, key=lambda p: p[1])
        out.extend(sorted({lo, hi}, key=lambda p: p[0]))
    out.append(points[-1])
    return out


class ResidualHistory:
    """Series of initial residuals by field name, in the order the fields first appear."""

    def __init__(self) -> None:
        self.series: dict[str, list[Point]] = {}

    def add(self, step: TimeStep) -> None:
        """Add one iteration: the first solve of each field in the step (a field solved several
        times per iteration, e.g. p with non-orthogonal correctors, keeps its first residual)."""
        seen: set[str] = set()
        for name, initial, _final, _iters in step.residuals:
            if name in seen:
                continue
            seen.add(name)
            if math.isfinite(initial) and initial > 0:  # log scale: zero or nan cannot be drawn
                self.series.setdefault(name, []).append((step.time, initial))

    def extend(self, steps: Iterable[TimeStep]) -> None:
        for step in steps:
            self.add(step)

    def clear(self) -> None:
        self.series.clear()

    @property
    def last_iteration(self) -> float | None:
        ends = [s[-1][0] for s in self.series.values() if s]
        return max(ends) if ends else None

    def decimated(self, max_points: int = MAX_POINTS) -> dict[str, list[Point]]:
        return {name: decimate(points, max_points) for name, points in self.series.items()}
