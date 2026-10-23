"""Run one benchmark case through the app's own pipeline (D-082). No Qt.

Project (New simulation defaults, "External flow" preset) -> geometry import (the STL import or
part_ops.cad_parts, as File > Import Geometry) -> the preset's box domain -> workflow/meshing.prepare_job
(the dictionaries the user gets) -> MeshRun (blockMesh, surfaceFeatureExtract, snappyHexMesh,
createPatch, checkMesh, the lost-part and domain guards) -> MeshReport; then the benchmark's own
read-only measurements and the indicative y+ run (workflow/solving.prepare_solver_case + SolverRun).

The only change to the generated case is output: ``writeFlags (layerFields)`` is appended to
system/snappyHexMeshDict so snappyHexMesh writes its layer fields. A second checkMesh writes the face
non-orthogonality field (it does not change the mesh).

Evaluation switch (phase 5.3, D-102): with ``mesher="cfmesh"`` the same project is meshed by cfMesh's
cartesianMesh instead (workflow/cfmesh.prepare_cfmesh_job, the case the app would never write); every
measurement is the same, and the layers are also counted from the mesh itself (bench/layer_walk), for
both meshers, because cfMesh writes no layer fields.
"""

import os
import resource
import shutil
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.bench import layer_walk, metrics
from vortexcfd.bench import reference as reference_module
from vortexcfd.bench.cases import BenchCase
from vortexcfd.bench.geometries import ensure_geometry, sphere_reference
from vortexcfd.core.model import Simulation, StoppingCriteria
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.foam.cfmesh_case import cfmesh_commands
from vortexcfd.foam.mesh_report import check_class
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.foam.mesh_case import part_patch_names, safe_part_names
from vortexcfd.foam.polymesh import PolyMesh
from vortexcfd.foam.parallel import physical_cores, recommended_cores
from vortexcfd.foam.physics_case import control_dict
from vortexcfd.foam.postprocessing import patch_face_counts
from vortexcfd.foam.runner import run_foam
from vortexcfd.foam.solver_run import SolverRun
from vortexcfd.geometry.cad import CAD_EXTENSIONS, read_cad, tessellate
from vortexcfd.workflow import cfmesh, meshing, part_ops, solving, surface_prep

EXTERNAL_FLOW = BUILTIN_PRESETS[0]
LAYER_FIELDS = ("nSurfaceLayers", "thickness", "thicknessFraction")
WRITE_LAYER_FIELDS = "\n// VortexCFD benchmark: write the layer fields (output only, D-082)\nwriteFlags ( layerFields );\n"
FACE_CHECK = ["checkMesh", "-writeAllSurfaceFields", "-writeFields", "(nonOrthoAngle)", "-constant", "-noZero"]
STEP_TIMEOUT_S = 1800.0
# Reference tessellation of a CAD file for the fidelity distance: this fraction of its diagonal
# (the app's default import uses 1e-3).
REFERENCE_DEFLECTION_FRACTION = 1e-5
REFERENCE_ANGLE_DEG = 2.0


def import_summary(project: Project) -> dict:
    """What the import gave, per part: triangles, open and non-manifold edges, duplicate faces (the
    surface checks, without the self-intersection pass)."""
    from vortexcfd.geometry.checks import check_surface

    out = {}
    for part in project.sim.geometry.parts:
        mesh = part_ops.part_mesh(project, part)
        rep = check_surface(mesh, intersections=False)
        out[part.name] = {"triangles": rep.n_triangles, "open_edges": rep.open_edges,
                          "non_manifold_edges": rep.non_manifold_edges, "duplicate_faces": rep.duplicate_faces,
                          "watertight": rep.watertight, "bodies": part.cad.bodies if part.cad else None}
    return out


