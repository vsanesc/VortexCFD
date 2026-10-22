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

    folder = WORK / (f"alpha_{args.alpha:g}_base_{args.base:g}" + (f"_mc{args.mesh_cores}" if args.mesh_cores else ""))
    project = nc.build_project(folder, alpha=args.alpha, base_size=args.base)
    if args.radius:  # diagnostic: the domain size (radius and wake in chords)
        folder = folder.with_name(folder.name + f"_R{args.radius:g}")
        project = nc.build_project(folder, alpha=args.alpha, base_size=args.base)
        project.update_domain(radius=args.radius, downstream=args.radius)
    if args.mesh_cores:  # a set-up choice: the meshing ranks (D-111; a parallel mesh is not bit-identical)
        project.update_mesh(cores=args.mesh_cores)
    if args.buffer:  # diagnostic (round 2): the 2D staircase buffer, cells per level
        from vortexcfd.foam import mesh_case

        mesh_case.WR_SECTION_BUFFER_CELLS = args.buffer  # the NACA set-up is wall-resolved (D-124)
        folder = folder.with_name(folder.name + f"_buf{args.buffer}")
        project = nc.build_project(folder, alpha=args.alpha, base_size=args.base)
        if args.radius:
            project.update_domain(radius=args.radius, downstream=args.radius)
            project.save()
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
    if report is not None:
        record["check_mesh_failures"] = list(report.failed_check_lines) or None
    if args.mesh_only and not refusal:
        say(f"alpha {args.alpha:g}: mesh only: {report.cells} cells, valid {report.valid}")
    elif refusal:
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
        record["diagnostics"] = flow_diagnostics(case, args.alpha, stopping)
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


def cell_centres(mesh: PolyMesh) -> np.ndarray:
    """Approximate cell centres: the mean of each cell's face centres."""
    centres = face_geometry(mesh.points, mesh.faces)[0]
    n = int(max(mesh.owner.max(), mesh.neighbour.max() if len(mesh.neighbour) else 0)) + 1
    total, count = np.zeros((n, 3)), np.zeros(n)
    np.add.at(total, mesh.owner, centres)
    np.add.at(count, mesh.owner, 1.0)
    inner = centres[:len(mesh.neighbour)]
    np.add.at(total, mesh.neighbour, inner)
    np.add.at(count, mesh.neighbour, 1.0)
    return total / count[:, None]


