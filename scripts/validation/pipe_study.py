"""Turbulent smooth-pipe validation (task w3-internal, Part B; docs/validation/pipe/SETUP.md): the case of
tests/validation/pipe_case.py run through the app's workflow layer as Generate Mesh then Run Solver would (single
level: the mesh study is not run, QUESTIONS 204), then the same mesh with a total-pressure inlet.

    nice -n 15 .venv/bin/python scripts/validation/pipe_study.py setup     # project, estimate
    nice -n 15 .venv/bin/python scripts/validation/pipe_study.py run       # mesh and solve (mass-flow inlet)
    nice -n 15 .venv/bin/python scripts/validation/pipe_study.py total     # total-pressure inlet on the same mesh
    nice -n 15 .venv/bin/python scripts/validation/pipe_study.py collect   # -> docs/validation/pipe/result.json

Projects in run/validation/pipe/ (git-ignored).
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import pipe_case as pc  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402

apply_display_guard()

from vortexcfd.core.project import Project  # noqa: E402
from vortexcfd.foam.convergence import window_stats  # noqa: E402
from vortexcfd.foam.mesh_record import MeshRecord, read_mesh_record, write_mesh_record  # noqa: E402
from vortexcfd.foam.mesh_run import MeshRun  # noqa: E402
from vortexcfd.foam.postprocessing import ReportMonitor  # noqa: E402
from vortexcfd.foam.run_record import read_run_record  # noqa: E402
from vortexcfd.foam.solver_run import SolverRun  # noqa: E402
from vortexcfd.foam.results import latest_result_time  # noqa: E402
from vortexcfd.foam.wall_fields import wall_face_values, yplus_histogram  # noqa: E402
from vortexcfd.workflow import internal, meshing, solving  # noqa: E402

WORK = ROOT / "run" / "validation" / "pipe"
OUT = ROOT / "docs" / "validation" / "pipe"
MAIN = WORK / "massflow"
TOTAL = WORK / "total_pressure"
WINDOW = 200  # iterations of the reported means


def say(text: str) -> None:
    print(f"[pipe {time.strftime('%H:%M:%S')}] {text}", flush=True)


def project_file(folder: Path) -> Path:
    return folder / "pipe" / "pipe.vcfd"


def mesh(project: Project) -> dict:
    job = meshing.prepare_job(project)
    t0 = time.monotonic()
    first = (job.inputs.first_layer_thickness, job.inputs.layer_count or 1) if job.inputs.first_layer_thickness else None
    run = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=first, cores=job.cores,
                  walls=internal.wall_patches(project), step_timeout_s=3600)
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    if not result.success:
        raise SystemExit(f"meshing failed: {result.failed_step} {result.error}")
    report = result.report
    write_mesh_record(job.case_dir, MeshRecord(report, meshing.inputs_hash(project), job.inputs.patches, job.cores))
    say(f"mesh: {report.cells:,} cells in {seconds:.0f} s on {job.cores} cores, valid {report.valid}, "
        f"layers {[(c.patch, c.mesh_layers, c.thickness_percent) for c in report.layers]}, first cell "
        f"{report.first_cell}")
    return {"cells": report.cells, "valid": report.valid, "mesh_s": round(seconds, 1), "cores": job.cores,
            "estimate": {"base_m": job.inputs.estimate().base_size, "surface_m": job.inputs.estimate().surface_size}}


def solve(project: Project) -> dict:
    case = solving.prepare_solver_case(project)
    t0 = time.monotonic()
    run = SolverRun(case, cores=project.sim.solvers.cores, stopping=project.sim.solvers.stopping, timeout_s=3 * 3600)
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    say(f"solve: {result.state} after {result.iterations} iterations in {seconds:.0f} s")
    return {"state": result.state, "iterations": result.iterations, "solve_s": round(seconds, 1)}


def cmd_setup(_args) -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    project = pc.build_project(MAIN)
    box = meshing.loaded_parts(project)[0]
    est = meshing.estimate_with_volumes(project, box)
    plan = meshing.plan_layers_for(project, box)
    length = meshing.surface_length(project, box)
    say(f"surface length {length.describe()}; base {est.base_size * 1e3:.3g} mm, surface cell "
        f"{est.surface_size * 1e3:.3g} mm, levels {est.level_min}-{est.level_max}, {est.total_cells:,} background cells")
    say(f"layers: {plan.count} x first {plan.first * 1e3:.3g} mm at {plan.expansion:.3g} (y+ speed "
        f"{meshing.flow_speed(project):.4g} m/s); mesh cores {meshing.mesh_cores(project, box).used}")
    say(f"readiness: {meshing.readiness(project)}")


def cmd_run(_args) -> None:
    project = Project.open(project_file(MAIN))
    info = {"mesh": mesh(project)}
    info["solve"] = solve(project)
    (WORK / "massflow.json").write_text(json.dumps(info, indent=2) + "\n")


def cmd_total(_args) -> None:
    """The total-pressure inlet at the mass-weighted total pressure the mass-flow run had at its inlet (outlet 0 Pa),
    on a copy of the mass-flow run's mesh."""
    monitor = ReportMonitor(project_file(MAIN).parent / "case")
    monitor.poll()
    p0 = window_stats(monitor.series("flow:p0_mass:patch:inlet"), WINDOW).mean
    if TOTAL.exists():
        shutil.rmtree(TOTAL)
    project = pc.build_project(TOTAL, inlet={"kind": "total_pressure", "total_pressure": round(p0, 3)})
    source, target = project_file(MAIN).parent / "case", project_file(TOTAL).parent / "case"
    meshing.prepare_job(project)  # the same meshing inputs: the same dictionaries
    shutil.copytree(source / "constant" / "polyMesh", target / "constant" / "polyMesh")
    record = read_mesh_record(source)
    write_mesh_record(target, MeshRecord(record.report, meshing.inputs_hash(project), record.patches, record.cores))
    say(f"total-pressure inlet p0 = {p0:.3f} Pa (the mass-flow run's mass-averaged inlet total pressure)")
    info = {"p0_pa": round(p0, 3), "solve": solve(project)}
    (WORK / "total_pressure.json").write_text(json.dumps(info, indent=2) + "\n")