def _log(msg: str) -> None:
    print(f"[bench {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _peak_child_mb() -> float:
    """Peak resident memory of the largest finished child process so far (MiB; Linux reports KiB)."""
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0


def descendants_rss_mb(root: int | None = None, proc: Path = Path("/proc")) -> float:
    """Resident memory (MiB) of every live descendant of ``root`` (default: this process) together: the
    ranks of an mpirun run add up, which the per-process peak of getrusage does not show."""
    root = os.getpid() if root is None else root
    parent: dict[int, int] = {}
    rss: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rpartition(")")[2].split()
        except OSError:
            continue
        parent[int(entry.name)] = int(fields[1])  # after the command: state, ppid, ...
        rss[int(entry.name)] = int(fields[21])  # rss in pages (field 24 of proc(5))
    children: dict[int, list[int]] = {}
    for pid, ppid in parent.items():
        children.setdefault(ppid, []).append(pid)
    total, todo = 0, list(children.get(root, ()))
    while todo:
        pid = todo.pop()
        total += rss.get(pid, 0)
        todo.extend(children.get(pid, ()))
    return total * PAGE_BYTES / 2**20


PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")


class MemorySampler:
    """The peak of descendants_rss_mb, sampled every ``interval_s`` on a thread while in the ``with``."""

    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s, self.peak_mb = interval_s, 0.0
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._done.wait(self.interval_s):
            self.peak_mb = max(self.peak_mb, descendants_rss_mb())

    def __enter__(self) -> "MemorySampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._done.set()
        self._thread.join()


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
    data["reports"].update(case.reports)
    data["inflow"].update(case.inflow)
    data["domain"].update(case.domain)
    return Project.create(work_root, case.name, Simulation.model_validate(data))


def import_geometry(project: Project, source: Path, units: str, mode: str = "regions") -> None:
    """Copy ``source`` into the project's geometry folder and add its part(s), as File > Import
    (``mode``: the answer to its question for a file with several bodies, "regions" or "parts")."""
    folder = project.folder / "geometry"
    dest = folder / source.name
    shutil.copy2(source, dest)
    if source.suffix.lower() in CAD_EXTENSIONS:
        parts = part_ops.cad_parts(project.folder, dest, None, mode, set())
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
                      source: Path, fidelity: bool = True) -> dict:
    """Layer coverage per patch and zone, and surface fidelity (unless ``fidelity`` is False: local
    cases measure it against their reference instead), from the layer fields at time 0."""
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
    if not fidelity:
        return out
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


def _faces_padded(mesh: pv.PolyData) -> np.ndarray:
    """(n, k) point ids of every polygon of ``mesh``, -1 padded."""
    stream = np.asarray(mesh.faces)
    rows, i = [], 0
    while i < len(stream):
        n = int(stream[i])
        rows.append(stream[i + 1:i + 1 + n])
        i += n + 1
    width = max((len(r) for r in rows), default=3)
    out = np.full((len(rows), width), -1, dtype=np.int64)
    for k, r in enumerate(rows):
        out[k, :len(r)] = r
    return out


def reference_measurements(ref: "reference_module.ReferenceSurface", case_dir: Path, patches: tuple[str, ...],
                           zones) -> dict:
    """Fidelity against the reference's outer skin (D-094), overall and per zone: mesh wall points to
    the skin and skin points to the mesh walls (max and RMS in mm, share further than half the local
    surface cell size), and the wall surface left inside a component (points further than half a
    cell inside a reference solid; count and area)."""
    blocks = _read_patches(case_dir, patches, 0.0, ())
    if not blocks:
        return {"error": "no wall faces"}
    walls = pv.merge(list(blocks.values()), merge_points=True)
    points = np.asarray(walls.points, dtype=float)
    area = np.asarray(walls.cell_data["Area"], dtype=float)
    size = metrics.point_sizes(points, _faces_padded(walls), area)
    tri_walls = walls.triangulate()
    # mesh -> reference
    d_mesh = _distance_to_surface(ref.skin, points)
    # reference -> mesh: the skin's points; the local size is that of the nearest wall face
    skin_pts = np.asarray(ref.skin.points, dtype=float)
    cells, closest = tri_walls.find_closest_cell(skin_pts, return_closest_point=True)
    d_ref = np.linalg.norm(skin_pts - closest, axis=1)
    face_size = np.sqrt(np.asarray(tri_walls.cell_data["Area"], dtype=float))
    # the triangulated walls keep the polygon's area per triangle (cell data is copied)
    size_ref = face_size[np.asarray(cells, dtype=np.int64)]
    out = {"mesh_to_reference": metrics.reference_fidelity(d_mesh, size),
           "reference_to_mesh": metrics.reference_fidelity(d_ref, size_ref),
           "far_fraction_of_cell": metrics.FAR_FRACTION, "zones": {}}
    # wall surface left inside a component
    deep = d_mesh > metrics.FAR_FRACTION * size
    inside_pts = deep & ref.inside_any(points)
    centres = np.asarray(walls.cell_centers().points, dtype=float)
    d_centre = _distance_to_surface(ref.skin, centres)
    face_sizes = np.sqrt(area)
    inside_faces = (d_centre > metrics.FAR_FRACTION * face_sizes) & ref.inside_any(centres)
    out["internal"] = {"points": int(inside_pts.sum()), "faces": int(inside_faces.sum()),
                       "area_m2": float(area[inside_faces].sum()),
                       "area_percent": 100.0 * float(area[inside_faces].sum() / area.sum()) if area.sum() > 0 else None}
    for zone in zones:
        m_mesh = metrics.zone_mask(points, zone.boxes, zone.segments, zone.width)
        m_ref = metrics.zone_mask(skin_pts, zone.boxes, zone.segments, zone.width)
        m_face = metrics.zone_mask(centres, zone.boxes, zone.segments, zone.width)
        out["zones"][zone.name] = {
            "mesh_to_reference": metrics.reference_fidelity(d_mesh[m_mesh], size[m_mesh]),
            "reference_to_mesh": metrics.reference_fidelity(d_ref[m_ref], size_ref[m_ref]),
            "internal_area_m2": float(area[m_face & inside_faces].sum()),
        }
    return out


