"""Stopping criteria: OpenFOAM runTimeControl conditions or the app's own evaluation, and the
oscillation check (no Qt). [NUMERICS-REVIEW] (D-058, D-059)

Two ways to stop (D-058):

- only residual criteria: OpenFOAM's own runTimeControl function object
  (src/functionObjects/utilities/runTimeControl in v2606) ends the run with ``writeAndEnd`` when
  its ``equationInitialResidual`` conditions are met (validated by the flat plate);
- at least one asymptotic criterion: OpenFOAM has no range-based condition, so no runTimeControl
  is written and the app evaluates ALL criteria after every iteration from the live data
  (``evaluate``: residuals from the log, quantities from the postProcessing files), combines them
  with "all" / "any" (``criteria_met``) and stops the solver with the clean stop (SIGUSR1 and
  stopAtWriteNowSignal, D-010; foam/solver_run.py).

v2606 condition used natively (keywords read from the sources):

- ``equationInitialResidual`` (fields, value, mode minimum, timeStart): satisfied when the initial
  residual of the field's first solve in the iteration (a vector field: its largest component)
  is below ``value``; never before time index 3 nor before ``timeStart``.
- grouping (``groupID``): the run stops when every condition of one group is met in the same
  iteration; "all" puts every criterion in group 1, "any" gives each criterion its own group.

Asymptotic criterion (app-side): over the last W iterations (one value per iteration),
r = (max - min) / max(|mean|, floor) <= tolerance; for a vector (a probe's U) max - min is the
length of the vector of per-component ranges and |mean| the length of the mean vector. Evaluated
only once W values exist and from the minimum iterations on.

Mean-stable criterion (app-side, D-118): over the last two windows of W iterations,
d = |mean(last W) - mean(previous W)| / max(|mean(last W)|, floor) <= tolerance. Evaluated only once
2 W values exist (scalar quantities; a probe's U uses the length of the difference of the mean
vectors over the length of the last mean). For a steady run that oscillates about a stationary mean.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vortexcfd.core.model import AsymptoticCriterion, MeanStableCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.core.reports import default_floor, report_label

FUNCTION_NAME = "runTimeControl1"


def force_coeffs_name(patch: str | None) -> str:
    """forceCoeffs1 for all walls, forceCoeffs_<patch> for one part."""
    return "forceCoeffs1" if patch is None else f"forceCoeffs_{patch}"


def probe_function_name(name: str) -> str:
    return f"probe_{name}"


def quantity_label(quantity: str) -> str:
    return report_label(quantity)
# The equationInitialResidual condition never checks the first two time indices.
FIRST_RESIDUAL_CHECK = 3

Series = Sequence[tuple[float, float]]  # (iteration, value)


def condition_name(index: int, criterion) -> str:
    """The criterion's name: the runTimeControl condition name (and in the solver log), also used
    for app-side criteria in the run record."""
    target = criterion.field if isinstance(criterion, ResidualCriterion) else criterion.quantity
    return f"c{index + 1}_{criterion.kind}_{target}"


def describe(criterion) -> str:
    """One line stating the criterion exactly."""
    if isinstance(criterion, ResidualCriterion):
        return f"{criterion.field} initial residual < {criterion.threshold:.3g}"
    label = quantity_label(criterion.quantity)
    if isinstance(criterion, MeanStableCriterion):
        return (f"{label}: |mean of the last {criterion.window} - mean of the {criterion.window} before| / "
                f"max(|mean|, {criterion.effective_floor:.3g}) <= {criterion.tolerance:.3g}")
    return (f"{label}: (max - min) / max(|mean|, {criterion.effective_floor:.3g}) over the last "
            f"{criterion.window} <= {criterion.tolerance:.3g}")


def short_label(criterion) -> str:
    """A few words naming the criterion (tables, the run state; ``describe`` states it exactly)."""
    if isinstance(criterion, ResidualCriterion):
        return f"{criterion.field} residual"
    if isinstance(criterion, MeanStableCriterion):
        return f"{quantity_label(criterion.quantity)} mean stable"
    return f"{quantity_label(criterion.quantity)} asymptotic"


def is_native(stopping: StoppingCriteria) -> bool:
    """True when OpenFOAM's runTimeControl stops the run (only residual criteria); False when the
    app evaluates the criteria (at least one asymptotic criterion) or there are none."""
    return bool(stopping.criteria) and all(isinstance(c, ResidualCriterion) for c in stopping.criteria)


def app_side(stopping: StoppingCriteria | None) -> bool:
    """True when the app must evaluate the criteria and stop the solver itself."""
    return stopping is not None and bool(stopping.criteria) and not is_native(stopping)


def earliest_iteration(criterion, min_iterations: int) -> int:
    """The first iteration at which the criterion may be considered met."""
    if isinstance(criterion, ResidualCriterion):
        return max(min_iterations, FIRST_RESIDUAL_CHECK)
    if isinstance(criterion, MeanStableCriterion):
        return max(min_iterations, 2 * criterion.window)
    return max(min_iterations, criterion.window)


def run_time_control(stopping: StoppingCriteria) -> dict | None:
    """The runTimeControl function object for residual-only criteria (None without criteria or
    when an asymptotic criterion makes the app evaluate them all)."""
    if not is_native(stopping):
        return None
    conditions: dict[str, dict] = {}
    for i, c in enumerate(stopping.criteria):
        group = 1 if stopping.combine == "all" else i + 1
        conditions[condition_name(i, c)] = {
            "type": "equationInitialResidual", "fields": [c.field], "value": c.threshold,
            "mode": "minimum", "timeStart": stopping.min_iterations, "groupID": group}
    return {"type": "runTimeControl", "libs": ["utilityFunctionObjects"], "conditions": conditions,
            "satisfiedAction": "end"}


def criteria_outcome(stopping: StoppingCriteria, met: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(descriptions of all criteria, descriptions of those named in ``met``), for the run record."""
    names = {condition_name(i, c): describe(c) for i, c in enumerate(stopping.criteria)}
    return tuple(names.values()), tuple(names.get(n, n) for n in met)


