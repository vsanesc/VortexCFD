"""Square cylinder at Re 22,000, 2D URANS (task 1.1-transient Part 2, Part B; docs/validation/square_re22000/SETUP.md):
the case set up through the app's workflow layer, meshed and solved per level as Generate Mesh then Run Solver would.

    nice -n 15 .venv/bin/python scripts/validation/square_study.py level --name coarse [--set algorithm=piso]
    .venv/bin/python scripts/validation/square_study.py collect     # -> docs/validation/square_re22000/result.json

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
        out["solve"] = cylinder_study.solve(project)
    path = WORK / f"{folder.name}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
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
    level.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    level.set_defaults(func=cmd_level)
    collect = sub.add_parser("collect")
    collect.add_argument("runs", nargs="+", help="run names (the level and its tag), e.g. coarse medium")
    collect.set_defaults(func=cmd_collect)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