def summarise(folder: Path) -> dict:
    case = project_file(folder).parent / "case"
    monitor = ReportMonitor(case)
    monitor.poll()
    project = Project.open(project_file(folder))
    measures = internal.inlet_measures(project, meshing._body_parts(project)[1])["inlet"]
    outlet = window_stats(monitor.series("flow:mdot:patch:outlet"), WINDOW).mean
    u_bulk = outlet / (pc.RHO * measures.area)  # the run's own flow through the polygonal pipe, and its D_h
    out: dict = {"drops_pa": {}, "friction": {}, "friction_nominal": {},
                 "geometry": {"area_m2": measures.area, "hydraulic_diameter_m": measures.hydraulic_diameter,
                              "u_bulk_m_s": u_bulk, "re": u_bulk * measures.hydraulic_diameter / pc.NU}}
    for name, (a, b) in pc.DROPS.items():
        stats = window_stats(monitor.series(f"dp:{name}:static"), WINDOW)
        out["drops_pa"][name] = {"mean": stats.mean, "spread": stats.spread, "n": stats.n}
        out["friction"][name] = pc.friction_factor(stats.mean, (b - a) * pc.D, u=u_bulk, d=measures.hydraulic_diameter)
        out["friction_nominal"][name] = pc.friction_factor(stats.mean, (b - a) * pc.D)
    flows = {}
    for kind, name in monitor.internal_locations():
        stats = window_stats(monitor.series(f"flow:mdot:{kind}:{name}"), WINDOW)
        flows[f"{kind}:{name}"] = stats.mean
    out["mass_flow_kg_s"] = flows
    balance = monitor.mass_balance()
    out["mass_imbalance_percent"] = balance[2] if balance else None
    out["inlet_p0_mass_pa"] = window_stats(monitor.series("flow:p0_mass:patch:inlet"), WINDOW).mean
    out["inlet_p_area_pa"] = window_stats(monitor.series("flow:p_area:patch:inlet"), WINDOW).mean
    time_name = latest_result_time(case)
    values = wall_face_values(case / time_name / "yPlus", ("wall",)) if time_name else {}
    if values:
        v = values["wall"]
        out["yplus"] = {"time": time_name, "mean": float(v.mean()), "min": float(v.min()), "max": float(v.max()),
                        "fractions": yplus_histogram(v).fractions}
    record = read_run_record(case)
    out["run"] = {"state": record.state, "iterations": record.iterations} if record else None
    mesh_record = read_mesh_record(case)
    if mesh_record is not None:
        r = mesh_record.report
        out["mesh"] = {"cells": r.cells, "valid": r.valid, "max_non_ortho": r.max_non_orthogonality,
                       "layers": [(c.patch, c.mesh_layers, c.thickness_percent) for c in r.layers],
                       "first_cell_m": r.first_cell.mean_m if r.first_cell else None,
                       "first_cell_planned_m": r.first_cell.planned_m if r.first_cell else None,
                       "share_over_2x": r.first_cell.share_over_2x if r.first_cell else None}
    return out


def cmd_collect(_args) -> None:
    result = {"reference": {"re": pc.REYNOLDS, "prandtl_karman": pc.prandtl_karman(pc.REYNOLDS),
                            "colebrook_smooth": pc.colebrook_smooth(pc.REYNOLDS)},
              "massflow": summarise(MAIN)}
    for name in ("massflow", "total_pressure"):
        path = WORK / f"{name}.json"
        if path.is_file():
            result.setdefault(name, {})["timing"] = json.loads(path.read_text())
    if project_file(TOTAL).is_file():
        result["total_pressure"].update(summarise(TOTAL))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=float) + "\n")
    say(f"wrote {OUT / 'result.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("setup", "run", "total", "collect"))
    args = parser.parse_args()
    {"setup": cmd_setup, "run": cmd_run, "total": cmd_total, "collect": cmd_collect}[args.command](args)


if __name__ == "__main__":
    main()