def met_labels(stopping: StoppingCriteria, met: Sequence[str]) -> tuple[str, ...]:
    """The short labels of the criteria named in ``met`` (the run state "Criteria met: ...")."""
    names = {condition_name(i, c): short_label(c) for i, c in enumerate(stopping.criteria)}
    return tuple(names.get(n, n) for n in met)


def unique_by_iteration(series: Series) -> list[tuple[float, float]]:
    """One value per iteration, the last one written (writeAndEnd repeats the final row)."""
    out: list[tuple[float, float]] = []
    for t, v in series:
        if out and out[-1][0] == t:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    return out


def relative_range(values: Sequence, floor: float) -> float:
    """(max - min) / max(|mean|, floor) of the values (for vectors: the length of the vector of
    per-component ranges over the length of the mean vector)."""
    n = len(values)
    if isinstance(values[0], tuple):
        comps = range(len(values[0]))
        spread = math.sqrt(sum((max(v[i] for v in values) - min(v[i] for v in values)) ** 2 for i in comps))
        mean = math.sqrt(sum((sum(v[i] for v in values) / n) ** 2 for i in comps))
    else:
        spread = max(values) - min(values)
        mean = abs(sum(values) / n)
    return spread / max(mean, floor)


def asymptotic_range(series, window: int, floor: float) -> float | None:
    """The asymptotic criterion's value over the last ``window`` iterations (relative_range);
    None until ``window`` values exist."""
    values = [v for _, v in unique_by_iteration(series)]
    if len(values) < window:
        return None
    return relative_range(values[-window:], floor)


def _mean(values: Sequence):
    n = len(values)
    if isinstance(values[0], tuple):
        return tuple(sum(v[i] for v in values) / n for i in range(len(values[0])))
    return sum(values) / n


