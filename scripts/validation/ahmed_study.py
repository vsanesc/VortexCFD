"""Ahmed body 25 degree validation (task validation-ahmed): the case set up through the app's workflow
layer and the three-level mesh study run as the GUI's Mesh Study node runs it.

    .venv/bin/python scripts/validation/ahmed_study.py setup   # project, volumes, surface preparation, plan
    .venv/bin/python scripts/validation/ahmed_study.py study   # mesh and solve the three levels
    .venv/bin/python scripts/validation/ahmed_study.py collect # per-level numbers -> result.json

Round 2 (SETUP.md, "Round 2"): ``--round 2`` before the command; its project is ahmed25_r2 next to round
1's, and ``study`` runs one level per command, refusing to start when the level's estimated end (the solver
rate measured on this round's levels at the same core count, else round 1's) is after ``--deadline`` and
stopping it cleanly at the deadline (the app's stop: the solver's clean stop, D-058; the meshing stop, D-111):

    .venv/bin/python scripts/validation/ahmed_study.py --round 2 setup
    .venv/bin/python scripts/validation/ahmed_study.py --round 2 study --level coarse --deadline 23:15
    .venv/bin/python scripts/validation/ahmed_study.py --round 2 collect   # -> result_round2.json

Round 3 (SETUP.md, "The separating run"): round 2 without the ground layers, project ahmed25_r2_nolayers,
the coarse level only (``--round 3 setup``, ``--round 3 study --level coarse``, ``--round 3 collect`` ->
result_round3.json).

Round 4 (SETUP.md, "Round 4"): round 2 with the body and the stilts wall-resolved (target y+ 1 at the first
cell centre), the ground keeping round 2's stack, the safety cap 3000; project ahmed25_r4_wallres, the medium
and fine levels (``--round 4 setup``, ``--round 4 study --level medium --deadline HH:MM``, ``--round 4
collect`` -> result_round4.json). Its solver estimate falls back to round 2's measured rates (8 ranks).

Run with nice -n 15. The project goes to run/validation/ahmed/ (git-ignored); the numbers to
docs/validation/ahmed/result.json (round 2: result_round2.json; RESULT.md is written from them).
"""

import argparse
import dataclasses
import datetime
import json
import shutil
import threading
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.validation import ahmed_case as ac  # noqa: E402
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402
from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

apply_display_guard()
isolate_settings()  # never the user's settings or Recent list (D-141)

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


ROUND = 1  # set from --round


def project_path() -> Path:
    name = ac.project_name(ROUND)
    return WORK / name / f"{name}.vcfd"


def setup(args) -> None:
    start = time.monotonic()
    project = ac.build_project(WORK, WORK / "geometry_src", ROUND)
    box, names, meshes = meshing.loaded_parts(project)
    est = meshing.project_estimate(project, box)
    bounds = [tuple(float(b) for b in m.bounds) for m in meshes]
    project.update_mesh(target_surface_size=args.surface_size, background_cells_target=args.background)
    if ROUND >= 2:  # round 1's level sizes in the longer domain (SETUP.md, "Round 2")
        project.update_mesh(base_size=ac.BASE_SIZE_ROUND1)
    est = meshing.project_estimate(project, box)
    project.add_refinement_volume(refinement.wake_volume(project, [names.index(ac.BODY)], bounds, est))
    project.add_refinement_volume(RefinementVolume(id="new", name="slant", shape=slant_box(),
                                                   target_size=est.surface_size))
    prep = surface_prep.prepare(project, "intersection_features")  # the stilts cross the body
    project.set_surface_prep(prep)
    project.update_study("mesh", ratio=ac.STUDY_RATIO, current_as="fine", quantities=ac.STUDY_QUANTITIES,
                         cores=ac.SOLVER_CORES if ROUND == 1 else ac.CORES_R2)
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
    from vortexcfd.workflow.mesh_study import plan_study, study_dir_for

    sp = plan_study(project)
    measured = round_measured(project) if ROUND >= 2 else {}
    if ROUND >= 2:
        from vortexcfd.foam.mesh_case import ground_split_x

        print(f"ground wall start asked {ac.GROUND_WALL_START:.4f} m")
    if ROUND == 4:
        stack = ground_stack_round4(project)
        print(f"ground keeps round 2's stack: {stack.count} x first {stack.first * 1000:.4f} mm, ratio "
              f"{stack.expansion:.3f}; body and stilts: {sp.layers.count} x first {sp.layers.first * 1000:.4f} mm, "
              f"ratio {sp.layers.expansion:.3f}")
    for lp in sp.levels:
        print(f"level {lp.level.name}: factor {lp.level.factor:.3f}, base {lp.estimate.base_size * 1000:.1f} mm, "
              f"background {lp.estimate.total_cells}, "
              f"estimated cells {lp.estimated_cells} ({'measured ratio' if sp.measured else 'assumed ratio'} "
              f"{sp.cells_per_background:.2f})")
        if ROUND >= 2:
            mesh_s, solve_s, source = ac.estimate_level(lp.level.name, lp.estimated_cells, ac.iterations(ROUND),
                                                        measured)
            from vortexcfd.workflow.mesh_study import prepare_study  # noqa: F401 (the split is per level)

            inp = meshing.mesh_inputs(project)[0]
            inp = dataclasses.replace(inp, mesh=lp.level.mesh)
            print(f"  ground wall starts at x = {ground_split_x(inp):.4f} m on this level; estimate ({ac.iterations(ROUND)} "
                  f"iterations, solver rate {source}): meshing {mesh_s / 60:.1f} min, solver {solve_s / 60:.1f} min")