def force_partition_check(project: Project, case_dir: Path, patches: tuple[str, ...]) -> dict:
    """Per-part forces sum to the total, checked on the geometry (no solve): the app's own force
    function objects (physics_case.control_dict) per part against the all-walls object and the mesh's
    wall patches (metrics.force_partition)."""
    functions = control_dict(solving.solver_input(project)).content["functions"]
    total = tuple(functions["forces1"]["patches"])
    per_part = {}
    parts = project.sim.geometry.parts
    for part, key, names in zip(parts, safe_part_names([p.name for p in parts]), part_patch_names(parts)):
        key = f"forces_{key}"
        if len(names) > 1 and key in functions:
            per_part[part.name] = tuple(functions[key]["patches"])
        elif len(names) == 1 and f"forces_{names[0]}" in functions:
            per_part[part.name] = tuple(functions[f"forces_{names[0]}"]["patches"])
        else:  # a single wall patch: forces1 is the part's object
            per_part[part.name] = total if len(project.sim.geometry.parts) == 1 else tuple(names)
    counts = patch_face_counts(case_dir)
    blocks = _read_patches(case_dir, patches, 0.0, ())
    areas = {name: float(np.asarray(b.cell_data["Area"]).sum()) for name, b in blocks.items()}
    return metrics.force_partition(per_part, total, counts, areas)


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


# cfMesh's OpenMP threads follow the CPU affinity (benchmarks/RESULT_5.3.md, Part A): the evaluation pins
# cartesianMesh to one logical CPU of each of CFMESH_CORES physical cores (SMT siblings are adjacent on
# the development PC: CPUs 2k and 2k + 1 are core k).
CFMESH_CORES = 10


def cfmesh_cpus(cores: int = CFMESH_CORES) -> tuple[int, ...]:
    return tuple(range(0, 2 * cores, 2))