def _norm(value) -> float:
    return math.sqrt(sum(c * c for c in value)) if isinstance(value, tuple) else abs(value)


def mean_change(values: Sequence, window: int, floor: float) -> float | None:
    """The mean-stable criterion's value: |mean(last window) - mean(window before)| /
    max(|mean(last window)|, floor); None until 2 ``window`` values exist."""
    if len(values) < 2 * window:
        return None
    last, previous = _mean(values[-window:]), _mean(values[-2 * window:-window])
    if isinstance(last, tuple):
        diff = tuple(a - b for a, b in zip(last, previous))
    else:
        diff = last - previous
    return _norm(diff) / max(_norm(last), floor)


def criterion_value(series, criterion: AsymptoticCriterion) -> float | None:
    """The value an asymptotic or mean-stable criterion compares with its tolerance at the last
    iteration of ``series`` (None: not enough values yet)."""
    values = [v for _, v in unique_by_iteration(series)]
    if isinstance(criterion, MeanStableCriterion):
        return mean_change(values, criterion.window, criterion.effective_floor)
    if len(values) < criterion.window:
        return None
    return relative_range(values[-criterion.window:], criterion.effective_floor)


def first_met_iteration(series, criterion: AsymptoticCriterion, min_iterations: int = 0) -> int | None:
    """The first iteration of ``series`` at which ``criterion`` (asymptotic or mean-stable) alone is
    met (None: never)."""
    rows = unique_by_iteration(series)
    values = [v for _, v in rows]
    w, floor = criterion.window, criterion.effective_floor
    stable = isinstance(criterion, MeanStableCriterion)
    for i in range(2 * w if stable else w, len(rows) + 1):
        it = rows[i - 1][0]
        if it < min_iterations:
            continue
        value = mean_change(values[:i], w, floor) if stable else relative_range(values[i - w:i], floor)
        if value <= criterion.tolerance:
            return int(it)
    return None


@dataclass(frozen=True)
class WindowStats:
    """A quantity over its last ``n`` iterations: mean, max - min, and the amplitude
    (max - min) / max(|mean|, floor) (the oscillation check's normalisation, D-059)."""

    mean: float
    spread: float
    amplitude: float | None  # None: no floor and |mean| < MEAN_FLOOR
    n: int

    def text(self) -> str:
        """e.g. "mean 0.3409 \u00b1 3.2% (500 it.)": the half range as a share of the scale."""
        half = "" if self.amplitude is None else f" \u00b1 {50 * self.amplitude:.2g}%"
        return f"mean {self.mean:.4g}{half} ({self.n} it.)"


def window_stats(series, window: int, floor: float | None = None, quantity: str | None = None) -> WindowStats | None:
    """The windowed mean and oscillation of a scalar series over its last ``window`` iterations (all of
    them when fewer exist; None: fewer than 2 values or a vector). ``floor`` None: the quantity's
    default (core/reports.default_floor)."""
    values = [v for _, v in unique_by_iteration(series)][-window:]
    if len(values) < 2 or isinstance(values[-1], tuple):
        return None
    mean = sum(values) / len(values)
    spread = max(values) - min(values)
    if floor is None and quantity is not None:
        floor = default_floor(quantity)
    if floor is None:
        amplitude = None if abs(mean) < MEAN_FLOOR else spread / abs(mean)
    else:
        amplitude = spread / max(abs(mean), floor)
    return WindowStats(mean, spread, amplitude, len(values))