def flow_diagnostics(case: Path, alpha: float, stopping) -> dict:
    """The round 2 diagnosis numbers of a finished run: CL, CD (pressure, viscous), CM (recorded values, D-119), the
    upper-surface Cp and Cf near the trailing edge (Cf signed along the body x axis: negative = reversed flow), the
    reversed-flow start on the upper surface, and nut / nu from the inlet to the airfoil along z = 0."""
    from vortexcfd.foam.dictfile import read_foam_file
    from vortexcfd.foam.wall_fields import skin_friction_along

    out: dict = {"values": {}, "basis": {}}
    monitor = ReportMonitor(case)
    monitor.poll()
    for q in ("Cl", "Cd", "Cd_pressure", "Cd_viscous", "CmPitch"):
        v = recorded_value(q, monitor.series(q), stopping)
        if v is not None:
            out["values"][q], out["basis"][q] = v.value, v.basis
    t = latest_time(case)
    if t is None:
        return out
    mesh = PolyMesh.read(case)
    start, n = mesh.boundary[PATCH]
    centres = face_geometry(mesh.points, mesh.faces[start:start + n])[0]
    a = math.radians(alpha)
    dx, dz = centres[:, 0] - nc.CENTRE[0], centres[:, 2] - nc.CENTRE[2]
    xb = nc.CENTRE[0] + math.cos(a) * dx - math.sin(a) * dz
    zb = math.sin(a) * dx + math.cos(a) * dz
    q = 0.5 * nc.SPEED ** 2
    # p is zeroGradient on the wall: the wall-adjacent cell's value
    p = np.asarray(read_foam_file(t / "p")["internalField"], dtype=float)[mesh.owner[start:start + n]]
    tau = wall_face_values(t / "wallShearStress", [PATCH])[PATCH]
    cf = skin_friction_along(tau, (math.cos(a), 0.0, -math.sin(a)), nc.SPEED)
    upper = np.flatnonzero(zb > 0)
    order = upper[np.argsort(xb[upper])]
    stations = (0.5, 0.8, 0.9, 0.95, 0.99)
    out["upper_cp"] = {f"{s:g}": float(np.interp(s, xb[order], p[order] / q)) for s in stations}
    out["upper_cf"] = {f"{s:g}": float(np.interp(s, xb[order], cf[order])) for s in stations}
    aft = order[xb[order] > 0.3]
    reversed_ = aft[cf[aft] < 0]
    out["upper_reversed_from"] = float(xb[reversed_].min()) if reversed_.size else None
    out["upper_cf_min_aft"] = float(cf[aft].min()) if aft.size else None
    # nut / nu on z = 0 ahead of the quarter chord (wind axes), and the inlet value
    nut = np.asarray(read_foam_file(t / "nut")["internalField"], dtype=float)
    cells = cell_centres(mesh)
    decay = {}
    for d in (-99.0, -50.0, -10.0, -2.0, -1.0):
        target = np.array([nc.CENTRE[0] + d, cells[0, 1], 0.0])
        i = int(np.argmin(((cells - target) ** 2).sum(axis=1)))
        decay[f"{d:g}"] = float(nut[i] / nc.NU) if nut.ndim == 1 else None
    k_in = read_foam_file(case / "0" / "k")["boundaryField"]["inlet"]["value"]
    w_in = read_foam_file(case / "0" / "omega")["boundaryField"]["inlet"]["value"]
    out["inlet_k"], out["inlet_omega"] = float(k_in), float(w_in)
    out["nut_ratio_inlet"] = float(k_in) / float(w_in) / nc.NU
    out["nut_ratio_ahead"] = decay  # chords from the quarter chord along z = 0
    return out


def scheme_tokens(text: str) -> tuple:
    """A scheme entry as a token tuple, numbers typed (foamlib refuses a numeric string as a token)."""
    def token(t: str):
        try:
            return int(t)
        except ValueError:
            try:
                return float(t)
            except ValueError:
                return t
    return tuple(token(t) for t in text.split())