def ground_stack_round4(project: Project):
    """Round 4: round 2's shared layer stack (target y+ GROUND_TARGET_YPLUS_R4 at the first cell centre, the
    fine settings' surface size), which the ground keeps: a LayerStack (first, count, expansion). The project
    is changed in memory only."""
    from vortexcfd.workflow.mesh_study import plan_study

    copy = Project.open(project.path)
    copy.update_mesh(target_yplus=ac.GROUND_TARGET_YPLUS_R4)
    return plan_study(copy).layers


def override_ground_layers(project: Project, case: Path) -> str:
    """Round 4: give the ground of a prepared level case round 2's stack (its own per-patch entry)."""
    stack = ground_stack_round4(project)
    path = case / "system" / "snappyHexMeshDict"
    path.write_text(ac.ground_layer_override(path.read_text(encoding="utf-8"), stack.first, stack.count,
                                             stack.expansion, project.sim.mesh.min_thickness * stack.first),
                    encoding="utf-8")
    return f"ground layers {stack.count} x first {stack.first * 1000:.4f} mm, ratio {stack.expansion:.3f}"


def round_measured(project: Project) -> dict:
    """The measured solver rates of this round's levels; round 4 falls back to round 2's (same 8 ranks)."""
    from vortexcfd.workflow.mesh_study import study_dir_for

    cores = project.sim.studies.mesh.cores
    measured = ac.measured_rates(study_dir_for(project), cores)
    if not measured and ROUND == 4:
        print("solver rates: none measured on round 4 yet, round 2's levels used", flush=True)
        measured = ac.measured_rates(WORK / ac.PROJECT_NAME_R2 / "case_study", cores)
    return measured


def deadline_today(text: str) -> datetime.datetime:
    """HH:MM as the next such time: today, or tomorrow when it has passed (an overnight run)."""
    hours, minutes = (int(x) for x in text.split(":"))
    now = datetime.datetime.now()
    deadline = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return deadline + datetime.timedelta(days=1) if deadline <= now else deadline


def study(args) -> None:
    from vortexcfd.workflow.mesh_study import plan_study, prepare_study, solver_writer, study_dir_for
    from vortexcfd.foam.mesh_study import StudyRun

    project = Project.open(project_path())
    deadline = None
    if ROUND >= 2:
        if not args.level:
            raise SystemExit("round 2 runs one level per command: --level coarse|medium|fine")
        planned = {lp.level.name: lp.estimated_cells for lp in plan_study(project).levels}
        measured = round_measured(project)
        mesh_s, solve_s, source = ac.estimate_level(args.level, planned[args.level], ac.iterations(ROUND), measured)
        end = datetime.datetime.now() + datetime.timedelta(seconds=mesh_s + solve_s + 60)
        print(f"{args.level}: {planned[args.level]} cells estimated, meshing {mesh_s / 60:.1f} min, solver "
              f"{solve_s / 60:.1f} min ({ac.iterations(ROUND)} iterations, solver rate {source}): estimated end {end:%H:%M}",
              flush=True)
        if args.deadline:
            deadline = deadline_today(args.deadline)
            if end > deadline:
                raise SystemExit(f"not started: the estimated end {end:%H:%M} is after the deadline {deadline:%H:%M}")
        study_dir, record, inputs = prepare_study(project, only=[args.level])
        if ROUND == 4:
            from vortexcfd.foam.mesh_study import level_dir

            print(override_ground_layers(project, level_dir(study_dir, record.levels[0].index)), flush=True)
    else:
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
    stopped_at_deadline = threading.Event()
    if deadline is not None:  # the app's stop at the deadline: a clean solver stop, or the meshing stop
        def watchdog() -> None:
            while run.is_running():
                if datetime.datetime.now() >= deadline:
                    print(f"{time.strftime('%H:%M:%S')} deadline {deadline:%H:%M}: stopping the level", flush=True)
                    stopped_at_deadline.set()
                    run.request_stop()
                    return
                time.sleep(5)

        threading.Thread(target=watchdog, daemon=True).start()
    result = run.wait()
    log.close()
    suffix = f"_{args.level}" if ROUND >= 2 else ""
    (study_dir / f"study_events{suffix}.json").write_text(
        json.dumps({"start": start, "end": time.time(), "events": events,
                    "stopped_at_deadline": stopped_at_deadline.is_set()}, indent=1), encoding="utf-8")
    if ROUND >= 2:  # keep this level's record: the next level's run rewrites study.json
        shutil.copy(study_dir / "study.json", study_dir / f"study_{args.level}.json")
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


