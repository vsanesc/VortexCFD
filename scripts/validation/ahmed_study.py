"""Ahmed body 25 degree validation (task validation-ahmed): the case set up through the app's workflow
layer and the three-level mesh study run as the GUI's Mesh Study node runs it.

    .venv/bin/python scripts/validation/ahmed_study.py setup   # project, volumes, surface preparation, plan
    .venv/bin/python scripts/validation/ahmed_study.py study   # mesh and solve the three levels
    .venv/bin/python scripts/validation/ahmed_study.py collect # per-level numbers -> result.json

Run with nice -n 15. The project goes to run/validation/ahmed/ (git-ignored); the numbers to
docs/validation/ahmed/result.json (RESULT.md is written from them).
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import ahmed_case as ac  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402

apply_display_guard()

from vortexcfd.core.model import BoxShape, RefinementVolume  # noqa: E402
from vortexcfd.core.project import Project  # noqa: E402
from vortexcfd.workflow import meshing, refinement, surface_prep  # noqa: E402

WORK = ROOT / "run" / "validation" / "ahmed"
OUT = ROOT / "docs" / "validation" / "ahmed"

# The slant volume: the 25 degree slant and the rear edges, where the separation bubble and the
# C-pillar (side edge) vortices form (Ahmed et al. 1984, Figs. 6 and 9; SETUP.md): from 50 mm before the
# slant's leading edge to 100 mm behind the base, the half width plus 35 mm, from 50 mm below the base's
# top edge to 60 mm above the roof; target = the part surface cell size (the body's finest surface level).
SLANT_MARGIN_FRONT, SLANT_MARGIN_REAR, SLANT_MARGIN_SIDE = 0.05, 0.10, 0.035
SLANT_MARGIN_BELOW, SLANT_MARGIN_ABOVE = 0.05, 0.06


def slant_box() -> BoxShape:
    a = math.radians(25.0)
    x0 = ac.LENGTH - 0.222 * math.cos(a) - SLANT_MARGIN_FRONT
    x1 = ac.LENGTH + SLANT_MARGIN_REAR
    z_rear = ac.CLEARANCE + ac.HEIGHT - 0.222 * math.sin(a)
    z0, z1 = z_rear - SLANT_MARGIN_BELOW, ac.CLEARANCE + ac.HEIGHT + SLANT_MARGIN_ABOVE
    y1 = ac.WIDTH / 2 + SLANT_MARGIN_SIDE
    return BoxShape(centre=((x0 + x1) / 2, y1 / 2, (z0 + z1) / 2), size=(x1 - x0, y1, z1 - z0))


def project_path() -> Path:
    return WORK / ac.PROJECT_NAME / f"{ac.PROJECT_NAME}.vcfd"


def setup(args) -> None:
    start = time.monotonic()
    project = ac.build_project(WORK, WORK / "geometry_src")
    box, names, meshes = meshing.loaded_parts(project)
    est = meshing.project_estimate(project, box)
    bounds = [tuple(float(b) for b in m.bounds) for m in meshes]
    project.update_mesh(target_surface_size=args.surface_size, background_cells_target=args.background)
    est = meshing.project_estimate(project, box)
    project.add_refinement_volume(refinement.wake_volume(project, [names.index(ac.BODY)], bounds, est))
    project.add_refinement_volume(RefinementVolume(id="new", name="slant", shape=slant_box(),
                                                   target_size=est.surface_size))
    prep = surface_prep.prepare(project, "intersection_features")  # the stilts cross the body
    project.set_surface_prep(prep)
    project.update_study("mesh", ratio=ac.STUDY_RATIO, current_as="fine", quantities=ac.STUDY_QUANTITIES,
                         cores=ac.SOLVER_CORES)
    project.save()
    box, _, _ = meshing.loaded_parts(project)
    est = meshing.estimate_with_volumes(project, box)
    plan = meshing.plan_layers_for(project, box)
    infos = refinement.volume_infos(project, box, meshing.project_estimate(project, box))
    print(f"setup in {time.monotonic() - start:.0f} s: {project_path()}")
    print(f"domain {tuple(round(b, 4) for b in box.bounds)} roles {box.roles} L {box.reference_length:.4f}")
    print(f"base {est.base_size:.4f} m, background cells {est.total_cells}, levels {est.level_min}-{est.level_max}, "
          f"surface {est.surface_size * 1000:.2f} mm, curvature level {est.curvature_level} "
          f"({est.curvature_size * 1000:.2f} mm), volume cells {est.volume_cells}")
    for info in infos:
        print(f"volume {info.volume.name}: level {info.level}, size {info.achieved_size * 1000:.1f} mm, "
              f"+{info.extra_cells} cells")
    print(f"layers: {plan.count} x first {plan.first * 1000:.3f} mm, ratio {plan.expansion:.3f}, "
          f"total {plan.total * 1000:.1f} mm (planned {plan.planned_count})")
    print(f"surface preparation: {prep.strategy}, features {prep.features_file}, report {prep.report}")
    print(f"mesh cores {meshing.mesh_cores(project, box)}")
    from vortexcfd.workflow.mesh_study import plan_study

    sp = plan_study(project)
    for lp in sp.levels:
        print(f"level {lp.level.name}: factor {lp.level.factor:.3f}, background {lp.estimate.total_cells}, "
              f"estimated cells {lp.estimated_cells} ({'measured ratio' if sp.measured else 'assumed ratio'} "
              f"{sp.cells_per_background:.2f})")


def study(args) -> None:
    from vortexcfd.workflow.mesh_study import prepare_study, solver_writer
    from vortexcfd.foam.mesh_study import StudyRun

    project = Project.open(project_path())
    study_dir, record, inputs = prepare_study(project)
    if args.levels:
        record.levels = [lv for lv in record.levels if lv.name in args.levels]
    log = (study_dir / "study_console.log").open("a", encoding="utf-8")
    events = []

    def on_line(text: str) -> None:
        if text.startswith("Mesh study") or text.startswith("Meshing") or "Criteria met" in text:
            stamp = time.strftime("%H:%M:%S")
            events.append((time.time(), text.strip()))
            print(f"{stamp} {text.strip()}", flush=True)
        log.write(text)

    run = StudyRun(study_dir, record, solver_writer(project), stopping=project.sim.solvers.stopping.model_copy(deep=True),
                   parts=inputs.patches, on_line=on_line, solver_timeout_s=args.solver_timeout)
    start = time.time()
    run.start()
    result = run.wait()
    log.close()
    (study_dir / "study_events.json").write_text(json.dumps({"start": start, "end": time.time(), "events": events},
                                                            indent=1), encoding="utf-8")
    print(f"study {result.status} in {time.time() - start:.0f} s")


def slant_flow(case_dir: Path, time_value: float) -> dict:
    """The near-wall flow on the 25 degree slant at ``time_value`` from the wallShearStress field (D-061):
    Cf along the downslope direction (cos 25, 0, -sin 25) per slant face, positive where the near-wall
    flow runs down the slant (attached), negative where it runs up (reversed: separated). Reports the
    reversed share of the slant area and, on the strip within 30 mm of the plane of symmetry, the
    reversed share and the first and last reversed face along the slant (fraction of its length)."""
    import numpy as np

    from vortexcfd.bench.runner import _read_patches
    from vortexcfd.foam.wall_fields import skin_friction_along

    blocks = _read_patches(case_dir, (ac.BODY,), time_value, ("wallShearStress",))
    block = blocks[ac.BODY].compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=False)
    a = math.radians(25.0)
    normal = np.array([math.sin(a), 0.0, math.cos(a)])
    centres = np.asarray(block.cell_centers().points)
    on_slant = (np.abs(np.asarray(block.cell_data["Normals"]) @ normal) > 0.95) & \
               (centres[:, 0] > ac.LENGTH - 0.222 * math.cos(a)) & (centres[:, 2] > ac.CLEARANCE + 0.1)
    area = np.asarray(block.cell_data["Area"])[on_slant]
    cf = skin_friction_along(np.asarray(block.cell_data["wallShearStress"])[on_slant],
                             (math.cos(a), 0.0, -math.sin(a)), ac.SPEED)
    s = (centres[on_slant, 0] - (ac.LENGTH - 0.222 * math.cos(a))) / (0.222 * math.cos(a))
    strip = centres[on_slant, 1] < 0.03
    reversed_strip = s[strip & (cf < 0)]
    return {"faces": int(on_slant.sum()), "area_m2": float(area.sum()),
            "reversed_area_percent": 100.0 * float(area[cf < 0].sum() / area.sum()),
            "centre_strip_reversed_percent": 100.0 * float(area[strip & (cf < 0)].sum() / area[strip].sum()),
            "centre_strip_reversed_from": float(reversed_strip.min()) if reversed_strip.size else None,
            "centre_strip_reversed_to": float(reversed_strip.max()) if reversed_strip.size else None,
            "mean_cf_downslope": float((area * cf).sum() / area.sum())}


def window_stats(case_dir: Path, quantities: list[str], window: int) -> dict:
    """Mean, standard deviation and range of every quantity over the last ``window`` iterations (the
    report series of the app's ReportMonitor, D-060)."""
    import numpy as np

    from vortexcfd.foam.postprocessing import ReportMonitor

    monitor = ReportMonitor(case_dir)
    monitor.poll()
    out = {}
    for q in quantities:
        rows = monitor.series(q)
        values = np.array([v for _, v in rows[-window:]], dtype=float)
        out[q] = {"mean": float(values.mean()), "std": float(values.std()), "min": float(values.min()),
                  "max": float(values.max()), "n": int(values.size), "last": float(values[-1])}
    return out


def level_metrics(case_dir: Path, level, project: Project) -> dict:
    """The numbers RESULT.md reports for one level."""
    import numpy as np

    from vortexcfd.bench import metrics
    from vortexcfd.bench.runner import _read_patches
    from vortexcfd.foam.mesh_report import parse_check_mesh, parse_layer_table

    out = {"name": level.name, "factor": level.factor, "cells": level.cells, "h_m": level.h, "state": level.state,
           "state_label": level.state_label, "criteria_met": level.criteria_met, "iterations": level.iterations,
           "solver_s": level.duration_s, "values": level.values}
    logs = case_dir / "logs"
    rows, extruded = parse_layer_table((logs / "log.snappyHexMesh").read_text(encoding="utf-8"))
    out["layers"] = {"extruded_percent": extruded,
                     "patches": {r.patch: {"faces": r.faces, "mesh_layers": r.mesh_layers,
                                           "thickness_percent": r.thickness_percent} for r in rows}}
    check = parse_check_mesh((logs / "log.checkMesh").read_text(encoding="utf-8"))
    out["check"] = {"mesh_ok": check.mesh_ok, "failed_checks": check.failed_checks,
                    "max_non_orthogonality": check.max_non_orthogonality, "max_skewness": check.max_skewness}
    if level.iterations:
        t = float(level.iterations)
        blocks = _read_patches(case_dir, (ac.BODY, ac.STILT_FRONT, ac.STILT_REAR, "ground"), t, ("yPlus",))
        body = blocks[ac.BODY]
        out["yplus_body"] = metrics.yplus_stats(np.asarray(body.cell_data["yPlus"]), np.asarray(body.cell_data["Area"]),
                                                project.sim.mesh.target_yplus)
        ground = blocks["ground"]
        gv, ga = np.asarray(ground.cell_data["yPlus"]), np.asarray(ground.cell_data["Area"])
        near = np.asarray(ground.cell_centers().points)
        under = (near[:, 0] > -0.2) & (near[:, 0] < ac.LENGTH + 0.2) & (near[:, 1] < 0.3)
        out["yplus_ground"] = {"mean": float((ga * gv).sum() / ga.sum()), "max": float(gv.max()),
                               "mean_near_body": float((ga[under] * gv[under]).sum() / ga[under].sum())}
        out["slant"] = slant_flow(case_dir, t)
        out["window"] = window_stats(case_dir, ac.STUDY_QUANTITIES, ac.AVERAGE_WINDOW)
    return out


def collect(args) -> None:
    import dataclasses

    from vortexcfd.foam.mesh_study import quantity_rows, read_record

    project = Project.open(project_path())
    study_dir = project.folder / "case_study"
    record = read_record(study_dir)
    events = json.loads((study_dir / "study_events.json").read_text(encoding="utf-8"))
    levels = []
    for level in record.levels:
        entry = level_metrics(study_dir / f"level_{level.index + 1}", level, project)
        starts = [t for t, text in events["events"] if text.startswith(f"Mesh study: meshing level {level.index + 1} ")]
        solves = [t for t, text in events["events"] if text.startswith(f"Mesh study: solving level {level.index + 1} ")]
        if starts and solves:
            entry["mesh_s"] = round(solves[0] - starts[0], 1)
        levels.append(entry)
    rows = []
    for row in quantity_rows(record):
        entry = {"quantity": row.quantity, "sizes": row.sizes, "values": row.values, "reliable": row.reliable,
                 "note": row.note}
        if row.result is not None:
            entry.update(dataclasses.asdict(row.result), applicable=row.result.applicable,
                         in_asymptotic_range=row.result.in_asymptotic_range, text=row.result.text)
        rows.append(entry)
    from vortexcfd.foam import gci

    means = {}
    for q in ac.STUDY_QUANTITIES:  # the GCI on the windowed means (RESULT.md), same procedure as the study's
        values = [lv["window"][q]["mean"] for lv in levels]
        r = gci.study(values, [lv["h_m"] for lv in levels])
        means[q] = {"values": values, **dataclasses.asdict(r), "applicable": r.applicable,
                    "in_asymptotic_range": r.in_asymptotic_range, "text": r.text}
    result = {"project": str(project_path().relative_to(ROOT)), "average_window": ac.AVERAGE_WINDOW,
              "gci_window_means": means, "status": record.status, "ratio": record.ratio,
              "mesh_cores": record.mesh_cores, "solver_cores": record.cores, "domain_volume_m3": record.domain_volume,
              "study_wall_s": round(events["end"] - events["start"], 1), "levels": levels, "gci": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=str)[:6000])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--surface-size", type=float, default=ac.SURFACE_SIZE, help="target surface size (x l_ref)")
    s.add_argument("--background", type=int, default=ac.BACKGROUND_CELLS, help="background cell target")
    s.set_defaults(func=setup)
    s = sub.add_parser("study")
    s.add_argument("--levels", nargs="*", default=None, help="only these levels (coarse, medium, fine)")
    s.add_argument("--solver-timeout", type=float, default=3 * 3600)
    s.set_defaults(func=study)
    s = sub.add_parser("collect")
    s.set_defaults(func=collect)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
