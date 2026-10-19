"""Run one benchmark case through the app's own pipeline (D-082). No Qt.

Project (New simulation defaults, "External flow" preset) -> geometry import (the STL import or
part_ops.cad_parts, as File > Import Geometry) -> the preset's box domain -> workflow/meshing.prepare_job
(the dictionaries the user gets) -> MeshRun (blockMesh, surfaceFeatureExtract, snappyHexMesh,
createPatch, checkMesh, the lost-part and domain guards) -> MeshReport; then the benchmark's own
read-only measurements and the indicative y+ run (workflow/solving.prepare_solver_case + SolverRun).

The only change to the generated case is output: ``writeFlags (layerFields)`` is appended to
system/snappyHexMeshDict so snappyHexMesh writes its layer fields. A second checkMesh writes the face
non-orthogonality field (it does not change the mesh).
"""

import resource
import shutil
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.bench import metrics
from vortexcfd.bench.cases import BenchCase
from vortexcfd.bench.geometries import ensure_geometry, sphere_reference
from vortexcfd.core.model import Simulation, StoppingCriteria
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.foam.parallel import physical_cores, recommended_cores
from vortexcfd.foam.runner import run_foam
from vortexcfd.foam.solver_run import SolverRun
from vortexcfd.geometry.cad import CAD_EXTENSIONS, read_cad, tessellate
from vortexcfd.workflow import meshing, part_ops, solving

EXTERNAL_FLOW = BUILTIN_PRESETS[0]
LAYER_FIELDS = ("nSurfaceLayers", "thickness", "thicknessFraction")
WRITE_LAYER_FIELDS = "\n// VortexCFD benchmark: write the layer fields (output only, D-082)\nwriteFlags ( layerFields );\n"
FACE_CHECK = ["checkMesh", "-writeAllSurfaceFields", "-writeFields", "(nonOrthoAngle)", "-constant", "-noZero"]
STEP_TIMEOUT_S = 1800.0
# Reference tessellation of a CAD file for the fidelity distance: this fraction of its diagonal
# (the app's default import uses 1e-3).
REFERENCE_DEFLECTION_FRACTION = 1e-5
REFERENCE_ANGLE_DEG = 2.0


