"""NASA TMR 2D backward-facing step (task w3-internal, Part C; docs/validation/bfs/SETUP.md): the case of
tests/validation/bfs_case.py, the three-level mesh study run as the GUI's Mesh Study node runs it, then the
reattachment length, Cf and Cp along the bottom wall per level.

    nice -n 15 .venv/bin/python scripts/validation/bfs_study.py setup                 # project and the study plan
    nice -n 15 .venv/bin/python scripts/validation/bfs_study.py study [--level medium]
    nice -n 15 .venv/bin/python scripts/validation/bfs_study.py collect               # -> docs/validation/bfs/

I5: a level whose layers collapsed (first cell above twice the plan on more than 10 % of the wall) is not solved and
does not count. Projects in run/validation/bfs/ (git-ignored).
"""

import argparse
import csv
import json
import math
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import bfs_case as bc  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402

apply_display_guard()

import numpy as np  # noqa: E402

from vortexcfd.core.project import Project  # noqa: E402
from vortexcfd.foam.convergence import window_stats  # noqa: E402
from vortexcfd.foam.gci import study as gci_study  # noqa: E402
from vortexcfd.foam.layer_walk import walk_layers  # noqa: E402
from vortexcfd.foam.mesh_study import StudyRun, level_dir, read_record, write_record  # noqa: E402
from vortexcfd.foam.polymesh import PolyMesh, face_geometry  # noqa: E402
from vortexcfd.foam.postprocessing import ReportMonitor  # noqa: E402
from vortexcfd.foam.results import latest_result_time  # noqa: E402
from vortexcfd.foam.wall_fields import wall_face_values  # noqa: E402
import pyvista as pv  # noqa: E402

from vortexcfd.workflow import internal, mesh_study, meshing, solving  # noqa: E402

WORK = ROOT / "run" / "validation" / "bfs"
OUT = ROOT / "docs" / "validation" / "bfs"
PROJECT = WORK / "bfs" / "bfs.vcfd"
FAMILIES = {"preset": (WORK, None, "", bc.X_INLET), "fine": (ROOT / "run" / "validation" / "bfs_fine", bc.FINE_FAMILY, "_finefamily", bc.X_INLET),
            # round 2 (QUESTIONS 209): the finer family with the inlet moved to match TMR's boundary layer
            "round2": (ROOT / "run" / "validation" / "bfs_r2", bc.FINE_FAMILY_ROUND2, "_round2", bc.X_INLET_ROUND2)}
WINDOW = 500
SHARE_LIMIT = 0.10  # I5: more than 10 % of the wall above twice the planned first cell: collapsed


def say(text: str) -> None:
    print(f"[bfs {time.strftime('%H:%M:%S')}] {text}", flush=True)


def collapse_check(level, report) -> str | None:
    first = report.first_cell if report is not None else None
    share = first.share_over_2x if first is not None else None
    if share is not None and share > SHARE_LIMIT:
        return (f"layers collapsed: {100 * share:.1f} % of the wall has a first cell above twice the planned "
                f"{first.planned_m:.3g} m (I5: not counted, not solved)")
    return None


def select(family: str) -> None:
    """Point the commands at a study family's project and output names."""
    global WORK, PROJECT, SUFFIX
    WORK, settings, SUFFIX, _x = FAMILIES[family]
    PROJECT = WORK / "bfs" / "bfs.vcfd"


SUFFIX = ""