def wall_resolved_metrics(case_dir: Path, body, project: Project) -> dict:
    """Round 4: the body's y+ share below 2 at the first cell centre, the first-cell report of D-109 on the
    body and the stilts (foam/mesh_run.measure_first_cell, the walk the GUI's Mesh report uses), and the
    layer walk's coverage on the body (area share with at least one layer and with the full stack)."""
    import numpy as np

    from vortexcfd.foam import layer_walk
    from vortexcfd.foam.mesh_report import FIRST_CELL_DRIFT
    from vortexcfd.foam.mesh_run import measure_first_cell
    from vortexcfd.foam.polymesh import PolyMesh
    from vortexcfd.workflow.mesh_study import plan_study

    stack = plan_study(project).layers
    v, a = np.asarray(body.cell_data["yPlus"]), np.asarray(body.cell_data["Area"])
    out = {"planned_first_m": stack.first, "planned_count": stack.count, "planned_expansion": stack.expansion,
           "yplus_body_below_2_percent": 100.0 * float(a[v < 2.0].sum() / a.sum()),
           "yplus_body_below_5_percent": 100.0 * float(a[v < 5.0].sum() / a.sum()),
           "yplus_body_median": float(np.median(v))}
    for name, patches in (("body", (ac.BODY,)), ("stilts", (ac.STILT_FRONT, ac.STILT_REAR))):
        fc = measure_first_cell(case_dir, patches, stack.first, stack.count)
        out[f"first_cell_{name}"] = {"mean_m": fc.mean_m, "p95_m": fc.p95_m, "planned_m": fc.planned_m,
                                     "error": fc.error,
                                     "drift_warning": bool(fc.mean_m and fc.mean_m > FIRST_CELL_DRIFT * stack.first)}
    walked = layer_walk.walk_layers(PolyMesh.read(case_dir), (ac.BODY,), stack.count + 5)
    area = np.concatenate([d["area"] for d in walked.values()])
    layers = np.concatenate([d["layers"] for d in walked.values()])
    out["body_layer_walk"] = {"any_layer_area_percent": 100.0 * float(area[layers >= 1].sum() / area.sum()),
                              "full_stack_area_percent": 100.0 * float(area[layers >= stack.count].sum() / area.sum()),
                              "mean_layers": float((area * layers).sum() / area.sum())}
    return out


def level_metrics(case_dir: Path, level, project: Project, window: int = ac.AVERAGE_WINDOW) -> dict:
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
        if ROUND == 4:
            out["wall_resolved"] = wall_resolved_metrics(case_dir, body, project)
        out["window"] = window_stats(case_dir, ac.STUDY_QUANTITIES, window)
    return out


