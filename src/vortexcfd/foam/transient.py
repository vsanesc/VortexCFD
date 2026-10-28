"""Transient runs (D-181): the control file, the statistics of the force history and the Strouhal number (no Qt).

A transient case carries ``system/transientControl`` (OpenFOAM ignores it), written by foam/physics_case and read by
foam/solver_run.SolverRun and the monitors: the convective time t_c = l_ref / U, the sampling start (None until it is
detected), the detection and stop settings and the fieldAverage entry the runner adds when the start is detected.

The force history of a transient run is sampled at the solver's (variable) time steps, so every statistic here is
time-weighted: the mean is the trapezoidal integral over the window divided by its length, the RMS the root of the
time-weighted mean square of the fluctuation about that mean (the standard deviation; for a lift whose mean is zero it
equals the RMS of the lift itself). [NUMERICS-REVIEW]
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

TRANSIENT_FILE = "system/transientControl"
# The initial-field perturbation's dictionary (D-198): setExprFields changes 0/U from it once, before the solver.
INITIAL_PERTURB_FILE = "system/setExprFieldsDict"
FIELD_AVERAGE = "fieldAverage1"  # the function object and its fields' prefix-free names (UMean, pPrime2Mean, ...)
# The coefficients whose ranges must settle before the sampling starts (with the stop quantity's mean).
DETECT_RANGES = ("Cd", "Cl")
# The default relative change of a coefficient's range (max - min) between two consecutive windows below which the
# start-up transient is over: a growing or decaying oscillation changes its range by more (D-181; editable, D-186).
# [NUMERICS-REVIEW]
RANGE_TOLERANCE = 0.05
# A Strouhal number from fewer cycles than this in the sampling window is shown with a warning.
MIN_CYCLES = 3.0


@dataclass(frozen=True)
class TransientControl:
    """The case's transient settings in seconds (TRANSIENT_FILE)."""

    convective_time: float  # t_c = l_ref / U (s)
    length: float  # l_ref (m): the Strouhal number's length
    speed: float  # U (m/s)
    end_time: float  # s
    window: float  # s: the detection and stop window
    tolerance: float  # relative: the mean's change (detection) and the running mean's range (stop)
    stop_quantity: str = "Cd"
    statistics_stop: bool = False
    sampling_start: float | None = None  # s; None: detected from the force history
    detected: bool = False  # the sampling start was detected (not set by the user)
    field_average: dict = field(default_factory=dict)  # the fieldAverage entry (timeStart set when it starts)
    range_tolerance: float = RANGE_TOLERANCE  # the detection's ranges (D-186)
    not_before: float = 0.0  # s: no sampling before this (the end of the start-up perturbations, D-187, D-198)
    max_courant: float | None = None  # the asked largest Courant number of an adaptive step (None: fixed step)
    max_delta_t: float | None = None  # s: the largest step of an adaptive run (D-194)
    # The declared start-up perturbations, one sentence each (physics_case.perturbation_lines, D-198); () with none.
    perturbations: tuple[str, ...] = ()

    def content(self) -> dict:
        data = {
            "convectiveTime": self.convective_time, "length": self.length, "speed": self.speed,
            "endTime": self.end_time, "window": self.window, "tolerance": self.tolerance,
            "stopQuantity": self.stop_quantity, "statisticsStop": self.statistics_stop,
            "detected": self.detected, "fieldAverage": dict(self.field_average),
            "rangeTolerance": self.range_tolerance, "notBefore": self.not_before,
        }
        if self.max_courant is not None and self.max_delta_t is not None:
            data["maxCourant"] = self.max_courant
            data["maxDeltaT"] = self.max_delta_t
        if self.sampling_start is not None:
            data["samplingStart"] = self.sampling_start
        if self.perturbations:  # quoted: foamlib writes a sentence only as a string token
            data["startupPerturbation"] = [f'"{line}"' for line in self.perturbations]
        return data

    @classmethod
    def from_content(cls, data: dict) -> "TransientControl":
        start = data.get("samplingStart")
        return cls(float(data["convectiveTime"]), float(data["length"]), float(data["speed"]),
                   float(data["endTime"]), float(data["window"]), float(data["tolerance"]),
                   str(data.get("stopQuantity", "Cd")), bool(data.get("statisticsStop", False)),
                   None if start is None else float(start), bool(data.get("detected", False)),
                   dict(data.get("fieldAverage", {})), float(data.get("rangeTolerance", RANGE_TOLERANCE)),
                   float(data.get("notBefore", 0.0)),
                   None if data.get("maxCourant") is None else float(data["maxCourant"]),
                   None if data.get("maxDeltaT") is None else float(data["maxDeltaT"]),
                   tuple(str(line).strip('"') for line in data.get("startupPerturbation", ())))

    def with_start(self, start: float, detected: bool) -> "TransientControl":
        return replace(self, sampling_start=float(start), detected=detected)