def cmd_setup(args) -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    project = bc.build_project(WORK, FAMILIES[args.family][1], x_inlet=FAMILIES[args.family][3])
    say(f"readiness: {meshing.readiness(project)}")
    box = meshing.loaded_parts(project)[0]
    length = meshing.surface_length(project, box)
    say(f"surface length {length.describe()}; y+ speed {meshing.flow_speed(project):.4g} m/s; first layer "
        f"{meshing.plan_layers_for(project, box).first * 1e3:.4g} mm")
    plan = mesh_study.plan_study(project)
    say(f"study: current settings as {plan.current_as} ({plan.current_as_note})")
    rows = []
    for lp in plan.levels:
        stack = mesh_study.level_layers(project, plan, lp)
        rows.append({"level": lp.level.name, "base_m": lp.estimate.base_size, "surface_m": lp.estimate.surface_size,
                     "span_m": lp.estimate.span, "background_cells": lp.estimate.total_cells,
                     "estimated_cells": lp.estimated_cells, "first_layer_m": stack[0], "layers": stack[1],
                     "expansion": stack[2]})
        say(f"{lp.level.name}: base {lp.estimate.base_size:.4g} m, surface {lp.estimate.surface_size:.4g} m, "
            f"{lp.estimate.total_cells:,} background cells, about {lp.estimated_cells:,} cells, layers {stack[1]} x "
            f"{stack[0]:.3g} m at {stack[2]:.3g}")
    (WORK / "plan.json").write_text(json.dumps({"levels": rows, "current_as": plan.current_as,
                                                "note": plan.current_as_note}, indent=2) + "\n")


def cmd_study(args) -> None:
    project = Project.open(PROJECT)
    only = [args.level] if args.level else None
    study_dir, record, inputs = mesh_study.prepare_study(project, only=only)
    previous = read_record(study_dir) if only else None
    keep = []
    if previous is not None:
        keep = [lv for lv in previous.levels if lv.name not in only]
    record.levels = [lv for lv in record.levels if only is None or lv.name in only]
    say(f"levels {[lv.name for lv in record.levels]} in {study_dir}; mesh cores {record.mesh_cores}, solver cores "
        f"{record.cores}")
    run = StudyRun(study_dir, record, mesh_study.solver_writer(project), stopping=project.sim.solvers.stopping,
                   parts=inputs.patches, before_solve=collapse_check, solver_timeout_s=3 * 3600,
                   walls=internal.wall_patches(project))
    t0 = time.monotonic()
    run.start()
    out = run.wait()
    out.levels = sorted(keep + out.levels, key=lambda lv: lv.index)
    write_record(study_dir, out)
    for lv in out.levels:
        say(f"{lv.name}: {lv.cells} cells, first cell {lv.first_cell_m} (share > 2x {lv.first_cell_share_over_2x}), "
            f"{lv.state_label}, {lv.iterations} it., {lv.duration_s} s, error {lv.error}")
    say(f"study {out.status} in {time.monotonic() - t0:.0f} s")


def wall_data(case: Path, patches: tuple[str, ...]) -> dict[str, np.ndarray]:
    """Face centres (x, z), the kinematic wall shear stress and p (kinematic) of the bottom-wall patches at the
    latest time, sorted by x."""
    mesh = PolyMesh.read(case)
    centres, vectors, _ = face_geometry(mesh.points, mesh.faces)
    time_name = latest_result_time(case)
    tau = wall_face_values(case / time_name / "wallShearStress", patches)
    from vortexcfd.foam.dictfile import read_foam_file

    p_cells = np.asarray(read_foam_file(case / time_name / "p")["internalField"], dtype=float)
    p = {patch: p_cells[mesh.owner[start:start + count]]  # zeroGradient walls: the face takes its cell's value
         for patch, (start, count) in ((name, mesh.boundary[name]) for name in patches)}
    xs, zs, tx, ps = [], [], [], []
    for patch in patches:
        start, count = mesh.boundary[patch]
        xs.append(centres[start:start + count, 0])
        zs.append(centres[start:start + count, 2])
        tx.append(tau[patch][:, 0] if tau[patch].ndim == 2 else np.full(count, tau[patch][0]))
        ps.append(p[patch] if p[patch].size == count else np.full(count, p[patch][0]))
    x, z, t, pp = (np.concatenate(a) for a in (xs, zs, tx, ps))
    order = np.argsort(x)
    return {"x": x[order], "z": z[order], "tau_x": t[order], "p": pp[order], "time": time_name}


def reattachment(x: np.ndarray, cf: np.ndarray, start: float = 0.5, end: float = 30.0) -> float | None:
    """x where Cf_x crosses from negative to positive the last time before ``end`` (the main bubble's end; the corner
    bubble's sign changes near the step come first), linear interpolation between face centres."""
    sel = (x > start) & (x < end)
    xs, cs = x[sel], cf[sel]
    crossings = [i for i in range(len(cs) - 1) if cs[i] < 0 <= cs[i + 1]]
    if not crossings:
        return None
    i = crossings[-1]
    return float(xs[i] - cs[i] * (xs[i + 1] - xs[i]) / (cs[i + 1] - cs[i]))