def run_mesh(project: Project, mesher: str = "snappy", mesh_cores: int = 1) -> tuple:
    """Prepare and run the meshing case; returns (job, MeshRunResult, step durations, notes).
    ``mesh_cores``: snappyHexMesh ranks (D-111; the benchmark meshes in serial unless asked). With
    cfMesh and a symmetry plane the run stops before checkMesh, the symmetry patch is made exactly
    planar (workflow/cfmesh.flatten_symmetry, its displacement in the notes) and checkMesh runs on that."""
    stages: list[tuple] = []
    notes: dict = {}
    if mesher == "cfmesh":
        job = cfmesh.prepare_cfmesh_job(project)
        commands = cfmesh_commands(job.inputs, cfmesh_cpus())
        if job.inputs.symmetric:
            stages = [commands[:-1], commands[-1:]]
        else:
            stages = [commands]
    else:
        job = meshing.prepare_job(project)
        shm = job.case_dir / "system" / "snappyHexMeshDict"
        shm.write_text(shm.read_text(encoding="utf-8") + WRITE_LAYER_FIELDS, encoding="utf-8")
        stages = [None]
    steps: dict[str, float] = {}
    current: list = [None, 0.0]

    def on_step(name: str) -> None:
        now = time.monotonic()
        if current[0] is not None:
            steps[current[0]] = now - current[1]
        current[0], current[1] = name, now
        _log(f"  {name}")

    start = time.monotonic()
    result = None
    for k, stage in enumerate(stages):
        if k > 0:  # between the cfMesh run and checkMesh: the symmetry plane
            if result is None or any(code != 0 for code in result.exit_codes.values()) or result.stopped:
                break
            on_step("flattenSymmetry")
            notes["symmetry_flattened"] = cfmesh.flatten_symmetry(job.case_dir, "symmetry", job.box.bounds[2])
        extra = {"steps": stage} if stage is not None else {}
        if mesher == "snappy":
            extra["cores"] = mesh_cores
        run = MeshRun(job.case_dir, on_step=on_step, parts=job.inputs.patches, step_timeout_s=STEP_TIMEOUT_S, **extra)
        run.start()
        result = run.wait()
    end = time.monotonic()
    if current[0] is not None:
        steps[current[0]] = end - current[1]
    steps["mesh_total"] = end - start
    return job, result, steps, notes


def planned_stack(inputs, plan=None) -> tuple[float | None, float | None]:
    """(first layer, total stack thickness) in metres of the planned y+ stack: the layer plan's planned
    total when ``plan`` (foam/yplus.LayerPlan) is given (with the layer cap it can be more than the stack
    written, D-106), else the stack written; None with relative sizing."""
    if inputs.fixed_layers is not None:
        first, count = inputs.fixed_layers
    elif inputs.first_layer_thickness is not None and inputs.layer_count is not None:
        first, count = inputs.first_layer_thickness, inputs.layer_count
    else:
        return None, None
    if plan is not None and plan.planned_total > 0:
        return first, plan.planned_total
    r = inputs.layer_expansion or inputs.mesh.expansion_ratio
    return first, (first * (r ** count - 1) / (r - 1) if r != 1 else first * count)


def walk_measurements(case: BenchCase, case_dir: Path, inputs, target_layers: int, plan=None) -> dict:
    """Layers counted from the mesh (bench/layer_walk), overall, per patch and per zone, in
    metrics.layer_stats form: the thickness is the stack's, its percentage is of the planned stack
    (planned_stack); plus the mean first-layer height of the faces with a layer against the planned
    first layer."""
    first_planned, total_planned = planned_stack(inputs, plan)
    t0 = time.monotonic()
    walked = layer_walk.walk_layers(PolyMesh.read(case_dir), inputs.patches, target_layers + 5)

    def stats(a, n, th, first, cell):
        frac = th / total_planned if total_planned else np.zeros_like(th)
        row = metrics.layer_stats(a, n, th, frac, target_layers)
        has = n > 0
        row["mean_first_layer_m"] = float((a[has] * first[has]).sum() / a[has].sum()) if has.any() else None
        row["first_cell"] = layer_walk.first_cell_stats(a, cell, n)  # every face, layered or not
        return row

    out: dict = {"method": "layer_walk", "max_aspect": layer_walk.MAX_ASPECT, "max_growth": layer_walk.MAX_GROWTH,
                 "planned_first_m": first_planned, "planned_total_m": total_planned, "patches": {}, "zones": {},
                 "written_total_m": planned_stack(inputs)[1]}
    if not walked:
        return out
    for name, d in walked.items():
        out["patches"][name] = stats(d["area"], d["layers"], d["thickness"], d["first"], d["first_cell"])
    a, n, th, first, cell, c = (np.concatenate([d[k] for d in walked.values()])
                                for k in ("area", "layers", "thickness", "first", "first_cell", "centre"))
    out["walls"] = stats(a, n, th, first, cell)
    for zone in case.zones:
        mask = metrics.zone_mask(c, zone.boxes, zone.segments, zone.width)
        out["zones"][zone.name] = {**stats(a[mask], n[mask], th[mask], first[mask], cell[mask]),
                                   "description": zone.description}
    out["time_s"] = time.monotonic() - t0
    return out