def read_control(case_dir: Path) -> TransientControl | None:
    """The transient control of a case, None for a steady case (or an unreadable file)."""
    from vortexcfd.foam.dictfile import read_foam_file

    path = Path(case_dir) / TRANSIENT_FILE
    if not path.is_file():
        return None
    try:
        return TransientControl.from_content(dict(read_foam_file(path)))
    except (OSError, KeyError, TypeError, ValueError):
        return None


def write_control(case_dir: Path, control: TransientControl) -> None:
    from vortexcfd.foam.dictfile import write_foam_file

    write_foam_file(Path(case_dir) / TRANSIENT_FILE, control.content(), object_name="transientControl")


def even_interval(span: float, interval: float) -> float:
    """The write interval that divides ``span`` (the end time less the start time of a run) into whole intervals no
    longer than ``interval``: OpenFOAM counts write times from the run's start time (Time::adjustDeltaT and
    Time::operator++, v2606), so a run's end is written only when it falls on one (D-181)."""
    if span <= 0 or interval <= 0:
        return interval
    return span / max(1, math.ceil(span / interval - 1e-9))


def field_average(start: float) -> dict:
    """The fieldAverage entry (v2606 src/functionObjects/field/fieldAverage, the tutorial
    incompressible/pimpleFoam/laminar/cylinder2D): the time-weighted mean and the mean of the squared fluctuation of
    U and p from ``start`` (s), every time step, written at the write times (UMean, UPrime2Mean, pMean,
    pPrime2Mean). [NUMERICS-REVIEW]"""
    item = {"mean": True, "prime2Mean": True, "base": "time"}
    return {
        "type": "fieldAverage",
        "libs": ["fieldFunctionObjects"],
        "fields": [("U", dict(item)), ("p", dict(item))],  # foamlib writes (U {...} p {...})
        "timeStart": float(start),
        "executeControl": "timeStep",
        "executeInterval": 1,
        "writeControl": "writeTime",
    }


# -- statistics ------------------------------------------------------------------------------------------------------


def _arrays(series: Sequence[tuple[float, float]], start: float | None = None, end: float | None = None):
    """Times and values of ``series`` (one value per time: a repeated time keeps its last row) within [start, end]."""
    rows: dict[float, float] = {}
    for t, v in series:
        rows[float(t)] = float(v)
    if not rows:
        return np.empty(0), np.empty(0)
    t = np.array(sorted(rows))
    x = np.array([rows[k] for k in t])
    keep = np.ones(len(t), dtype=bool)
    if start is not None:
        keep &= t >= start - 1e-12 * max(1.0, abs(start))
    if end is not None:
        keep &= t <= end + 1e-12 * max(1.0, abs(end))
    return t[keep], x[keep]


def time_mean(t: np.ndarray, x: np.ndarray) -> float | None:
    """The time-weighted (trapezoidal) mean of x over [t0, tn]; a single sample is its own mean."""
    if len(t) == 0:
        return None
    if len(t) == 1 or t[-1] <= t[0]:
        return float(np.mean(x))
    return float(np.trapezoid(x, t) / (t[-1] - t[0]))


def time_rms(t: np.ndarray, x: np.ndarray, mean: float | None = None) -> float | None:
    """The time-weighted RMS of the fluctuation about the mean (the standard deviation)."""
    mean = time_mean(t, x) if mean is None else mean
    if mean is None:
        return None
    square = time_mean(t, (x - mean) ** 2)
    return math.sqrt(max(square, 0.0)) if square is not None else None