WALLS = ("lower", "step", "floor", "upper")


def wall_layers(case: Path, planned: float, target: int) -> dict:
    """The walls' layers from the mesh walk: per patch the mean count, the share of the target kept (mean / target)
    and the area share of faces with the full count; over all walls the first cell's mean and the area share above
    twice the plan. ``complete``: every face of every wall has the full count (QUESTIONS 209 c: a level with an
    incomplete stack on any wall does not count)."""
    walked = walk_layers(PolyMesh.read(case), WALLS, 40)
    out, areas, cells, complete = {}, [], [], True
    for patch, d in walked.items():
        a, n = d["area"], d["layers"]
        full = float(a[n >= target].sum() / a.sum())
        out[patch] = {"mean": float(np.average(n, weights=a)), "kept": float(np.average(np.minimum(n, target), weights=a)) / target,
                      "full_share": full}
        complete = complete and full >= 1.0
        areas.append(a)
        cells.append(d["first_cell"])
    a, c = np.concatenate(areas), np.concatenate(cells)
    return {"layers": out, "target": target, "complete": complete, "first_cell_m": float(np.average(c, weights=a)),
            "share_over_2x": float(a[c > 2 * planned].sum() / a.sum())}


def level_result(case: Path) -> dict:
    monitor = ReportMonitor(case)
    monitor.poll()
    uref = window_stats(monitor.series(f"probe:{bc.REF_PROBE[0]}:Ux"), WINDOW).mean
    data = wall_data(case, ("lower", "floor"))
    q = 0.5 * uref ** 2  # kinematic dynamic pressure (p and tau are kinematic)
    cf = data["tau_x"] * -1.0 / q  # wallShearStress is the wall's stress on the fluid: tau_w = -tau (D-061)
    cp = data["p"] / q
    x = data["x"]
    floor = data["z"] < 0.5
    xr = reattachment(x[floor], cf[floor])
    cp40 = float(np.interp(40.0, x, cp))
    cps = cp - cp40
    near = floor & (x < 10)
    sign = np.sign(cf[floor])
    out = {"uref": uref, "re_h": uref * bc.H / bc.NU, "time": data["time"], "xr": xr,
           "cf_at_minus4": float(np.interp(-3.956, x, cf)), "cp_shift": cp40,
           "sign_changes": [float(v) for v in x[floor][:-1][sign[:-1] != sign[1:]] if v < 25.0][:6],
           "cf_min": float(cf[near].min()), "x_cf_min": float(x[near][np.argmin(cf[near])]),
           "cf_at_20": float(np.interp(20.0, x, cf)),
           "cp_min": float(cps[floor & (x < 6)].min()), "x_cp_min": float(x[floor & (x < 6)][np.argmin(cps[floor & (x < 6)])]),
           "cp_max": float(cps[floor & (x > 4) & (x < 20)].max()),
           "x_cp_max": float(x[floor & (x > 4) & (x < 20)][np.argmax(cps[floor & (x > 4) & (x < 20)])]),
           "cp_at_minus4": float(np.interp(-4.0, x, cps))}
    exp_cf, exp_cp = read_exp("cf.exp.dat"), read_exp("cp.expnew.dat", "bottom wall")
    out["vs_experiment"] = {
        "cf": [[float(xe), float(ce), float(np.interp(xe, x, cf))] for xe, ce, _err in exp_cf],
        "cp": [[float(xe), float(ce), float(np.interp(xe, x, cps))] for xe, ce, _orig in exp_cp],
    }
    out["profile"] = {"x": x.tolist(), "cf": cf.tolist(), "cp": cps.tolist()}
    return out


def read_exp(name: str, zone: str | None = None) -> np.ndarray:
    """The rows of a TMR data file in docs/validation/bfs/data/ (only ``zone``'s, when the file has zones)."""
    rows, current = [], None
    for line in (OUT / "data" / name).read_text().splitlines():
        if line.lower().startswith("zone"):
            current = line.split('"')[1] if '"' in line else line
            continue
        if zone is not None and current != zone:
            continue
        try:
            rows.append([float(v) for v in line.split()])
        except ValueError:
            continue
    return np.array(rows)


