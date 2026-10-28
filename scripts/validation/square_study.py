"""Square cylinder at Re 22,000, 2D URANS (task 1.1-transient Part 2, Part B; docs/validation/square_re22000/SETUP.md):
the case set up through the app's workflow layer, meshed and solved per level as Generate Mesh then Run Solver would.

    nice -n 15 .venv/bin/python scripts/validation/square_study.py level --name coarse [--set algorithm=piso]
    nice -n 15 .venv/bin/python scripts/validation/square_study.py continue --run coarse --start 50 --end 201
    .venv/bin/python scripts/validation/square_study.py collect coarse medium  # -> docs/validation/square_re22000/

The projects go to run/validation/square_re22000/ (git-ignored); the numbers to docs/validation/square_re22000/.
The meshing and solving steps are the cylinder driver's (scripts/validation/cylinder_study.py).
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402
from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

apply_display_guard()
isolate_settings()  # never the user's settings or Recent list (D-141); before the cylinder driver is loaded
_spec = importlib.util.spec_from_file_location("cylinder_study", Path(__file__).with_name("cylinder_study.py"))
cylinder_study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cylinder_study)  # the display guard and the isolated settings come with it

from tests.validation import square_case as sc  # noqa: E402
from vortexcfd.workflow import meshing  # noqa: E402

WORK = ROOT / "run" / "validation" / "square_re22000"
OUT = ROOT / "docs" / "validation" / "square_re22000"
say = cylinder_study.say


def cmd_level(args) -> None:
    folder = WORK / (args.name + (f"_{args.tag}" if args.tag else ""))
    extra = {}
    for item in args.set:  # Transient fields: key=value (JSON values)
        key, _, value = item.partition("=")
        try:
            extra[key] = json.loads(value)
        except json.JSONDecodeError:
            extra[key] = value
    project = sc.build_project(folder, args.name, end_time=args.end, cores=args.cores, **extra)
    say(f"square {args.name}: base {sc.LEVELS[args.name]:.4g} m, readiness {meshing.readiness(project)}")
    out = {"level": args.name, "base_m": sc.LEVELS[args.name], "settings": extra,
           "mesh": cylinder_study.mesh(project)}
    if not args.mesh_only:
        out["solve"] = cylinder_study.solve(project, timeout_s=args.timeout_h * 3600)
    path = WORK / f"{folder.name}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    say(f"wrote {path}")


def cmd_continue(args) -> None:
    """SETUP.md amendment 2: a level that ended without a detected start-up gets its sampling start by hand and is
    continued to a later end with the app's Continue (D-189); its run record is updated."""
    import time

    from vortexcfd.core.project import Project
    from vortexcfd.foam.logparse import parse_log_text
    from vortexcfd.foam.run_record import RunRecord
    from vortexcfd.foam.solver_run import SolverRun, solver_log
    from vortexcfd.workflow import solving

    folder = WORK / args.run
    path = WORK / f"{args.run}.json"
    data = json.loads(path.read_text())
    project = Project.open(folder / "square.json")
    project.update_transient(sampling_start=args.start, end_time=args.end)
    project.save()
    tr = data["solve"]["transient"]
    record = RunRecord(data["solve"]["state"], tr["steps"], {}, "", 0, transient=tr,
                       settings_hash=solving.solution_hash(project))
    case, resume = solving.prepare_continue(project, record)
    t0 = time.monotonic()
    run = SolverRun(case, cores=project.sim.solvers.cores, timeout_s=3600, resume=resume)
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    stats = (result.transient or {}).get("statistics") or {}
    say(f"continued {args.run}: {result.state} to t = {result.transient.get('end_time')} in {seconds:.0f} s; "
        f"sampling from {result.transient.get('sampling_start')}; St {stats.get('strouhal')}, "
        f"Cd {stats.get('coefficients', {}).get('Cd', {}).get('mean')}")
    steps = parse_log_text(solver_log(case).read_text(errors="replace")).time_steps
    data["solve"]["continued"] = {"sampling_start": args.start, "end": args.end, "state": result.state,
                                  "solve_s": round(seconds, 1), "steps_total": result.transient.get("steps"),
                                  "log_steps": len(steps)}
    data["solve"]["transient"] = result.transient
    path.write_text(json.dumps(data, indent=2) + "\n")
    say(f"wrote {path}")


def cmd_collect(args) -> None:
    table = []
    for name in args.runs:
        data = json.loads((WORK / f"{name}.json").read_text())
        stats = (data.get("solve", {}).get("transient") or {}).get("statistics") or {}
        c = stats.get("coefficients") or {}
        st, cd = stats.get("strouhal"), c.get("Cd", {}).get("mean")
        verdict, errors = sc.verdict(st, cd)
        table.append({"run": name, "level": data["level"], "settings": data.get("settings", {}),
                      "cells": data["mesh"]["cells"], "st": st, "cd_mean": cd,
                      "cl_rms": c.get("Cl", {}).get("rms"), "cycles": stats.get("cycles"), "errors": errors,
                      "verdict": verdict, "sampling_start": data["solve"]["transient"].get("sampling_start"),
                      "steps": data["solve"]["steps"], "solve_s": data["solve"]["solve_s"],
                      "max_courant": data["solve"]["max_courant"], "cores": data["mesh"].get("cores")})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps({"runs": table}, indent=2) + "\n")
    for r in table:
        say(f"{r['run']}: {r['cells']:,} cells, St {r['st']}, Cd {r['cd_mean']}, {r['cycles']} cycles, "
            f"{r['verdict']} {r['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    level = sub.add_parser("level")
    level.add_argument("--name", choices=list(sc.LEVELS), required=True)
    level.add_argument("--end", type=float, default=sc.END_TIME)
    level.add_argument("--cores", type=int, default=sc.CORES)
    level.add_argument("--mesh-only", action="store_true")
    level.add_argument("--tag", default="")
    level.add_argument("--timeout-h", type=float, default=3.0, help="the solver's time limit (hours)")
    level.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    level.set_defaults(func=cmd_level)
    cont = sub.add_parser("continue")
    cont.add_argument("--run", required=True)
    cont.add_argument("--start", type=float, required=True, help="the sampling start set by hand (t_c)")
    cont.add_argument("--end", type=float, required=True, help="the new end time (t_c)")
    cont.set_defaults(func=cmd_continue)
    collect = sub.add_parser("collect")
    collect.add_argument("runs", nargs="+", help="run names (the level and its tag), e.g. coarse medium")
    collect.set_defaults(func=cmd_collect)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