def running_mean(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    """The cumulative time-weighted mean from the first sample: M(t_i) = (1 / (t_i - t_0)) integral x dt; the first
    value is x_0."""
    if len(t) == 0:
        return np.empty(0)
    area = np.concatenate(([0.0], np.cumsum(0.5 * (x[1:] + x[:-1]) * np.diff(t))))
    span = t - t[0]
    out = np.empty(len(t))
    out[0] = x[0]
    out[1:] = np.where(span[1:] > 0, area[1:] / np.where(span[1:] > 0, span[1:], 1.0), x[1:])
    return out


@dataclass(frozen=True)
class Stats:
    """A coefficient over the sampling window."""

    mean: float
    rms: float
    minimum: float
    maximum: float
    start: float
    end: float
    samples: int

    def as_dict(self) -> dict:
        return {"mean": self.mean, "rms": self.rms, "min": self.minimum, "max": self.maximum, "start": self.start,
                "end": self.end, "samples": self.samples}


def window_stats(series: Sequence[tuple[float, float]], start: float, end: float | None = None) -> Stats | None:
    """Mean, RMS, min and max of ``series`` from ``start`` (s) to ``end`` (default: the last row)."""
    t, x = _arrays(series, start, end)
    if len(t) == 0:
        return None
    mean = time_mean(t, x)
    return Stats(mean, time_rms(t, x, mean), float(x.min()), float(x.max()), float(t[0]), float(t[-1]), len(t))


@dataclass(frozen=True)
class Spectrum:
    """The dominant frequency of a signal and how well the window resolves it."""

    frequency: float  # Hz
    cycles: float  # periods of that frequency in the window
    duration: float  # s

    def strouhal(self, length: float, speed: float) -> float:
        return self.frequency * length / speed


def dominant_frequency(series: Sequence[tuple[float, float]], start: float | None = None,
                       end: float | None = None) -> Spectrum | None:
    """The frequency of the spectral peak of ``series`` over [start, end] [NUMERICS-REVIEW]: the signal is
    interpolated linearly onto a uniform grid at its median time step (the steps of an adaptive run vary), its mean
    removed, a Hann window applied and zero-padded to 8 times the next power of two; the peak bin (the zero
    frequency excluded) is refined by a parabola through the logarithms of the three magnitudes around it (exact for
    a Gaussian peak; the Hann window's peak is close to one). None with fewer than 16 samples or a constant
    signal."""
    t, x = _arrays(series, start, end)
    if len(t) < 16 or t[-1] <= t[0]:
        return None
    duration = float(t[-1] - t[0])
    dt = float(np.median(np.diff(t)))
    dt = max(dt, duration / 2 ** 18)  # at most 2^18 points
    grid = np.arange(t[0], t[-1] + 0.5 * dt, dt)
    grid = grid[grid <= t[-1]]
    signal = np.interp(grid, t, x)
    signal = signal - signal.mean()
    if not np.any(np.abs(signal) > 1e-14 * max(1.0, float(np.abs(x).max()))):
        return None
    n = len(signal)
    nfft = 8 * (1 << (n - 1).bit_length())
    magnitude = np.abs(np.fft.rfft(signal * np.hanning(n), nfft))
    k = int(np.argmax(magnitude[1:])) + 1
    shift = 0.0
    if 1 <= k < len(magnitude) - 1:
        a, b, c = (math.log(max(m, 1e-300)) for m in magnitude[k - 1:k + 2])
        denominator = a - 2.0 * b + c
        if denominator < 0:
            shift = 0.5 * (a - c) / denominator
    frequency = (k + shift) / (nfft * dt)
    return Spectrum(frequency, frequency * duration, duration)


def strouhal(series: Sequence[tuple[float, float]], length: float, speed: float, start: float | None = None,
             end: float | None = None) -> tuple[float, float] | None:
    """(St = f l_ref / U from the lift's dominant frequency, the cycles in the window), None when there is none."""
    peak = dominant_frequency(series, start, end)
    if peak is None or speed <= 0:
        return None
    return peak.strouhal(length, speed), peak.cycles


# -- the sampling start and the statistical stop ----------------------------------------------------------------------


def _window_values(t: np.ndarray, x: np.ndarray, start: float, end: float):
    keep = (t >= start) & (t <= end)
    return t[keep], x[keep]


def _relative(change: float, scale: float, floor: float) -> float:
    return abs(change) / max(abs(scale), floor)


def settled_at(series: dict[str, Sequence[tuple[float, float]]], now: float, window: float, tolerance: float,
               mean_quantity: str, floor: float = 0.01, range_tolerance: float = RANGE_TOLERANCE,
               not_before: float = 0.0) -> bool:
    """Whether the start-up transient is over at ``now`` [NUMERICS-REVIEW]: over the two consecutive windows
    [now - 2W, now - W] and [now - W, now], both after ``not_before`` (the end of a start-up perturbation, D-187),
    the time-weighted mean of ``mean_quantity`` changes by at most ``tolerance`` and the range (max - min) of each of
    DETECT_RANGES (and of ``mean_quantity``) by at most ``range_tolerance`` (default RANGE_TOLERANCE, D-186), each
    relative to max(|the last window's value|, ``floor``) (the D-058 normalisation; the floor
    of the force coefficients, 0.01). The range is compared, not the mean, for the lift: a window that is not a
    whole number of periods moves a lift's mean by a large share of its amplitude, its range hardly. A quantity
    without data in both windows keeps it unsettled; one that is not monitored (absent from ``series``) is
    skipped."""
    if now < 2 * window or now - 2 * window < not_before - 1e-12 * max(1.0, abs(not_before)):
        return False
    names = [mean_quantity] + [q for q in DETECT_RANGES if q != mean_quantity]
    checked = 0
    for name in names:
        if name not in series:
            continue
        t, x = _arrays(series[name], 0.0, now)
        ta, xa = _window_values(t, x, now - 2 * window, now - window)
        tb, xb = _window_values(t, x, now - window, now)
        if len(ta) < 2 or len(tb) < 2:
            return False
        range_a, range_b = float(xa.max() - xa.min()), float(xb.max() - xb.min())
        if _relative(range_b - range_a, range_b, floor) > range_tolerance:
            return False
        if name == mean_quantity:
            mean_a, mean_b = time_mean(ta, xa), time_mean(tb, xb)
            if _relative(mean_b - mean_a, mean_b, floor) > tolerance:
                return False
        checked += 1
    return checked > 0


def detect_start(series: dict[str, Sequence[tuple[float, float]]], window: float, tolerance: float,
                 mean_quantity: str, floor: float = 0.01, step: float | None = None,
                 range_tolerance: float = RANGE_TOLERANCE, not_before: float = 0.0) -> float | None:
    """The first time (checked every ``step``, default W / 20, from 2 W on, or from ``not_before`` + 2 W) at which
    ``settled_at`` holds, from the recorded histories (after a run, or to explain a live detection); None when it
    never does."""
    ends = [float(s[-1][0]) for name, s in series.items() if s and (name == mean_quantity or name in DETECT_RANGES)]
    if not ends:
        return None
    last = min(ends)
    step = step or window / 20.0
    now = 2 * window + max(not_before, 0.0)
    while now <= last + 1e-12:
        if settled_at(series, now, window, tolerance, mean_quantity, floor, range_tolerance, not_before):
            return now
        now += step
    return None


def running_mean_range(series: Sequence[tuple[float, float]], start: float, now: float, window: float,
                       floor: float = 0.01) -> float | None:
    """(max - min) / max(|M(now)|, floor) of the running mean M from ``start`` over the last ``window`` before
    ``now``: the asymptotic criterion's measure (D-058) on the running mean. None before the sampling has lasted
    2 W (the running mean of a shorter sample still moves by its averaging alone)."""
    if now - start < 2 * window:
        return None
    t, x = _arrays(series, start, now)
    if len(t) < 3:
        return None
    mean = running_mean(t, x)
    last = mean[t >= now - window]
    if len(last) < 2:
        return None
    return float(last.max() - last.min()) / max(abs(float(mean[-1])), floor)


def running_mean_stable(series: Sequence[tuple[float, float]], start: float, now: float, window: float,
                        tolerance: float, floor: float = 0.01) -> bool:
    """The statistical stop (D-181) [NUMERICS-REVIEW]: the running mean of the quantity from the sampling start
    varies by at most ``tolerance`` (relative, floor as above) over the last ``window``."""
    value = running_mean_range(series, start, now, window, floor)
    return value is not None and value <= tolerance


def summary(series: dict[str, Sequence[tuple[float, float]]], start: float, length: float, speed: float,
            lift: str = "Cl") -> dict:
    """The statistics of a run from ``start`` (s): {"coefficients": {name: Stats.as_dict()}, "strouhal": St or None,
    "cycles": the lift's cycles in the window}."""
    stats = {}
    for name, rows in series.items():
        s = window_stats(rows, start)
        if s is not None:
            stats[name] = s.as_dict()
    found = strouhal(series[lift], length, speed, start) if lift in series else None
    return {"start": start, "coefficients": stats, "strouhal": found[0] if found else None,
            "cycles": found[1] if found else None}


# -- what the monitors show (D-181) -----------------------------------------------------------------------------------


def running_mean_points(series: Sequence[tuple[float, float]], start: float | None) -> list[tuple[float, float]]:
    """(time, running mean from ``start``) at every row from the sampling start: the monitors' and report charts'
    dashed line of a transient run; [] before the sampling starts."""
    if start is None:
        return []
    t, x = _arrays(series, start)
    if len(t) == 0:
        return []
    return list(zip(t.tolist(), running_mean(t, x).tolist()))


def slot_text(series: Sequence[tuple[float, float]], start: float | None) -> str:
    """A report slot's line under the latest value: the running mean and the RMS from the sampling start, or that
    the sampling has not started."""
    if start is None:
        return "start-up: sampling not started"
    stats = window_stats(series, start)
    if stats is None or stats.samples < 2:
        return f"sampling from t = {start:.4g} s"
    return f"running mean {stats.mean:.4g}, RMS {stats.rms:.3g} (from t = {start:.4g} s)"


# The Courant cap warning (D-194): over the last CAP_STEPS steps, the step sits at the largest step in at least
# CAP_SHARE of them while the largest Courant number stays below CAP_COURANT of the asked one.
CAP_STEPS = 50
CAP_SHARE = 0.8
CAP_COURANT = 0.9


def courant_cap_warning(control: TransientControl | None, steps) -> str | None:
    """Why the asked Courant number is not reached, or None (D-194): an adaptive run whose time step is held at the
    largest time step (maxDeltaT) while the largest Courant number stays clearly below the asked maxCo. ``steps``:
    logparse.TimeSteps (``delta_t``, ``courant_max``) in time order."""
    if control is None or control.max_courant is None or not control.max_delta_t:
        return None
    recent = [s for s in list(steps)[-CAP_STEPS:] if s.delta_t and s.courant_max is not None]
    if len(recent) < CAP_STEPS // 2:
        return None
    capped = sum(s.delta_t >= 0.999 * control.max_delta_t for s in recent)
    reached = max(s.courant_max for s in recent)
    if capped < CAP_SHARE * len(recent) or reached >= CAP_COURANT * control.max_courant:
        return None
    return (f"The largest time step ({control.max_delta_t:.3g} s) holds the step: the largest Courant number is "
            f"{reached:.2g}, not the {control.max_courant:g} asked for. Raise \"Largest time step\" (Solvers > "
            "Transient) to run at the asked Courant number.")


def banner(control: TransientControl | None, state: str | None, now: float | None,
           summary_: dict | None = None) -> tuple[str, str | None]:
    """(text, colour state) of the convergence banner of a transient run (state None: running)."""
    if control is None:
        return "No solver run yet", None
    end = control.end_time
    if state is None:
        at = f"t = {now:.4g} s of {end:.4g} s" if now is not None else "starting"
        phase = ("start-up transient (sampling starts once it is over)" if control.sampling_start is None else
                 f"sampling from t = {control.sampling_start:.4g} s")
        return f"Solving (transient): {at}; {phase}", None
    if state == "criteria_met":
        met = (summary_ or {}).get("met_time")
        at = f" at t = {met:.4g} s" if met is not None else ""
        return (f"Statistics converged{at}: the running mean of {control.stop_quantity} varied by at most "
                f"{100 * control.tolerance:g}% over the last {control.window:.4g} s", "ok")
    if state == "end_time":
        return f"End time reached (t = {end:.4g} s)", "ok"
    if state == "stopped":
        return "Stopped by the user", "warn"
    if state == "crashed":
        return "The solver crashed", "error"
    return "No solver run yet", None


def statistics_text(summary_: dict | None, convective_time: float | None = None) -> str:
    """The statistics of a run as lines: the sampling window, each coefficient's mean and RMS, the Strouhal number
    (with a warning below MIN_CYCLES cycles)."""
    if not summary_:
        return ""
    lines = []
    start = summary_.get("start")
    coefficients = summary_.get("coefficients") or {}
    end = max((float(c["end"]) for c in coefficients.values()), default=None)
    if start is not None and end is not None:
        span = f"{end - start:.4g} s"
        if convective_time:
            span += f", {(end - start) / convective_time:.3g} flow-through times"
        lines.append(f"Sampling window t = {start:.4g} to {end:.4g} s ({span})")
    for name, c in coefficients.items():
        lines.append(f"{name}: mean {c['mean']:.4g}, RMS {c['rms']:.3g} (min {c['min']:.4g}, max {c['max']:.4g})")
    st = summary_.get("strouhal")
    if st is not None:
        cycles = float(summary_.get("cycles") or 0.0)
        warn = f" (only {cycles:.2g} cycles: sample longer)" if cycles < MIN_CYCLES else f" ({cycles:.3g} cycles)"
        lines.append(f"Strouhal number St = f l_ref / U = {st:.4g} from the lift{warn}")
    return "\n".join(lines)