def collect_round2() -> None:
    """Round 2: the levels run so far (one record per level, study_<level>.json), each judged on the
    windowed means over the mean-stable criterion's window -> result_round2.json. No verdict until the
    three levels exist."""
    from vortexcfd.foam.mesh_study import LevelResult, StudyRecord

    project = Project.open(project_path())
    study_dir = project.folder / "case_study"
    window = ac.stopping_round2().criteria[0].window
    levels = []
    for name in ("coarse", "medium", "fine"):
        path = study_dir / f"study_{name}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        record = StudyRecord(levels=[LevelResult(**lv) for lv in data.pop("levels")], **data)
        level = record.levels[0]
        entry = level_metrics(study_dir / f"level_{level.index + 1}", level, project, window)
        events = json.loads((study_dir / f"study_events_{name}.json").read_text(encoding="utf-8"))
        starts = [t for t, text in events["events"] if text.startswith(f"Mesh study: meshing level {level.index + 1} ")]
        solves = [t for t, text in events["events"] if text.startswith(f"Mesh study: solving level {level.index + 1} ")]
        if starts and solves:
            entry["mesh_s"] = round(solves[0] - starts[0], 1)
        entry["stopped_at_deadline"] = events.get("stopped_at_deadline", False)
        entry["status"] = record.status
        levels.append(entry)
    result = {"project": str(project_path().relative_to(ROOT)), "average_window": window,
              "mesh_cores": ac.CORES_R2, "solver_cores": ac.CORES_R2, "ground_wall_start_asked": ac.GROUND_WALL_START,
              "iteration_cap": ac.iterations(ROUND), "levels": levels}
    if ROUND == 4 and levels:  # V6 on the finest level run (owner): no GCI with two levels
        cd = levels[-1]["window"]["Cd@body"]["mean"]
        error = cd / ac.CD_EXPERIMENT - 1.0
        consistent = ac.consistent_round4(cd)
        result["verdict"] = {"quantity": "Cd@body", "basis": levels[-1]["name"], "cd": cd,
                             "experiment": ac.CD_EXPERIMENT, "error": error,
                             "error_alt": cd / ac.CD_EXPERIMENT_ALT - 1.0,
                             "vs_guilmineau": cd / ac.CD_GUILMINEAU - 1.0,
                             "published_sst": list(ac.PUBLISHED_SST_VERIFIED.values()),
                             "consistent": consistent, "verdict": ac.verdict(error, consistent),
                             "stopped_at_deadline": levels[-1]["stopped_at_deadline"]}
    if [lv["name"] for lv in levels] == ["coarse", "medium", "fine"]:  # the GCI and V6, as round 1's collect
        from vortexcfd.foam import gci

        sizes = [lv["h_m"] for lv in levels]
        means = {}
        for q in ac.STUDY_QUANTITIES:
            values = [lv["window"][q]["mean"] for lv in levels]
            r = gci.study(values, sizes)
            means[q] = {"values": values, **dataclasses.asdict(r), "applicable": r.applicable,
                        "in_asymptotic_range": r.in_asymptotic_range, "text": r.text}
        result["gci_window_means"] = means
        cd, basis, _ = ac.judged_value([lv["window"]["Cd@body"]["mean"] for lv in levels], sizes)
        error = cd / ac.CD_EXPERIMENT - 1.0
        consistent = ac.consistent_with_sst(cd)
        result["verdict"] = {"quantity": "Cd@body", "basis": basis, "cd": cd, "experiment": ac.CD_EXPERIMENT,
                             "error": error, "error_alt": cd / ac.CD_EXPERIMENT_ALT - 1.0,
                             "published_sst": list(ac.PUBLISHED_SST_CD), "consistent_with_sst": consistent,
                             "verdict": ac.verdict(error, consistent),
                             "fine_stopped_at_deadline": levels[-1]["stopped_at_deadline"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"result_round{ROUND}.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=str)[:8000])


def collect(args) -> None:
    from vortexcfd.foam.mesh_study import quantity_rows, read_record

    if ROUND >= 2:
        collect_round2()
        return

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
    values = [lv["window"]["Cd@body"]["mean"] for lv in levels]
    cd, basis, _ = ac.judged_value(values, [lv["h_m"] for lv in levels])
    error = cd / ac.CD_EXPERIMENT - 1.0
    consistent = ac.consistent_with_sst(cd)
    result["verdict"] = {"quantity": "Cd@body", "basis": basis, "cd": cd, "experiment": ac.CD_EXPERIMENT,
                         "error": error, "error_alt": cd / ac.CD_EXPERIMENT_ALT - 1.0,
                         "published_sst": list(ac.PUBLISHED_SST_CD), "consistent_with_sst": consistent,
                         "verdict": ac.verdict(error, consistent)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=str)[:6000])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--round", type=int, choices=(1, 2, 3, 4), default=1,
                        help="1: the first study; 2: SETUP.md round 2; 3: round 2 without ground layers (QUESTIONS 177); "
                             "4: round 2 wall-resolved on the body and stilts")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--surface-size", type=float, default=ac.SURFACE_SIZE, help="target surface size (x l_ref)")
    s.add_argument("--background", type=int, default=ac.BACKGROUND_CELLS, help="background cell target")
    s.set_defaults(func=setup)
    s = sub.add_parser("study")
    s.add_argument("--levels", nargs="*", default=None, help="only these levels (coarse, medium, fine); round 1")
    s.add_argument("--level", choices=("coarse", "medium", "fine"), help="round 2: the one level to run")
    s.add_argument("--deadline", help="round 2: HH:MM today; not started if estimated to end later, stopped there")
    s.add_argument("--solver-timeout", type=float, default=3 * 3600)
    s.set_defaults(func=study)
    s = sub.add_parser("collect")
    s.set_defaults(func=collect)
    args = parser.parse_args()
    global ROUND
    ROUND = args.round
    args.func(args)


if __name__ == "__main__":
    main()
