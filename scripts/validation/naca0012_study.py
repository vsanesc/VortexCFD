"""NACA 0012 validation (task W2, Parts C-E; docs/validation/naca0012/SETUP.md): the TMR case set up through the
app's workflow layer, the three-level mesh study at 10 degrees run as the GUI's Mesh Study node runs it, and the
single runs at the other angles run as Generate Mesh then Run Solver would.

    .venv/bin/python scripts/validation/naca0012_study.py setup                 # project and the study plan
    .venv/bin/python scripts/validation/naca0012_study.py study [--level fine]  # mesh and solve the 10 deg levels
    .venv/bin/python scripts/validation/naca0012_study.py angle --alpha 15 --base 1.0
    .venv/bin/python scripts/validation/naca0012_study.py collect               # -> docs/validation/naca0012/result.json

Owner rule A6: a level whose layers collapsed (first-cell y+ above twice the target over more than 10 % of the wall,
from the D-109 first-cell report) is not solved. Run with nice -n 15. The projects go to run/validation/naca0012/
(git-ignored); the numbers to docs/validation/naca0012/result.json.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import naca0012_case as nc  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402

apply_display_guard()

import numpy as np  # noqa: E402

from vortexcfd.core.project import Project  # noqa: E402
from vortexcfd.foam.layer_walk import walk_layers  # noqa: E402
from vortexcfd.foam.mesh_study import StudyRun, quantity_rows, read_record, recorded_value  # noqa: E402
from vortexcfd.foam.polymesh import PolyMesh, face_geometry  # noqa: E402
from vortexcfd.foam.postprocessing import ReportMonitor  # noqa: E402
from vortexcfd.foam.wall_fields import wall_face_values  # noqa: E402
from vortexcfd.workflow import mesh_study, meshing, solving  # noqa: E402

WORK = ROOT / "run" / "validation" / "naca0012"
OUT = ROOT / "docs" / "validation" / "naca0012"
STUDY_PROJECT = WORK / "study_a10"
PATCH = "naca0012"


def say(text: str) -> None:
    print(f"[naca {time.strftime('%H:%M:%S')}] {text}", flush=True)


def collapse_check(level, report) -> str | None:
    """A6: refuse to solve a level whose layers collapsed."""
    first = report.first_cell if report is not None else None
    share = first.share_over_2x if first is not None else None
    if nc.collapsed(share):
        return (f"layers collapsed: {100 * share:.1f} % of the wall has a first cell above twice the planned "
                f"{first.planned_m:.3g} m (A6: inconclusive, not solved)")
    return None


def cmd_setup(_args) -> None:
    project = nc.build_project(STUDY_PROJECT)
    plan = mesh_study.plan_study(project)
    box = meshing.loaded_parts(project)[0]
    rows = []
    for lp in plan.levels:
        stack = mesh_study.level_layers(project, plan, lp)
        rows.append({"level": lp.level.name, "base_m": lp.estimate.base_size, "surface_m": lp.estimate.surface_size,
                     "span_m": lp.estimate.span, "background_cells": lp.estimate.total_cells,
                     "estimated_cells": lp.estimated_cells, "first_layer_m": stack[0], "layers": stack[1],
                     "expansion": stack[2]})
        say(f"{lp.level.name}: base {lp.estimate.base_size:.4g} m, surface cell {1e3 * lp.estimate.surface_size:.4g} mm, "
            f"{lp.estimate.total_cells:,} background cells, layers {stack[1]} x {stack[0]:.3g} m at {stack[2]:g}")
    (WORK / "plan.json").write_text(json.dumps({"levels": rows, "domain_area_m2": plan.domain_volume,
                                                "domain_bounds": box.bounds}, indent=2) + "\n")
    say(f"project {project.path}; mesh cores {meshing.mesh_cores(project, box).used}")


def cmd_study(args) -> None:
    project = Project.open(STUDY_PROJECT / "naca0012.json")
    only = [args.level] if args.level else None
    study_dir, record, inputs = mesh_study.prepare_study(project, only=only)
    previous = read_record(study_dir) if only else None
    if previous is not None and only:  # keep the other levels' results (one level per command)
        done = {lv.name: lv for lv in previous.levels}
        record.levels = [next((lv for lv in record.levels if lv.name == name), done.get(name))
                         for name in ("coarse", "medium", "fine") if name in done or name in only]
        record.levels = [lv for lv in record.levels if lv is not None]
    to_run = [lv.name for lv in record.levels if only is None or lv.name in only]
    say(f"study levels {to_run} in {study_dir}, mesh cores {record.mesh_cores}, solver cores {record.cores}")
    writer = mesh_study.solver_writer(project)

    class OnlyLevels(StudyRun):
        """StudyRun over the levels of this command only (the record keeps the others)."""

    stopping = project.sim.solvers.stopping
    keep = [lv for lv in record.levels if lv.name not in to_run]
    record.levels = [lv for lv in record.levels if lv.name in to_run]
    run = OnlyLevels(study_dir, record, writer, stopping=stopping, parts=inputs.patches, before_solve=collapse_check,
                     on_line=lambda line: print(line, end="") if args.verbose else None, solver_timeout_s=7200)
    t0 = time.monotonic()
    run.start()
    out = run.wait()
    out.levels = sorted(keep + out.levels, key=lambda lv: lv.index)
    from vortexcfd.foam.mesh_study import write_record

    write_record(study_dir, out)
    for lv in out.levels:
        say(f"{lv.name}: {lv.cells} cells, h {lv.h}, first cell {lv.first_cell_m} (share > 2x {lv.first_cell_share_over_2x}), "
            f"{lv.state_label}, {lv.iterations} it., {lv.duration_s} s, values {lv.values}, error {lv.error}")
    say(f"study {out.status} in {time.monotonic() - t0:.0f} s")


def cmd_angle(args) -> None:
    """One angle as the GUI runs it: Generate Mesh, the first-cell report checked (A6), Run Solver."""
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.solver_run import SolverRun

    folder = WORK / f"alpha_{args.alpha:g}_base_{args.base:g}"
    project = nc.build_project(folder, alpha=args.alpha, base_size=args.base)
    job = meshing.prepare_job(project)
    plan = meshing.plan_layers_for(project, job.box)
    say(f"alpha {args.alpha:g}: meshing in {job.case_dir} on {job.cores} cores, {plan.count} layers x {plan.first:.3g} m")
    t0 = time.monotonic()
    mesh = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=(plan.first, plan.count), cores=job.cores,
                   step_timeout_s=3600)
    mesh.start()
    result = mesh.wait()
    mesh_s = time.monotonic() - t0
    report = result.report if result is not None else None
    record = {"alpha": args.alpha, "base_m": args.base, "mesh_s": round(mesh_s, 1),
              "cells": report.cells if report else None, "mesh_ok": bool(report and report.valid),
              "first_cell_m": report.first_cell.mean_m if report and report.first_cell else None,
              "first_cell_share_over_2x": report.first_cell.share_over_2x if report and report.first_cell else None,
              "planned_first_m": plan.first, "layers": plan.count}
    refusal = None if report is not None and report.valid else "invalid mesh"
    refusal = refusal or collapse_check(None, report)
    if refusal:
        record["error"] = refusal
        say(f"alpha {args.alpha:g}: not solved: {refusal}")
    else:
        case = solving.prepare_solver_case(project)
        stopping = project.sim.solvers.stopping
        run = SolverRun(case, stopping=stopping, cores=project.sim.solvers.cores, timeout_s=7200)
        say(f"alpha {args.alpha:g}: solving {report.cells} cells on {project.sim.solvers.cores} cores")
        run.start()
        res = run.wait()
        monitor = ReportMonitor(case)
        monitor.poll()
        values = {}
        for q in ("Cl", "Cd", "CmPitch", "Cd_pressure", "Cd_viscous"):
            v = recorded_value(q, monitor.series(q), stopping)
            if v is not None:
                values[q] = v.value
        record.update({"state": res.state, "iterations": res.iterations, "duration_s": round(res.duration_s, 1),
                       "criteria_met": list(res.criteria_met), "values": values})
        say(f"alpha {args.alpha:g}: {res.state} at {res.iterations}, {res.duration_s:.0f} s, {values}")
    (folder / "angle.json").write_text(json.dumps(record, indent=2) + "\n")


def latest_time(case: Path) -> Path | None:
    times = [p for p in case.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit() and float(p.name) > 0]
    return max(times, key=lambda p: float(p.name)) if times else None


def wall_stats(case: Path, planned_first: float, count: int, target: float = 1.0) -> dict:
    """y+ at the first cell centre over the wall (area-weighted mean, share within a factor 2 of the target) and
    the layers from the mesh walk (strict coverage: the wall area with the full count)."""
    mesh = PolyMesh.read(case)
    walked = walk_layers(mesh, (PATCH,), count + 5)[PATCH]
    area = walked["area"]
    out = {"strict_coverage": float(area[walked["layers"] >= count].sum() / area.sum()),
           "mean_layers": float((area * walked["layers"]).sum() / area.sum()),
           "first_cell_mean_m": float((area * walked["first_cell"]).sum() / area.sum())}
    t = latest_time(case)
    if t is not None and (t / "yPlus").is_file():
        yp = wall_face_values(t / "yPlus", [PATCH]).get(PATCH)
        if yp is not None and len(yp) == len(area):
            within = (yp >= 0.5 * target) & (yp <= 2.0 * target)
            out.update({"yplus_mean": float((area * yp).sum() / area.sum()),
                        "yplus_within_2x": float(area[within].sum() / area.sum()),
                        "yplus_max": float(yp.max())})
    return out


def cmd_collect(_args) -> None:
    result = {"reference_sst": nc.TMR_SST, "ladson": nc.LADSON, "levels": [], "angles": []}
    study_dir = STUDY_PROJECT / "case_study"
    rec = read_record(study_dir)
    if rec is not None:
        for lv in rec.levels:
            row = {k: getattr(lv, k) for k in ("name", "factor", "cells", "h", "mesh_ok", "state", "state_label",
                                               "iterations", "duration_s", "values", "error", "planned_layers",
                                               "first_cell_m", "first_cell_share_over_2x", "value_basis")}
            case = study_dir / f"level_{lv.index + 1}"
            if lv.cells and lv.planned_layers:
                row.update(wall_stats(case, lv.planned_layers[0], int(lv.planned_layers[1])))
            result["levels"].append(row)
        result["gci"] = []
        for q in quantity_rows(rec):
            r = q.result
            result["gci"].append({"quantity": q.quantity, "values": q.values, "sizes": q.sizes, "note": q.note,
                                  "convergence": r.convergence if r else None, "order": r.order if r else None,
                                  "extrapolated": r.extrapolated if r else None,
                                  "gci_fine": r.gci_fine if r else None, "gci_medium": r.gci_medium if r else None,
                                  "asymptotic_ratio": r.asymptotic_ratio if r else None})
    for path in sorted(WORK.glob("alpha_*/angle.json")):
        row = json.loads(path.read_text())
        case = path.parent / "case"
        if row.get("cells") and "values" in row:
            row.update(wall_stats(case, row["planned_first_m"], row["layers"]))
        result["angles"].append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
    say(f"wrote {OUT / 'result.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    st = sub.add_parser("study")
    st.add_argument("--level", choices=("coarse", "medium", "fine"))
    st.add_argument("--verbose", action="store_true")
    an = sub.add_parser("angle")
    an.add_argument("--alpha", type=float, required=True)
    an.add_argument("--base", type=float, default=nc.FINE_BASE)
    sub.add_parser("collect")
    args = parser.parse_args()
    {"setup": cmd_setup, "study": cmd_study, "angle": cmd_angle, "collect": cmd_collect}[args.command](args)


if __name__ == "__main__":
    main()