# The y+ runs use the recommended count for each mesh (cells / CELLS_PER_CORE) with a cap of
# YPLUS_MAX_CORES and never more than the physical cores minus YPLUS_FREE_CORES, not the app's
# efficiency cap of D-064 (D-092).
YPLUS_MAX_CORES = 10
YPLUS_FREE_CORES = 2


def yplus_cores(cells: int, physical: int) -> int:
    return recommended_cores(cells, physical, efficient=max(1, min(YPLUS_MAX_CORES, physical - YPLUS_FREE_CORES)))


def run_yplus(project: Project, case: BenchCase, cells: int, patches: tuple[str, ...]) -> dict:
    """The indicative y+ run: the app's default physics, ``case.iterations`` iterations, no stopping
    criteria, ``yplus_cores`` ranks (recorded); then the yPlus field on the walls."""
    cores = yplus_cores(cells, physical_cores())
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


def local_reference(case: BenchCase, cache: Path | None = None) -> tuple[BenchCase, "reference_module.ReferenceSurface", dict]:
    """The reference of a local case (D-094) and the case with its l_ref and zones set from it."""
    spec = case.reference_spec
    ref = reference_module.cached_reference(Path(case.reference), spec.get("components") or {}, spec.get("zones"),
                                            spec.get("l_ref"), cache)
    lref = ref.l_ref if ref.l_ref > 0 else None
    changed = replace(case, zones=ref.zones, reference_length=lref or 0.0,
                      reports={**case.reports, **({"reference_length": lref} if lref else {})})
    summary = {"file": Path(case.reference).name, "l_ref_m": lref, "l_ref_method": ref.l_ref_method,
               "skin_area_m2": float(ref.skin.area),
               "curves_m": {f"{_name(ref, i)}/{_name(ref, j)}": float(np.linalg.norm(s[:, 1] - s[:, 0], axis=1).sum())
                            for (i, j), s in ref.curves.items()},
               "zones": {z.name: z.description for z in ref.zones}, "notes": ref.notes}
    return changed, ref, summary


def _name(ref: "reference_module.ReferenceSurface", index: int) -> str:
    return next((n for n, k in ref.components.items() if k == index), str(index))


