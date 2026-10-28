"""Compare transient runs over one sampling window (task 1.1-transient, Part 2 closing brief; docs/validation/
startup_perturbation/SETUP.md and docs/validation/square_re22000/SETUP.md, "Time-step convergence").

    .venv/bin/python scripts/validation/window_compare.py --window 96 150 --ref swing \\
        swing=run/validation/square_re22000/coarse initial=run/validation/square_re22000/coarse_initial \\
        [--rule halves|relative] [--tolerance 0.02] [--out docs/validation/startup_perturbation/square.json]

Each run is LABEL=PROJECT_FOLDER (the folder holding case/). For every run, over the window [a, b] (in flow-through
times t_c, from the case's system/transientControl) and over its two halves [a, m] and [m, b]: the Strouhal number of
the lift, the mean Cd and the RMS of Cl, by the app's own functions (foam/transient: window_stats, strouhal), from
the whole force history (every postProcessing start-time folder). Also the start-up time the app's detection gives
on that history (foam/transient.detect_start with the run's window, tolerances and the end of its start-up
perturbation) and the time steps up to it (from the solver log).

Rules (written before the runs, in the SETUP files):
- ``halves``: a run is equivalent to the reference when, for each quantity Q, |Q_run - Q_ref| over the whole window
  is at most max(|Q_run(a, m) - Q_run(m, b)|, |Q_ref(a, m) - Q_ref(m, b)|).
- ``relative``: a run agrees with the reference when |Q_run - Q_ref| / |Q_ref| <= ``tolerance`` for St and mean Cd.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vortexcfd.foam import transient  # noqa: E402
from vortexcfd.foam.logparse import parse_log_text  # noqa: E402
from vortexcfd.foam.postprocessing import ReportMonitor  # noqa: E402
from vortexcfd.foam.solver_run import CHECK_FRACTION, solver_log  # noqa: E402

QUANTITIES = ("st", "cd_mean", "cl_rms")


def window_values(series: dict, control, start: float, end: float) -> dict:
    """St, mean Cd and RMS Cl over [start, end] (s)."""
    cd = transient.window_stats(series["Cd"], start, end)
    cl = transient.window_stats(series["Cl"], start, end)
    found = transient.strouhal(series["Cl"], control.length, control.speed, start, end)
    return {"st": found[0] if found else None, "cycles": found[1] if found else None,
            "cd_mean": cd.mean if cd else None, "cl_rms": cl.rms if cl else None}


def analyse(folder: Path, a: float, b: float) -> dict:
    case = folder / "case"
    control = transient.read_control(case)
    if control is None:
        raise SystemExit(f"{case}: no system/transientControl")
    t_c = control.convective_time
    monitor = ReportMonitor(case)
    monitor.poll()
    series = {q: monitor.series(q) for q in ("Cd", "Cl")}
    last = min(rows[-1][0] for rows in series.values()) / t_c
    if last < b - 1e-6:
        raise SystemExit(f"{case}: the force history ends at {last:.3f} t_c, before the window's end {b}")
    m = 0.5 * (a + b)
    out = {"folder": str(folder), "convective_time": t_c, "not_before_tc": control.not_before / t_c,
           "window": [a, b],
           "whole": window_values(series, control, a * t_c, b * t_c),
           "first_half": window_values(series, control, a * t_c, m * t_c),
           "second_half": window_values(series, control, m * t_c, b * t_c)}
    out["halves_diff"] = {q: abs(out["first_half"][q] - out["second_half"][q]) for q in QUANTITIES}
    detected = transient.detect_start(series, control.window, control.tolerance, control.stop_quantity,
                                      step=control.window * CHECK_FRACTION, range_tolerance=control.range_tolerance,
                                      not_before=control.not_before)  # checked as often as SolverRun checks
    steps = parse_log_text(solver_log(case).read_text(errors="replace")).time_steps
    out["detected_tc"] = None if detected is None else detected / t_c
    out["steps_to_detected"] = None if detected is None else sum(1 for s in steps if s.time <= detected + 1e-12)
    out["steps_total"] = len(steps)
    return out


def compare(run: dict, ref: dict, rule: str, tolerance: float) -> dict:
    rows = {}
    for q in QUANTITIES:
        diff = abs(run["whole"][q] - ref["whole"][q])
        relative = diff / abs(ref["whole"][q])
        if rule == "halves":
            limit = max(run["halves_diff"][q], ref["halves_diff"][q])
            ok = diff <= limit
        else:
            limit = tolerance * abs(ref["whole"][q])
            ok = diff <= limit if q in ("st", "cd_mean") else None
        rows[q] = {"diff": diff, "relative": relative, "limit": limit, "within": ok}
    decided = [r["within"] for r in rows.values() if r["within"] is not None]
    return {"quantities": rows, "verdict": "equivalent" if all(decided) else "not equivalent"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", type=float, nargs=2, required=True, metavar=("A", "B"), help="t_c")
    parser.add_argument("--ref", required=True, help="the label of the reference run")
    parser.add_argument("--rule", choices=("halves", "relative"), default="halves")
    parser.add_argument("--tolerance", type=float, default=0.02, help="the relative rule's tolerance")
    parser.add_argument("--out", type=Path)
    parser.add_argument("runs", nargs="+", metavar="LABEL=FOLDER")
    args = parser.parse_args()
    a, b = args.window
    runs = {}
    for item in args.runs:
        label, _, folder = item.partition("=")
        runs[label] = analyse(Path(folder), a, b)
    ref = runs[args.ref]
    result = {"window_tc": [a, b], "rule": args.rule, "reference": args.ref, "runs": runs, "comparisons": {}}
    if args.rule == "relative":
        result["tolerance"] = args.tolerance
    for label, run in runs.items():
        if label != args.ref:
            result["comparisons"][label] = compare(run, ref, args.rule, args.tolerance)
    for label, run in runs.items():
        w, h1, h2 = run["whole"], run["first_half"], run["second_half"]
        print(f"{label}: St {w['st']:.5f} ({h1['st']:.5f} / {h2['st']:.5f}), Cd {w['cd_mean']:.5f} "
              f"({h1['cd_mean']:.5f} / {h2['cd_mean']:.5f}), Cl RMS {w['cl_rms']:.5f} ({h1['cl_rms']:.5f} / "
              f"{h2['cl_rms']:.5f}), cycles {w['cycles']:.2f}; detected {run['detected_tc']} t_c after "
              f"{run['steps_to_detected']} of {run['steps_total']} steps")
    for label, c in result["comparisons"].items():
        parts = ", ".join(f"{q} {r['diff']:.3g} ({100 * r['relative']:.2f} %) limit {r['limit']:.3g}"
                          for q, r in c["quantities"].items())
        print(f"{label} vs {args.ref}: {c['verdict']}: {parts}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
