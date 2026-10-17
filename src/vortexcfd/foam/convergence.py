"""Stopping criteria as OpenFOAM runTimeControl conditions, their live evaluation, and the
oscillation check (no Qt). [NUMERICS-REVIEW] (D-058, D-059)

The stop itself is always OpenFOAM's: the runTimeControl function object
(src/functionObjects/utilities/runTimeControl in v2606) ends the run with ``writeAndEnd`` when its
conditions are met, so the solver writes the last iteration and exits normally. This module only
mirrors the same formulas in Python to show each criterion's current value while the run goes on.

v2606 conditions used (keywords read from the sources):

- ``equationInitialResidual`` (fields, value, mode minimum, timeStart): satisfied when the initial
  residual of the field's first solve in the iteration (a vector field: its largest component)
  is below ``value``; never before time index 3 nor before ``timeStart``.
- ``average`` (functionObject, fields, tolerance, window, windowType exact, nIterStartUp): the mean
  of the last ``window`` values of a function-object result (the current one included) and
  delta = |mean - current|; satisfied when delta <= tolerance (absolute) and the condition has
  been applied more than nIterStartUp + 2 times. Measured on a real run: nIterStartUp N first
  allows a stop at iteration N + 3 (the condition is first applied at iteration 1).
- grouping (``groupID``): the run stops when every condition of one group is met in the same
  iteration; "all" puts every criterion in group 1, "any" gives each criterion its own group.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vortexcfd.core.model import AsymptoticCriterion, ResidualCriterion, StoppingCriteria

FUNCTION_NAME = "runTimeControl1"
# Monitored quantity -> (function object, result name) read by an ``average`` condition.
QUANTITY_SOURCES = {"Cd": ("forceCoeffs1", "Cd"), "Cl": ("forceCoeffs1", "Cl"),
                    "CmPitch": ("forceCoeffs1", "CmPitch")}
QUANTITY_LABELS = {"Cd": "Cd", "Cl": "Cl", "CmPitch": "Cm (pitch)"}
# The equationInitialResidual condition never checks the first two time indices.
FIRST_RESIDUAL_CHECK = 3
# ``average``: nIterStartUp N first allows a stop at iteration N + START_UP_OFFSET (real run, D-058).
START_UP_OFFSET = 3

Series = Sequence[tuple[float, float]]  # (iteration, value)


def condition_name(index: int, criterion) -> str:
    """The condition's name in the runTimeControl dictionary (and in the solver log)."""
    target = criterion.field if isinstance(criterion, ResidualCriterion) else criterion.quantity
    return f"c{index + 1}_{criterion.kind}_{target}"


def describe(criterion) -> str:
    """One line stating the criterion exactly."""
    if isinstance(criterion, ResidualCriterion):
        return f"{criterion.field} initial residual < {criterion.threshold:.3g}"
    label = QUANTITY_LABELS.get(criterion.quantity, criterion.quantity)
    return f"{label}: |value - mean of last {criterion.window}| <= {criterion.tolerance:.3g}"


def short_label(criterion) -> str:
    """A few words naming the criterion (tables; ``describe`` states it exactly)."""
    if isinstance(criterion, ResidualCriterion):
        return f"{criterion.field} residual"
    return f"{QUANTITY_LABELS.get(criterion.quantity, criterion.quantity)} asymptotic"


def n_iter_start_up(criterion: AsymptoticCriterion, min_iterations: int) -> int:
    """nIterStartUp so that the window is full and min_iterations reached before any stop."""
    return max(max(min_iterations, criterion.window) - START_UP_OFFSET, 0)


def earliest_iteration(criterion, min_iterations: int) -> int:
    """The first iteration at which OpenFOAM may consider the criterion met."""
    if isinstance(criterion, ResidualCriterion):
        return max(min_iterations, FIRST_RESIDUAL_CHECK)
    return n_iter_start_up(criterion, min_iterations) + START_UP_OFFSET


def run_time_control(stopping: StoppingCriteria) -> dict | None:
    """The runTimeControl function object for the criteria (None without criteria)."""
    if not stopping.criteria:
        return None
    conditions: dict[str, dict] = {}
    for i, c in enumerate(stopping.criteria):
        group = 1 if stopping.combine == "all" else i + 1
        if isinstance(c, ResidualCriterion):
            entry = {"type": "equationInitialResidual", "fields": [c.field], "value": c.threshold,
                     "mode": "minimum", "timeStart": stopping.min_iterations}
        else:
            function, result = QUANTITY_SOURCES[c.quantity]
            entry = {"type": "average", "functionObject": function, "fields": [result],
                     "tolerance": c.tolerance, "window": c.window, "windowType": "exact",
                     "nIterStartUp": n_iter_start_up(c, stopping.min_iterations)}
        entry["groupID"] = group
        conditions[condition_name(i, c)] = entry
    return {"type": "runTimeControl", "libs": ["utilityFunctionObjects"], "conditions": conditions,
            "satisfiedAction": "end"}