def run_case(case: BenchCase, work_root: Path, geometry_dir: Path, solve: bool = True, mesher: str = "snappy",
             mesh_cores: int = 1) -> dict:
    """Mesh (and, with ``solve``, the y+ run) one case; every result is a plain dict for the JSON.
    ``mesher`` "cfmesh" is the 5.3 evaluation switch (the project folder is <case>_cfmesh);
    ``mesh_cores`` the snappyHexMesh ranks (D-111, 1 by default for comparability with the baseline)."""
    t0 = time.monotonic()
    ref = None
    out: dict = {"case": case.name, "description": case.description, "mesher": mesher}
    if case.local:
        _log(f"{case.name}: reference analysis")
        case, ref, out["reference"] = local_reference(case, work_root / ".reference_cache")
        source = Path(case.source)
        solve = solve and case.solve
    else:
        source = ensure_geometry(case.geometry, geometry_dir)
    out["reference_length"] = case.reference_length
    if mesher == "cfmesh":
        case = replace(case, name=f"{case.name}_cfmesh")
        out["case"] = case.name
        out["cfmesh_cores"] = CFMESH_CORES
    project = new_project(case, work_root)
    t_import = time.monotonic()
    import_geometry(project, source, case.units, case.import_mode)
    out["import_time_s"] = time.monotonic() - t_import
    if case.local:
        out["import"] = import_summary(project)
        if case.surface_prep:  # Edit > Surface Preparation, as the GUI runs it (D-093)
            _log(f"{case.name}: surface preparation ({case.surface_prep})")
            try:
                prep = surface_prep.prepare(project, case.surface_prep)
            except Exception as exc:  # a failed preparation is a result
                out.update(failed=True, failure=f"surface preparation failed: {type(exc).__name__}: {exc}",
                           time_s={"case_total": time.monotonic() - t0})
                return out
            project.set_surface_prep(prep)
            project.save()
            out["surface_prep"] = {"strategy": prep.strategy, "time_s": prep.time_s, "report": prep.report,
                                   "parts": {p.part: {"strategy": p.strategy, "note": p.note} for p in prep.parts}}
    reason = meshing.readiness(project)
    if reason is not None:
        out.update(failed=True, failure=f"not ready: {reason}")
        return out
    box, _names, bounds = meshing.parts_layout(project)
    length = meshing.surface_length(project, box, bounds)
    est = meshing.estimate_for(box, project.sim.mesh, length.value)
    out["app_reference_length"] = box.reference_length
    out["estimate"] = {"base_size": est.base_size, "level_min": est.level_min, "level_max": est.level_max,
                       "surface_size": est.surface_size, "background_cells": est.total_cells,
                       "surface_length": length.value, "surface_length_source": length.source,
                       "curvature_level": est.curvature_level}
    _log(f"{case.name}: meshing" + (f" on {mesh_cores} cores" if mesh_cores > 1 else ""))
    with MemorySampler() as memory:
        job, result, steps, notes = run_mesh(project, mesher, mesh_cores)
    out.update(notes)
    out["mesh_cores"] = mesh_cores
    out["mesh_peak_mb"] = _peak_child_mb()
    out["mesh_peak_total_mb"] = memory.peak_mb  # all processes of the run together (sampled, D-111)
    report = result.report if result else None
    stages = snappy_stages(job.case_dir / "logs")
    snappy_log = job.case_dir / "logs" / "log.snappyHexMesh"
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
    soft = [line for line in report.failed_check_lines if check_class(line) == "soft"]
    out["checks"] = {"hard": len(report.hard_failures), "soft": len(soft),  # D-100 classes
                     "hard_lines": list(report.hard_failures), "soft_lines": soft}
    out["robustness"] = {"valid": report.valid, "mesh_ok": report.mesh_ok, "lost_parts": list(report.lost_parts),
                         "domain_errors": list(report.domain_errors)}
    out["snappy_layer_table"] = [asdict(c) for c in report.layers]
    out["extruded_percent"] = report.extruded_percent
    _log(f"{case.name}: {report.summary()}")
    out["layers"] = wall_measurements(case, job.case_dir, job.inputs.patches, target_layers, source,
                                      fidelity=ref is None)
    if ref is not None:
        _log(f"{case.name}: fidelity against the reference")
        out["reference_fidelity"] = reference_measurements(ref, job.case_dir, job.inputs.patches, case.zones)
        counts = patch_face_counts(job.case_dir)
        out["patch_faces"] = {p: counts.get(p, 0) for p in job.inputs.patches}
        out["force_partition"] = force_partition_check(project, job.case_dir, job.inputs.patches)
    _log(f"{case.name}: layers counted from the mesh")
    plan = meshing.plan_layers_for(project, job.box) if project.sim.mesh.layer_sizing == "absolute_yplus" else None
    if plan is not None:  # the layer plan: planned against written (the layer cap, D-106)
        out["layer_plan"] = {"count": plan.count, "planned_count": plan.planned_count, "expansion": plan.expansion,
                             "planned_expansion": plan.planned_expansion, "first_m": plan.first,
                             "total_m": plan.total, "planned_total_m": plan.planned_total,
                             "thickness_percent": plan.thickness_percent, "capped": plan.capped}
    try:
        out["layers_walk"] = walk_measurements(case, job.case_dir, job.inputs, target_layers, plan)
    except (IndexError, ValueError) as exc:  # a measurement failure is not a meshing failure (seen once in 5.4)
        out["layers_walk"] = {"method": "layer_walk", "error": f"{type(exc).__name__}: {exc}", "zones": {}}
    if snappy_log.is_file():  # what the layer phase did (D-091); the snap and layer run's log
        out["layers"]["log"] = metrics.layer_log_diagnostics(snappy_log.read_text(errors="replace"))
    out["failed"] = not report.valid
    if solve and report.valid:
        _log(f"{case.name}: indicative y+ run ({case.iterations} iterations)")
        out["yplus"] = run_yplus(project, case, report.cells or 0, job.inputs.patches)
        out["solve_peak_mb"] = _peak_child_mb()
    out["time_s"]["case_total"] = time.monotonic() - t0
    return out