def _log(msg: str) -> None:
    print(f"[bench {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _peak_child_mb() -> float:
    """Peak resident memory of the largest finished child process so far (MiB; Linux reports KiB)."""
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0


def new_project(case: BenchCase, work_root: Path) -> Project:
    """A fresh project <work_root>/<case>/ set up as the New simulation dialog does, plus the case's
    changes. An earlier benchmark project of the same name is removed (only if it is one)."""
    folder = work_root / case.name
    if folder.exists():
        if not (folder / f"{case.name}.vcfd").is_file():
            raise RuntimeError(f"{folder} exists and is not a benchmark project: not touching it")
        shutil.rmtree(folder)
    sim = apply_preset(Simulation(name=case.name), EXTERNAL_FLOW)
    data = sim.model_dump()
    data["mesh"].update(case.mesh)
    data["inflow"].update(case.inflow)
    data["domain"].update(case.domain)
    return Project.create(work_root, case.name, Simulation.model_validate(data))


def import_geometry(project: Project, source: Path, units: str) -> None:
    """Copy ``source`` into the project's geometry folder and add its part(s), as File > Import."""
    folder = project.folder / "geometry"
    dest = folder / source.name
    shutil.copy2(source, dest)
    if source.suffix.lower() in CAD_EXTENSIONS:
        parts = part_ops.cad_parts(project.folder, dest, None, "regions", set())
    else:
        from vortexcfd.core.model import Part

        parts = [Part(name=source.stem, source_file=f"geometry/{source.name}", units=units)]
    for part in parts:
        project.add_part(part)
    project.save()


def _read_patches(case_dir: Path, patches: tuple[str, ...], time_value: float | None, fields: tuple[str, ...]):
    """{patch: PolyData} of the wall patches at ``time_value`` (None: the first time) with ``fields``
    as cell data (one value per boundary face, in OpenFOAM's face order)."""
    reader = pv.POpenFOAMReader(str(case_dir / "case.foam")) if hasattr(pv, "POpenFOAMReader") else \
        pv.OpenFOAMReader(str(case_dir / "case.foam"))
    reader.cell_to_point_creation = False
    reader.skip_zero_time = False
    if time_value is not None:
        reader.set_active_time_value(time_value)
    for name in reader.patch_array_names:
        if name == "internalMesh":
            reader.disable_patch_array(name)
        else:
            reader.enable_patch_array(name)
    for name in reader.cell_array_names:
        if name in fields:
            reader.enable_cell_array(name)
        else:
            reader.disable_cell_array(name)
    data = reader.read()
    boundary = data["boundary"]
    out = {}
    for name in patches:
        block = boundary[name] if name in boundary.keys() else None
        if block is not None and block.n_cells:
            out[name] = block.compute_cell_sizes(length=False, area=True, volume=False)
    return out


def _cad_reference(path: Path):
    """A fine tessellation of a CAD file in metres, for the fidelity distance."""
    model = read_cad(path)
    mesh = tessellate(model, REFERENCE_DEFLECTION_FRACTION * model.diagonal, REFERENCE_ANGLE_DEG)
    mesh.cell_data.clear()
    return mesh.scale(1e-3 if model.units == "mm" else 1.0, inplace=False)


def _distance_to_surface(surface: pv.PolyData, points: np.ndarray) -> np.ndarray:
    _cells, closest = surface.find_closest_cell(points, return_closest_point=True)
    return np.linalg.norm(points - closest, axis=1)


def wall_measurements(case: BenchCase, case_dir: Path, patches: tuple[str, ...], target_layers: int,
                      source: Path) -> dict:
    """Layer coverage per patch and zone, and surface fidelity, from the layer fields at time 0."""
    blocks = _read_patches(case_dir, patches, 0.0, LAYER_FIELDS)
    per_patch, areas, centres, n, th, fr, points = {}, [], [], [], [], [], []
    for name, block in blocks.items():
        cd = block.cell_data
        if not all(f in cd for f in LAYER_FIELDS):
            continue
        row = [np.asarray(block.cell_data["Area"]), np.asarray(cd["nSurfaceLayers"]),
               np.asarray(cd["thickness"]), np.asarray(cd["thicknessFraction"])]
        per_patch[name] = metrics.layer_stats(*row, target_layers)
        areas.append(row[0]); n.append(row[1]); th.append(row[2]); fr.append(row[3])
        centres.append(np.asarray(block.cell_centers().points))
        points.append(np.asarray(block.points))
    out: dict = {"patches": per_patch, "zones": {}, "fields_found": bool(per_patch)}
    if per_patch:
        a, nl, t, f, c = (np.concatenate(x) for x in (areas, n, th, fr, centres))
        out["walls"] = metrics.layer_stats(a, nl, t, f, target_layers)
        for zone in case.zones:
            mask = metrics.zone_mask(c, zone.boxes, zone.segments, zone.width)
            out["zones"][zone.name] = {**metrics.layer_stats(a[mask], nl[mask], t[mask], f[mask], target_layers),
                                       "description": zone.description}
        out["low_coverage"] = metrics.low_coverage({**per_patch, **out["zones"]})
    wall_points = np.unique(np.concatenate(points), axis=0) if points else np.zeros((0, 3))
    if not points:  # no layer fields: the geometry is still there
        blocks = _read_patches(case_dir, patches, 0.0, ())
        wall_points = np.unique(np.concatenate([np.asarray(b.points) for b in blocks.values()]), axis=0) \
            if blocks else np.zeros((0, 3))
    ref = sphere_reference(case.geometry)
    if ref is not None:
        distances = metrics.sphere_distance(*ref)(wall_points)
    else:
        distances = _distance_to_surface(_cad_reference(source), wall_points)
    out["fidelity"] = metrics.fidelity(distances, case.reference_length)
    return out


def face_quality(case_dir: Path) -> dict:
    """Internal faces above 65 and 70 degrees of non-orthogonality, from checkMesh's face field."""
    log = case_dir / "logs" / "log.checkMesh.bench"
    code = run_foam(FACE_CHECK, case_dir, log)
    field = case_dir / "constant" / "face_nonOrthoAngle"
    if code != 0 or not field.is_file():
        return {"error": f"checkMesh -writeFields exit code {code}"}
    values = metrics.read_scalar_list_field(field.read_text(encoding="utf-8", errors="replace"))
    above = metrics.count_above(values, metrics.NON_ORTHO_THRESHOLDS)
    return {"faces_non_ortho_gt65": above["65"], "faces_non_ortho_gt70": above["70"],
            "internal_faces": int(values.size)}


def snappy_stages(log_dir: Path) -> dict:
    """snappyHexMesh's stage times; with seeded parts the castellation comes from the castellation-only
    run (log.snappyHexMesh.castellate) and the whole run is the sum of both runs (D-084)."""
    main, first = log_dir / "log.snappyHexMesh", log_dir / "log.snappyHexMesh.castellate"
    stages = metrics.snappy_stage_times(main.read_text(errors="replace")) if main.is_file() else {}
    if first.is_file() and stages:
        pre = metrics.snappy_stage_times(first.read_text(errors="replace"))
        stages["castellation"] = pre["castellation"]
        if pre["snappy_total"] is not None and stages["snappy_total"] is not None:
            stages["snappy_total"] += pre["snappy_total"]
    return stages


def run_mesh(project: Project) -> tuple:
    """Prepare and run the meshing case; returns (job, MeshRunResult, step durations)."""
    job = meshing.prepare_job(project)
    shm = job.case_dir / "system" / "snappyHexMeshDict"
    shm.write_text(shm.read_text(encoding="utf-8") + WRITE_LAYER_FIELDS, encoding="utf-8")
    steps: dict[str, float] = {}
    current: list = [None, 0.0]

    def on_step(name: str) -> None:
        now = time.monotonic()
        if current[0] is not None:
            steps[current[0]] = now - current[1]
        current[0], current[1] = name, now
        _log(f"  {name}")

    run = MeshRun(job.case_dir, on_step=on_step, parts=job.inputs.patches, step_timeout_s=STEP_TIMEOUT_S)
    start = time.monotonic()
    run.start()
    result = run.wait()
    end = time.monotonic()
    if current[0] is not None:
        steps[current[0]] = end - current[1]
    steps["mesh_total"] = end - start
    return job, result, steps


def run_yplus(project: Project, case: BenchCase, cells: int, patches: tuple[str, ...]) -> dict:
    """The indicative y+ run: the app's default physics, ``case.iterations`` iterations, no stopping
    criteria, the recommended cores; then the yPlus field on the walls."""
    cores = recommended_cores(cells, physical_cores())
    project.update_solver(iterations=case.iterations, write_interval=case.iterations, cores=cores,
                          stopping=StoppingCriteria(criteria=[]))
    case_dir = solving.prepare_solver_case(project)
    run = SolverRun(case_dir, cores=cores, stopping=project.sim.solvers.stopping, timeout_s=STEP_TIMEOUT_S)
    start = time.monotonic()
    run.start()
    result = run.wait()
    out = {"cores": cores, "iterations_asked": case.iterations, "state": result.state if result else None,
           "iterations": result.iterations if result else None, "time_s": time.monotonic() - start,
           "label": "indicative, not converged"}
    if result is None or result.iterations is None or result.iterations < 1:
        return out
    blocks = _read_patches(case_dir, patches, float(result.iterations), ("yPlus",))
    values, areas = [], []
    for block in blocks.values():
        if "yPlus" in block.cell_data:
            values.append(np.asarray(block.cell_data["yPlus"]))
            areas.append(np.asarray(block.cell_data["Area"]))
    if values:
        out.update(metrics.yplus_stats(np.concatenate(values), np.concatenate(areas),
                                       project.sim.mesh.target_yplus))
    return out


def run_case(case: BenchCase, work_root: Path, geometry_dir: Path, solve: bool = True) -> dict:
    """Mesh (and, with ``solve``, the y+ run) one case; every result is a plain dict for the JSON."""
    t0 = time.monotonic()
    source = ensure_geometry(case.geometry, geometry_dir)
    project = new_project(case, work_root)
    import_geometry(project, source, case.units)
    out: dict = {"case": case.name, "description": case.description, "reference_length": case.reference_length}
    reason = meshing.readiness(project)
    if reason is not None:
        out.update(failed=True, failure=f"not ready: {reason}")
        return out
    box, _names, _bounds = meshing.parts_layout(project)
    est = meshing.estimate_for(box, project.sim.mesh)
    out["app_reference_length"] = box.reference_length
    out["estimate"] = {"base_size": est.base_size, "level_min": est.level_min, "level_max": est.level_max,
                       "surface_size": est.surface_size, "background_cells": est.total_cells}
    _log(f"{case.name}: meshing")
    job, result, steps = run_mesh(project)
    out["mesh_peak_mb"] = _peak_child_mb()
    report = result.report if result else None
    stages = snappy_stages(job.case_dir / "logs")
    out["time_s"] = {**{k: v for k, v in stages.items()}, "steps": steps, "mesh_total": steps.get("mesh_total")}
    out["mesh_success"] = bool(result and result.success)
    out["failed_step"] = result.failed_step if result else "not run"
    if report is None:
        out.update(failed=True, failure=f"meshing failed at {out['failed_step']}")
        out["time_s"]["case_total"] = time.monotonic() - t0
        return out
    check_log = job.case_dir / "logs" / "log.checkMesh"
    quality = metrics.parse_check_mesh_quality(check_log.read_text(errors="replace"))
    target_layers = job.inputs.layer_count if job.inputs.layer_count is not None else project.sim.mesh.layers
    out["cells"] = report.cells
    out["quality"] = {**quality, **face_quality(job.case_dir)}
    out["robustness"] = {"valid": report.valid, "mesh_ok": report.mesh_ok, "lost_parts": list(report.lost_parts),
                         "domain_errors": list(report.domain_errors)}
    out["snappy_layer_table"] = [asdict(c) for c in report.layers]
    out["extruded_percent"] = report.extruded_percent
    _log(f"{case.name}: {report.summary()}")
    out["layers"] = wall_measurements(case, job.case_dir, job.inputs.patches, target_layers, source)
    out["failed"] = not report.valid
    if solve and report.valid:
        _log(f"{case.name}: indicative y+ run ({case.iterations} iterations)")
        out["yplus"] = run_yplus(project, case, report.cells or 0, job.inputs.patches)
        out["solve_peak_mb"] = _peak_child_mb()
    out["time_s"]["case_total"] = time.monotonic() - t0
    return out