def cmd_diag(args) -> None:
    """Round 2, Part B: one change at a time on a copy of a round 1 level (its mesh and the app's solver files),
    either from the uniform free stream or restarted from that level's converged solution. Diagnostic only: the
    overrides are written into the copy, never into the app."""
    from vortexcfd.foam.dictfile import read_foam_file, set_foam_entry
    from vortexcfd.foam.solver_run import SolverRun
    import shutil

    source = (Path(args.source) if args.source else STUDY_PROJECT / "case_study" / "level_2").resolve()
    dest = WORK / "r2" / args.name / "case"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("constant", "system"):
        shutil.copytree(source / name, dest / name)
    for name in ("case.foam", "vortexcfd_domain.json"):
        if (source / name).exists():
            shutil.copy2(source / name, dest / name)
    (dest / "system" / "decomposeParDict").unlink(missing_ok=True)
    project = Project.open(STUDY_PROJECT / "naca0012.json")
    if args.tu is not None or args.ratio is not None:
        project.update_inflow(**({"turbulence_intensity": args.tu} if args.tu is not None else {}),
                              **({"viscosity_ratio": args.ratio} if args.ratio is not None else {}))
    mesh_study.solver_writer(project)(dest)
    if args.kw_scheme:  # e.g. "bounded Gauss linearUpwind grad(k)"; "{f}" stands for the field name
        schemes = read_foam_file(dest / "system" / "fvSchemes")
        div = dict(schemes["divSchemes"])
        for f in ("k", "omega"):
            div[f"div(phi,{f})"] = scheme_tokens(args.kw_scheme.format(f=f))
        set_foam_entry(dest / "system" / "fvSchemes", "divSchemes", div)
        if args.grad_kw:
            grads = dict(schemes["gradSchemes"])
            for f in ("k", "omega"):
                grads[f"grad({f})"] = scheme_tokens(args.grad_kw)
            set_foam_entry(dest / "system" / "fvSchemes", "gradSchemes", grads)
    stopping = project.sim.solvers.stopping
    limit = args.limit or nc.ITERATION_LIMIT
    if args.restart:
        t0 = latest_time(Path(args.restart))
        shutil.copytree(t0, dest / t0.name, ignore=shutil.ignore_patterns("uniform", "wallShearStress", "yPlus"))
        set_foam_entry(dest / "system" / "controlDict", "startFrom", "latestTime")
        set_foam_entry(dest / "system" / "controlDict", "endTime", int(float(t0.name)) + limit)
        set_foam_entry(dest / "system" / "controlDict", "writeInterval", int(float(t0.name)) + limit)
        stopping = stopping.model_copy(update={"min_iterations": int(float(t0.name)) + 500})
    else:
        set_foam_entry(dest / "system" / "controlDict", "endTime", limit)
    run = SolverRun(dest, stopping=stopping, cores=project.sim.studies.mesh.cores, timeout_s=7200)
    say(f"diag {args.name}: solving {dest} (restart {args.restart or 'no'}, k/omega {args.kw_scheme or 'app'}, "
        f"Tu {args.tu or 'app'}, ratio {args.ratio or 'app'})")
    run.start()
    res = run.wait()
    record = {"name": args.name, "source": str(source.relative_to(ROOT)), "restart": args.restart,
              "kw_scheme": args.kw_scheme, "grad_kw": args.grad_kw, "tu": args.tu, "ratio": args.ratio,
              "state": res.state, "iterations": res.iterations, "duration_s": round(res.duration_s, 1),
              "criteria_met": list(res.criteria_met)}
    record.update(flow_diagnostics(dest, nc.STUDY_ANGLE, stopping))
    (dest.parent / "diag.json").write_text(json.dumps(record, indent=2) + "\n")
    say(f"diag {args.name}: {res.state} at {res.iterations}, {res.duration_s:.0f} s, {record['values']}")


def cmd_inspect(args) -> None:
    """The diagnosis numbers of an existing round 1 run (no solver run)."""
    case = Path(args.case)
    record = {"case": str(case), **flow_diagnostics(case, args.alpha, nc.stopping())}
    print(json.dumps(record, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(record, indent=2) + "\n")


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
    an.add_argument("--mesh-cores", type=int, default=None)
    an.add_argument("--radius", type=float, default=None)
    an.add_argument("--buffer", type=int, default=None)
    an.add_argument("--mesh-only", action="store_true")
    sub.add_parser("collect")
    dg = sub.add_parser("diag")
    dg.add_argument("--name", required=True)
    dg.add_argument("--source", default=None, help="a round 1 case to copy (default: the medium 10 deg level)")
    dg.add_argument("--restart", default=None, help="start from this case's latest time")
    dg.add_argument("--kw-scheme", default=None)
    dg.add_argument("--grad-kw", default=None)
    dg.add_argument("--tu", type=float, default=None)
    dg.add_argument("--ratio", type=float, default=None)
    dg.add_argument("--limit", type=int, default=None)
    ins = sub.add_parser("inspect")
    ins.add_argument("--case", required=True)
    ins.add_argument("--alpha", type=float, default=nc.STUDY_ANGLE)
    ins.add_argument("--out", default=None)
    args = parser.parse_args()
    {"setup": cmd_setup, "study": cmd_study, "angle": cmd_angle, "collect": cmd_collect, "diag": cmd_diag,
     "inspect": cmd_inspect}[args.command](args)


if __name__ == "__main__":
    main()