def cmd_collect(_args) -> None:
    project = Project.open(PROJECT)
    study_dir = PROJECT.parent / "case_study"
    record = read_record(study_dir)
    levels = []
    for lv in record.levels:
        case = level_dir(study_dir, lv.index)
        row = {"level": lv.name, "cells": lv.cells, "h": lv.h, "state": lv.state_label, "iterations": lv.iterations,
               "duration_s": lv.duration_s, "first_cell_m": lv.first_cell_m,
               "share_over_2x": lv.first_cell_share_over_2x, "error": lv.error}
        if lv.error is None and lv.iterations:
            row.update(level_result(case))
            row["walls"] = wall_layers(case, lv.planned_layers[0], int(lv.planned_layers[1]))
        levels.append(row)
    counted = [r for r in levels if r.get("xr") is not None and r["walls"]["complete"]]  # valid levels only
    gci = None
    if len(counted) == 3:
        g = gci_study([r["xr"] for r in counted], [r["h"] for r in counted])
        gci = {"convergence": g.convergence, "order": g.order, "extrapolated": g.extrapolated,
               "gci_fine": g.gci_fine, "gci_medium": g.gci_medium, "asymptotic_ratio": g.asymptotic_ratio, "text": g.text}
    OUT.mkdir(parents=True, exist_ok=True)
    profiles = {r["level"]: r.pop("profile") for r in levels if "profile" in r}
    (OUT / f"result{SUFFIX}.json").write_text(json.dumps({"levels": levels, "gci_xr": gci, "experiment_xr": bc.EXPERIMENT_XR,
                                                 "tmr_sst_xr": bc.TMR_SST_XR}, indent=2, default=float) + "\n")
    for name, prof in profiles.items():
        with open(OUT / f"wall_{name}{SUFFIX}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["x_over_H", "Cf", "Cp_shifted"])
            for x, cf, cp in zip(prof["x"], prof["cf"], prof["cp"]):
                if -6.0 <= x <= 45.0:
                    w.writerow([f"{x:.5f}", f"{cf:.6e}", f"{cp:.6e}"])
    for r in levels:
        say(f"{r['level']}: {r['cells']} cells, h {r['h']}, x_r {r.get('xr')}, U_ref {r.get('uref')}, Re_H {r.get('re_h')}, "
            f"Cf(-4) {r.get('cf_at_minus4')}, {r['state']}")
    say(f"GCI x_r: {gci}")


def boundary_layer(case: Path, time_name: str, x0: float = -4.0) -> dict:
    """delta_99 above the lower wall (z = 1) at ``x0``: the height where Ux first reaches 0.99 of the centre-channel
    value (z = 5), from the cell centres within 0.08 H of x0 (linear between cells), and the centre-channel Ux."""
    foam = case / "case.foam"
    foam.touch()
    reader = pv.OpenFOAMReader(str(foam))
    reader.set_active_time_value(float(time_name))
    mesh = reader.read()["internalMesh"]
    centres = mesh.cell_centers().points
    ux = np.asarray(mesh.cell_data["U"])[:, 0]
    sel = np.abs(centres[:, 0] - x0) < 0.08
    z, u = centres[sel, 2], ux[sel]
    order = np.argsort(z)
    z, u = z[order], u[order]
    ue = float(np.interp(5.0, z, u))
    i = int(np.argmax(u >= 0.99 * ue))
    z99 = float(np.interp(0.99 * ue, u[i - 1:i + 1], z[i - 1:i + 1])) if i > 0 else float(z[i])
    return {"delta99_H": z99 - 1.0, "u_centre": ue}


def cmd_calibrate(args) -> None:
    """One single mesh at the 0.129 H surface cell (round 1's preset fine level) with the inlet at ``--x-inlet``:
    delta_99 and Cf at x/H = -4 (QUESTIONS 209 a)."""
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.solver_run import SolverRun

    folder = ROOT / "run" / "validation" / "bfs_cal" / f"x{-args.x_inlet:g}"
    if folder.exists():
        shutil.rmtree(folder)
    project = bc.build_project(folder, {"base_size": 0.1289}, x_inlet=args.x_inlet)
    project.update_solver(cores=bc.CORES)
    job = meshing.prepare_job(project)
    first = (job.inputs.first_layer_thickness, job.inputs.layer_count or 1)
    run = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=first, cores=job.cores,
                  walls=internal.wall_patches(project))
    run.start()
    meshed = run.wait()
    if not meshed.success:
        raise SystemExit(f"meshing failed: {meshed.failed_step}")
    case = solving.prepare_solver_case(project)
    solver = SolverRun(case, cores=bc.CORES, stopping=project.sim.solvers.stopping, timeout_s=3600)
    solver.start()
    result = solver.wait()
    data = wall_data(case, ("lower", "floor"))
    monitor = ReportMonitor(case)
    monitor.poll()
    uref = window_stats(monitor.series(f"probe:{bc.REF_PROBE[0]}:Ux"), WINDOW).mean
    cf = -data["tau_x"] / (0.5 * uref ** 2)
    floor = data["z"] < 0.5
    out = {"x_inlet": args.x_inlet, "cells": meshed.report.cells, "state": result.state, "iterations": result.iterations,
           "uref": uref, "cf_minus4": float(np.interp(-3.956, data["x"], cf)), "xr": reattachment(data["x"][floor], cf[floor]),
           **boundary_layer(case, data["time"])}
    say(json.dumps(out))
    with open(WORK.parent / "bfs_calibration.jsonl", "a") as fh:
        fh.write(json.dumps(out) + "\n")


