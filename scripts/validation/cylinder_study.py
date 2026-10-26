"""Circular cylinder at Re 100 (task 1.1-transient, Part B; docs/validation/cylinder_re100/SETUP.md): the 2D laminar
transient case set up through the app's workflow layer, meshed and solved per level as Generate Mesh then Run Solver
would, and the three-level mesh study on St and the mean Cd.

    nice -n 15 .venv/bin/python scripts/validation/cylinder_study.py level --name coarse [--end 120] [--mesh-only]
    nice -n 15 .venv/bin/python scripts/validation/cylinder_study.py level --name coarse --end 60 --start 30 --write 25 --tag short
    .venv/bin/python scripts/validation/cylinder_study.py collect     # -> docs/validation/cylinder_re100/result.json

The projects go to run/validation/cylinder_re100/ (git-ignored); the numbers to docs/validation/cylinder_re100/.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import cylinder_case as cc  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402
from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

apply_display_guard()
isolate_settings()  # never the user's settings or Recent list (D-141)

from vortexcfd.foam import gci  # noqa: E402
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record  # noqa: E402
from vortexcfd.foam.mesh_run import MeshRun  # noqa: E402
from vortexcfd.foam.logparse import parse_log_text  # noqa: E402
from vortexcfd.foam.solver_run import SolverRun, solver_log  # noqa: E402
from vortexcfd.workflow import meshing, solving  # noqa: E402

WORK = ROOT / "run" / "validation" / "cylinder_re100"
OUT = ROOT / "docs" / "validation" / "cylinder_re100"


def say(text: str) -> None:
    print(f"[cylinder {time.strftime('%H:%M:%S')}] {text}", flush=True)


def mesh(project) -> dict:
    job = meshing.prepare_job(project)
    t0 = time.monotonic()
    first = (job.inputs.first_layer_thickness, job.inputs.layer_count or 1) if job.inputs.first_layer_thickness else None
    run = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=first, cores=job.cores, step_timeout_s=3600)
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    if not result.success:
        raise SystemExit(f"meshing failed: {result.failed_step} {result.error}")
    report = result.report
    write_mesh_record(job.case_dir, MeshRecord(report, meshing.inputs_hash(project), job.inputs.patches, job.cores))
    say(f"mesh: {report.cells:,} cells in {seconds:.0f} s on {job.cores} cores, mesh OK {report.mesh_ok}, "
        f"max non-orthogonality {report.max_non_orthogonality}, layers "
        f"{[(c.patch, c.mesh_layers, c.thickness_percent) for c in report.layers]}")
    return {"cells": report.cells, "mesh_ok": report.mesh_ok, "mesh_s": round(seconds, 1), "cores": job.cores,
            "max_non_orthogonality": report.max_non_orthogonality}


def solve(project) -> dict:
    case = solving.prepare_solver_case(project)
    t0 = time.monotonic()
    run = SolverRun(case, cores=project.sim.solvers.cores, timeout_s=3 * 3600,
                    on_line=lambda line: line.startswith("Start-up transient") and say(line.strip()))
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    steps = parse_log_text(solver_log(case).read_text(errors="replace")).time_steps
    deltas = [s.delta_t for s in steps if s.delta_t]
    courant = [s.courant_max for s in steps if s.courant_max is not None]
    tr = result.transient or {}
    stats = tr.get("statistics") or {}
    coefficients = stats.get("coefficients") or {}
    say(f"solve: {result.state} after {result.iterations:,} steps to t = {tr.get('end_time')} in {seconds:.0f} s; "
        f"deltaT {min(deltas):.3g}..{max(deltas):.3g} s, max Co {max(courant):.3g}; sampling from "
        f"{tr.get('sampling_start')} ({'detected' if tr.get('detected') else 'set'}); St {stats.get('strouhal')}, "
        f"Cd mean {coefficients.get('Cd', {}).get('mean')}, Cl RMS {coefficients.get('Cl', {}).get('rms')}")
    averaged = sorted(str(p.relative_to(case)) for p in case.glob("[0-9]*/*Mean")) if case.is_dir() else []
    return {"state": result.state, "steps": result.iterations, "solve_s": round(seconds, 1),
            "delta_t": [min(deltas), max(deltas)], "first_delta_t": deltas[0] if deltas else None,
            "max_courant": max(courant), "transient": tr, "averaged_fields": averaged}


def cmd_level(args) -> None:
    folder = WORK / (args.name + (f"_{args.tag}" if args.tag else ""))
    project = cc.build_project(folder, args.name, end_time=args.end, cores=args.cores, sampling_start=args.start,
                               write_interval=args.write)
    say(f"{args.name}: base {cc.LEVELS[args.name]:.4g} m, readiness {meshing.readiness(project)}")
    out = {"level": args.name, "base_m": cc.LEVELS[args.name], "mesh": mesh(project)}
    if not args.mesh_only:
        out["solve"] = solve(project)
    path = WORK / f"{folder.name}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    say(f"wrote {path}")


def cmd_collect(_args) -> None:
    rows = {}
    for name in cc.LEVELS:
        path = WORK / f"{name}.json"
        if path.is_file():
            rows[name] = json.loads(path.read_text())
    table = []
    for name, data in rows.items():
        stats = (data.get("solve", {}).get("transient") or {}).get("statistics") or {}
        c = stats.get("coefficients") or {}
        st, cd, cl = stats.get("strouhal"), c.get("Cd", {}).get("mean"), c.get("Cl", {}).get("rms")
        verdict, errors = cc.verdict(st, cd, cl)
        table.append({"level": name, "cells": data["mesh"]["cells"], "st": st, "cd_mean": cd, "cl_rms": cl,
                      "cycles": stats.get("cycles"), "errors": errors, "verdict": verdict,
                      "sampling_start": data["solve"]["transient"].get("sampling_start"),
                      "steps": data["solve"]["steps"], "solve_s": data["solve"]["solve_s"]})
    study = {}
    if len(table) == 3 and all(r["st"] is not None for r in table):
        area = 1.0  # h = (A / N)^(1/2): the domain area is the same on every level, so any constant works
        sizes = [gci.cell_size(area, r["cells"], 2) for r in table]
        for key in ("st", "cd_mean"):
            res = gci.study([r[key] for r in table], sizes)
            study[key] = {"convergence": res.convergence, "order": res.order, "extrapolated": res.extrapolated,
                          "gci_fine": res.gci_fine, "asymptotic_ratio": res.asymptotic_ratio, "text": res.text}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps({"levels": table, "gci": study}, indent=2) + "\n")
    for r in table:
        say(f"{r['level']}: {r['cells']:,} cells, St {r['st']:.4f}, Cd {r['cd_mean']:.4f}, Cl RMS {r['cl_rms']:.4f}, "
            f"{r['cycles']:.1f} cycles, {r['verdict']} {r['errors']}")
    for key, s in study.items():
        say(f"GCI {key}: {s['text']} (p {s['order']}, extrapolated {s['extrapolated']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    level = sub.add_parser("level")
    level.add_argument("--name", choices=list(cc.LEVELS), required=True)
    level.add_argument("--end", type=float, default=cc.END_TIME)
    level.add_argument("--cores", type=int, default=cc.CORES)
    level.add_argument("--mesh-only", action="store_true")
    level.add_argument("--start", type=float, default=None, help="a set sampling start (t_c); default: detected")
    level.add_argument("--write", type=float, default=None, help="the write interval (t_c); default: the end time")
    level.add_argument("--tag", default="", help="a suffix of the run's folder (a run beside the study's)")
    level.set_defaults(func=cmd_level)
    sub.add_parser("collect").set_defaults(func=cmd_collect)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