def criteria_outcome(stopping: StoppingCriteria, met: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(descriptions of all criteria, descriptions of those named in ``met``), for the run record."""
    names = {condition_name(i, c): describe(c) for i, c in enumerate(stopping.criteria)}
    return tuple(names.values()), tuple(names.get(n, n) for n in met)


def unique_by_iteration(series: Series) -> list[tuple[float, float]]:
    """One value per iteration, the last one written (writeAndEnd repeats the final row)."""
    out: list[tuple[float, float]] = []
    for t, v in series:
        if out and out[-1][0] == t:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    return out


def asymptotic_delta(series: Series, window: int) -> float | None:
    """|x_n - mean of the last ``window`` values| (x_n included), as the ``average`` condition
    computes it; None until ``window`` values exist."""
    values = [v for _, v in unique_by_iteration(series)]
    if len(values) < window:
        return None
    last = values[-window:]
    return abs(values[-1] - sum(last) / window)


@dataclass(frozen=True)
class CriterionStatus:
    """One criterion's live state: value compared with threshold, and whether it is met."""

    description: str
    value: float | None  # None: not computed yet
    threshold: float
    satisfied: bool
    note: str = ""  # e.g. "from iteration 50"
    label: str = ""  # short_label


def residual_value(residuals: dict[str, Series], field: str) -> tuple[float, float] | None:
    """(iteration, residual) at the last iteration; U is the largest of its components."""
    names = ("Ux", "Uy", "Uz") if field == "U" else (field,)
    last: dict[str, tuple[float, float]] = {n: residuals[n][-1] for n in names if residuals.get(n)}
    if not last:
        return None
    it = max(t for t, _ in last.values())
    values = [v for t, v in last.values() if t == it]
    return it, max(values)


def evaluate(stopping: StoppingCriteria, residuals: dict[str, Series],
             quantity: Callable[[str], Series]) -> list[CriterionStatus]:
    """The state of every criterion from the residual history and the report series."""
    out = []
    for c in stopping.criteria:
        earliest = earliest_iteration(c, stopping.min_iterations)
        if isinstance(c, ResidualCriterion):
            got = residual_value(residuals, c.field)
            value, it = (got[1], got[0]) if got else (None, 0)
            met = value is not None and value < c.threshold
            threshold = c.threshold
        else:
            series = unique_by_iteration(quantity(c.quantity))
            value = asymptotic_delta(series, c.window)
            it = series[-1][0] if series else 0
            met = value is not None and value <= c.tolerance
            threshold = c.tolerance
        early = it < earliest
        note = f"from iteration {earliest}" if early and earliest > 1 else ""
        out.append(CriterionStatus(describe(c), value, threshold, met and not early, note, short_label(c)))
    return out


@dataclass(frozen=True)
class Oscillation:
    """A monitored quantity that oscillates over the window without drifting."""

    quantity: str
    amplitude: float  # (max - min) / |mean| over the window
    mean: float

    def message(self) -> str:
        label = QUANTITY_LABELS.get(self.quantity, self.quantity)
        return (f"{label} oscillates by {100 * self.amplitude:.2g}% - the flow may be unsteady; "
                "a steady solution may not exist")


# The relative amplitude is not evaluated when the mean is this close to zero (it is undefined).
MEAN_FLOOR = 1e-3
# Not drifting: the least-squares line over the window changes by less than this fraction of
# max - min.
DRIFT_FRACTION = 0.5


def linear_change(values: Sequence[float]) -> float:
    """Change of the least-squares straight line across the window (slope times n - 1)."""
    n = len(values)
    xm = (n - 1) / 2
    ym = sum(values) / n
    sxx = sum((i - xm) ** 2 for i in range(n))
    sxy = sum((i - xm) * (v - ym) for i, v in enumerate(values))
    return sxy / sxx * (n - 1)


def oscillation(quantity: str, series: Series, window: int, threshold: float) -> Oscillation | None:
    """The oscillation warning of one quantity, or None.

    Over the last ``window`` values: amplitude a = (max - min) / |mean|. It is reported when
    a > threshold and the mean is not drifting, i.e. the least-squares line through the window
    changes by less than DRIFT_FRACTION * (max - min) (a monotonic ramp changes by about its whole
    range; an oscillation over at least two periods by much less). Not evaluated with fewer than
    ``window`` values or a mean below MEAN_FLOOR in magnitude.
    """
    values = [v for _, v in unique_by_iteration(series)]
    if len(values) < window or window < 2:
        return None
    last = values[-window:]
    mean = sum(last) / window
    spread = max(last) - min(last)
    if not all(math.isfinite(v) for v in last) or abs(mean) < MEAN_FLOOR or spread <= 0:
        return None
    amplitude = spread / abs(mean)
    if amplitude <= threshold or abs(linear_change(last)) >= DRIFT_FRACTION * spread:
        return None
    return Oscillation(quantity, amplitude, mean)