def cmd_plot(_args) -> None:
    """docs/validation/bfs/cf_cp.png: Cf and Cp along the bottom wall of every level of both families against
    Driver & Seegmiller (TMR data files)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_cf, ax_cp) = plt.subplots(1, 2, figsize=(12, 4.5))
    for suffix, family in (("", "r1 preset family"), ("_finefamily", "r1 finer family"), ("_round2", "r2 (inlet at -131 H)")):
        for name, style in (("coarse", ":"), ("medium", "--"), ("fine", "-")):
            path = OUT / f"wall_{name}{suffix}.csv"
            if not path.is_file():
                continue
            rows = np.loadtxt(path, delimiter=",", skiprows=1)
            floor = rows[:, 0] > 0.001
            label = f"{family}, {name}"
            ax_cf.plot(rows[:, 0], rows[:, 1], style, lw=1.2, label=label)
            ax_cp.plot(rows[:, 0], rows[:, 2], style, lw=1.2, label=label)
            del floor
    cf, cp = read_exp("cf.exp.dat"), read_exp("cp.expnew.dat", "bottom wall")
    ax_cf.errorbar(cf[:, 0], cf[:, 1], yerr=cf[:, 2], fmt="ks", ms=4, label="Driver & Seegmiller")
    ax_cp.plot(cp[:, 0], cp[:, 1], "ks", ms=4, label="Driver & Seegmiller (shifted)")
    for ax, name in ((ax_cf, "Cf"), (ax_cp, "Cp (0 at x/H = 40)")):
        ax.set_xlim(-6, 36)
        ax.set_xlabel("x/H")
        ax.set_ylabel(name)
        ax.grid(alpha=0.3)
    ax_cf.axhline(0.0, color="k", lw=0.6)
    ax_cf.set_ylim(-0.002, 0.004)
    ax_cf.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "cf_cp.png", dpi=110)
    say(f"wrote {OUT / 'cf_cp.png'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("setup", "study", "collect", "plot", "calibrate"))
    parser.add_argument("--x-inlet", type=float, default=bc.X_INLET_ROUND2)
    parser.add_argument("--level", choices=("coarse", "medium", "fine"))
    parser.add_argument("--family", choices=tuple(FAMILIES), default="preset")
    args = parser.parse_args()
    select(args.family)
    {"setup": cmd_setup, "study": cmd_study, "collect": cmd_collect, "plot": cmd_plot,
     "calibrate": cmd_calibrate}[args.command](args)


if __name__ == "__main__":
    main()