@dataclass(frozen=True)
class CriterionStatus:
    """One criterion's live state: value compared with threshold, and whether it is met."""

    description: str
    value: float | None  # None: not computed yet
    threshold: float
    satisfied: bool
    note: str = ""  # e.g. "from iteration 50"
    label: str = ""  # short_label
    iteration: float | None = None  # the iteration the value belongs to
    name: str = ""  # condition_name


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
    for i, c in enumerate(stopping.criteria):
        earliest = earliest_iteration(c, stopping.min_iterations)
        if isinstance(c, ResidualCriterion):
            got = residual_value(residuals, c.field)
            value, it = (got[1], got[0]) if got else (None, None)
            met = value is not None and value < c.threshold
            threshold = c.threshold
        else:
            series = unique_by_iteration(quantity(c.quantity))
            value = criterion_value(series, c)
            it = series[-1][0] if series else None
            met = value is not None and value <= c.tolerance
            threshold = c.tolerance
        early = it is None or it < earliest
        note = f"from iteration {earliest}" if early and earliest > 1 else ""
        out.append(CriterionStatus(describe(c), value, threshold, met and not early, note, short_label(c),
                                   it, condition_name(i, c)))
    return out


def criteria_met(stopping: StoppingCriteria, statuses: Sequence[CriterionStatus],
                 iteration: float) -> tuple[str, ...]:
    """The names of the criteria that stop the run at ``iteration`` ("all": every criterion is
    met at that iteration; "any": at least one), or () when the run goes on. A criterion whose
    value belongs to another iteration (its file lags behind the log) is not met."""
    met = tuple(s.name for s in statuses if s.satisfied and s.iteration == iteration)
    if not statuses or not met:
        return ()
    if stopping.combine == "all" and len(met) < len(statuses):
        return ()
    return met


@dataclass(frozen=True)
class Oscillation:
    """A monitored quantity that oscillates over the window without drifting."""

    quantity: str
    amplitude: float  # (max - min) / max(|mean|, floor) over the window
    mean: float
    spread: float = 0.0  # max - min
    floor: float = 0.0

    def message(self, suggest_mean_stable: bool = False) -> str:
        """The warning; ``suggest_mean_stable`` adds the hint to judge the windowed mean with the
        mean-stable criterion (D-118: the quantity has no mean-stable criterion yet)."""
        label = quantity_label(self.quantity)
        tail = " - the flow may be unsteady; a steady solution may not exist"
        if suggest_mean_stable:
            tail += f". If its mean is steady, stop on it with a \"mean stable\" criterion on {label}"
        if abs(self.mean) >= self.floor:
            return f"{label} oscillates by {100 * self.amplitude:.2g}%{tail}"
        return (f"{label} oscillates with a range of {self.spread:.2g} around a mean near zero "
                f"({self.mean:.2g}){tail}")


# Quantities without a scale floor (no criterion floor, no default): the relative amplitude is
# not evaluated when the mean is this close to zero (it is undefined).
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


def oscillation(quantity: str, series: Series, window: int, threshold: float,
                floor: float | None = None) -> Oscillation | None:
    """The oscillation warning of one quantity, or None.

    Over the last ``window`` values: amplitude a = (max - min) / max(|mean|, floor), the
    asymptotic criterion's normalisation (``floor`` None: the quantity's default,
    core/reports.default_floor; a quantity without one is not evaluated when |mean| < MEAN_FLOOR).
    It is reported when a > threshold and the mean is not drifting, i.e. the least-squares line
    through the window changes by less than DRIFT_FRACTION * (max - min) (a monotonic ramp changes
    by about its whole range; an oscillation over at least two periods by much less). Not
    evaluated with fewer than ``window`` values.
    """
    values = [v for _, v in unique_by_iteration(series)]
    if len(values) < window or window < 2 or any(isinstance(v, tuple) for v in values[-1:]):
        return None  # too short, or a vector (a probe's U): not checked
    last = values[-window:]
    mean = sum(last) / window
    spread = max(last) - min(last)
    if floor is None:
        floor = default_floor(quantity)
    if floor is None:
        if abs(mean) < MEAN_FLOOR:
            return None
        floor = 0.0
    if not all(math.isfinite(v) for v in last) or spread <= 0:
        return None
    amplitude = spread / max(abs(mean), floor)
    if amplitude <= threshold or abs(linear_change(last)) >= DRIFT_FRACTION * spread:
        return None
    return Oscillation(quantity, amplitude, mean, spread, floor)
