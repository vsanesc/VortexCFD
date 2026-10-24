"""Axis ticks for every chart of the app (D-169), Qt-free: "nice" steps by the 1-2-5 rule, minor ticks between them,
labels with thousands separators, and a tick count that follows the room the labels need, so the ticks adapt to the
chart's width and to its zoom and pan.

An iteration axis is an integer axis: its steps are whole iterations (never 1.5).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

MANTISSAS = (1, 2, 5)
# Minor ticks per major step by the step's mantissa: 1 -> 5 (0.2), 2 -> 4 (0.5), 5 -> 5 (1).
MINOR_DIVISIONS = {1: 5, 2: 4, 5: 5}


@dataclass(frozen=True)
class Ticks:
    major: tuple[float, ...]
    minor: tuple[float, ...]  # between the majors (none on a major)
    step: float

    def labels(self) -> list[str]:
        return [label(v, self.step) for v in self.major]


def nice_step(raw: float, integer: bool = False) -> float:
    """The smallest 1, 2 or 5 x 10^n step of at least ``raw``; at least 1 on an integer axis."""
    raw = max(raw, 1e-12)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    for m in (*MANTISSAS, 10):
        step = m * magnitude
        if step >= raw * (1 - 1e-9):
            break
    return max(step, 1.0) if integer else step


def _smaller_step(step: float) -> float:
    """The next smaller nice step (20 -> 10, 10 -> 5, 5 -> 2)."""
    m = _mantissa(step)
    magnitude = step / m
    return {1: 0.5, 2: 1.0, 5: 2.0}[m] * magnitude


def _mantissa(step: float) -> int:
    m = step / 10.0 ** math.floor(math.log10(step) + 1e-9)
    return min(MANTISSAS, key=lambda c: abs(c - m))


def ticks(lo: float, hi: float, target: int = 5, integer: bool = False) -> Ticks:
    """About ``target`` major ticks inside [lo, hi] (both included when they fall on a step) and their minor ticks."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return Ticks((), (), 1.0)
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0:
        span = abs(lo) or 1.0
    step = nice_step(span / max(target, 1), integer)
    while True:  # at least two majors: a smaller nice step when the range holds only one
        eps = 1e-9 * step
        first = math.ceil((lo - eps) / step)
        last = math.floor((hi + eps) / step)
        smaller = _smaller_step(step)
        if last > first or (integer and smaller < 1) or smaller < span * 1e-6:
            break
        step = smaller
    major = tuple(_clean(k * step) for k in range(first, last + 1))
    divisions = MINOR_DIVISIONS[_mantissa(step)]
    minor_step = step / divisions
    if integer and minor_step < 1:
        divisions = int(step) if step >= 2 else 1  # whole iterations only
        minor_step = step / divisions
    minor: list[float] = []
    if divisions > 1:
        k0, k1 = math.ceil((lo - eps) / minor_step), math.floor((hi + eps) / minor_step)
        minor = [_clean(k * minor_step) for k in range(k0, k1 + 1) if k % divisions]
    return Ticks(major, tuple(minor), step)


def _clean(value: float) -> float:
    """Round away the float noise of k * step (0.30000000000000004 -> 0.3)."""
    return float(f"{value:.12g}")


def label(value: float, step: float) -> str:
    """A tick's label: as many decimals as the step needs, thousands separators from 1,000 on, "−" for negatives."""
    decimals = max(0, -math.floor(math.log10(step) + 1e-9)) if step < 1 else 0
    text = f"{value:,.{decimals}f}"
    if text.startswith("-"):
        text = "−" + text[1:]
    return "0" if text in ("−0", "−0.0") else text


def fitted_ticks(lo: float, hi: float, length_px: float, text_width: Callable[[str], float], integer: bool = False,
                 gap_px: float = 12.0, max_target: int = 10) -> Ticks:
    """The ticks of an axis ``length_px`` long: the most (at most ``max_target``) whose labels do not touch, each label
    ``text_width(label)`` wide plus ``gap_px``."""
    best = ticks(lo, hi, 2, integer)
    for target in range(2, max_target + 1):
        candidate = ticks(lo, hi, target, integer)
        if len(candidate.major) < 2:
            continue
        widest = max(text_width(t) for t in candidate.labels())
        spacing = length_px * candidate.step / max(hi - lo, 1e-12)
        if spacing >= widest + gap_px:
            best = candidate
    return best
