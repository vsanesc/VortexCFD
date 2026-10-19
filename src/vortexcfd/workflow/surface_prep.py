"""Surface preparation orchestration (Qt-free, D-093).

``prepare(project, strategy)`` runs on a snapshot of the project (a background worker in the GUI):
it loads every Part's surface, computes the diagnostics, applies the strategy and writes its files
under <project>/geometry/ (new names, content-hashed, so undo only points back); the caller applies
the returned ``SurfacePrep`` with one ``Project.set_surface_prep`` (one undoable step).

Meshing uses a result only while it is current: ``state`` compares the parts' geometry with the
hash recorded when the preparation ran; a stale result blocks meshing until it is run again or
removed (workflow/meshing.readiness).
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.core.model import Part, PreparedPart, SurfacePrep
from vortexcfd.core.project import Project
from vortexcfd.geometry import cad as cad_module
from vortexcfd.geometry import regions
from vortexcfd.geometry import surface_prep as prep_geometry
from vortexcfd.geometry.cad_union import ComponentSource, sew_component, SEW_TOLERANCE_FRACTION, union_components
from vortexcfd.geometry.loader import UNIT_TO_METRE, load_surface
from vortexcfd.workflow.part_ops import file_stem

GEOMETRY_DIR = "geometry"
# The intersection curves in the meshing case (constant/triSurface).
JUNCTION_FILE = "surface_prep_junctions.eMesh"
STRATEGY_LABELS = {
    "intersection_features": "Intersection features",
    "cad_union": "CAD union",
}
# The strategy the dialog proposes (D-093: set from the 5.2 comparison, benchmarks/RESULT_5.2.md).
DEFAULT_STRATEGY = "intersection_features"
STALE_MESSAGE = ("The surface preparation is out of date: the parts changed after it ran. "
                 "Run Prepare Surfaces again, or remove it.")


class SurfacePrepError(Exception):
    """The preparation cannot run; the message says why."""


_digests: dict[tuple[str, int, int], str] = {}


def _digest(path: Path | None) -> str | None:
    """SHA-256 of a file's content (cached by path, mtime and size); None when it does not exist."""
    if path is None or not path.is_file():
        return None
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _digests:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _digests[key] = h.hexdigest()
    return _digests[key]


def geometry_hash(project: Project) -> str:
    """Hash of what the preparation depends on: every part's name, units, surface and region id file
    contents and CAD source (file content, bodies, deflections)."""
    folder = project.folder
    rows = []
    for part in project.sim.geometry.parts:
        resolve = (lambda rel: folder / rel if folder is not None and rel else None)
        cad = part.cad.model_dump() if part.cad else None
        rows.append([part.name, part.units, _digest(resolve(part.source_file)), _digest(resolve(part.region_ids)),
                     cad, _digest(resolve(part.cad.file)) if part.cad else None])
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def state(project: Project) -> str:
    """"none" (not run), "current" (meshing uses it) or "stale" (the parts changed since)."""
    prep = project.sim.surface_prep
    if prep is None:
        return "none"
    return "current" if prep.inputs_hash == geometry_hash(project) else "stale"


def current(project: Project) -> SurfacePrep | None:
    """The preparation result when it is current, else None."""
    return project.sim.surface_prep if state(project) == "current" else None


def _original_surface(project: Project, part: Part) -> pv.PolyData:
    return load_surface(project.resolve_part_path(part), part.units)


def prepared_surface(project: Project, part: Part, prep: SurfacePrep | None) -> tuple[pv.PolyData, str | None]:
    """(surface in metres, region id file relative to the project or None) that meshing uses for
    ``part``: the prepared ones when ``prep`` replaced them, else the part's own."""
    entry = prep.prepared(part.name) if prep is not None else None
    if entry is not None and entry.surface_file:
        return load_surface(project.folder / entry.surface_file, "m"), entry.region_ids
    return _original_surface(project, part), part.region_ids


def base_ids(project: Project, part: Part, mesh: pv.PolyData, prep: SurfacePrep | None) -> np.ndarray:
    """Per-triangle base ids of the surface meshing uses for ``part`` (see prepared_surface)."""
    entry = prep.prepared(part.name) if prep is not None else None
    if entry is not None and entry.surface_file:
        if entry.region_ids is None:
            return np.zeros(mesh.n_cells, dtype=np.int64)
        return regions.read_ids(project.folder / entry.region_ids, mesh.n_cells)
    return regions.base_ids(part, mesh, project.folder)


def _write_stl(folder: Path, stem: str, mesh: pv.PolyData) -> Path:
    """Write ``mesh`` (metres) as a binary STL named <stem>_<hash>.stl (an identical file is reused)."""
    pts = np.ascontiguousarray(mesh.points, dtype=np.float32)
    tris = np.ascontiguousarray(prep_geometry.triangles(mesh), dtype=np.int64)
    digest = hashlib.sha256(pts.tobytes() + tris.tobytes()).hexdigest()[:12]
    path = folder / f"{stem}_{digest}.stl"
    if not path.exists():
        pv.PolyData(mesh.points, mesh.faces).save(str(path))
    return path


def _write_features(folder: Path, segments: np.ndarray) -> Path | None:
    if not len(segments):
        return None
    tmp = folder / ".junctions.eMesh.tmp"
    prep_geometry.write_edge_mesh(tmp, segments, "Intersection curves of the components (VortexCFD, D-093)")
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()[:12]
    path = folder / f"junctions_{digest}.eMesh"
    if path.exists():
        tmp.unlink()
    else:
        tmp.replace(path)
    return path


def _relative(project: Project, path: Path | None) -> str | None:
    return None if path is None else path.relative_to(project.folder).as_posix()


def surface_cell_size(project: Project) -> float:
    """The surface cell size of the project's mesh settings (the estimate's size at the surface level),
    from the parts' own surfaces."""
    from vortexcfd.workflow import meshing  # meshing uses this module

    box, _names, meshes = meshing.loaded_original_parts(project)
    bounds = meshing.union_bounds([tuple(float(b) for b in m.bounds) for m in meshes])
    return meshing.project_estimate(project, box, parts_bounds=bounds).surface_size


def _sewing(project: Project, parts: list[Part]) -> dict[str, tuple[bool, int]]:
    """Per CAD part: (its faces sew into a closed solid, free edges after sewing) (diagnostics)."""
    out: dict[str, tuple[bool, int]] = {}
    models: dict[Path, cad_module.CadModel] = {}
    for part in parts:
        if part.cad is None:
            continue
        path = project.folder / part.cad.file
        try:
            model = models.get(path) or models.setdefault(path, cad_module.read_cad(path))
        except (OSError, cad_module.CadImportError):
            continue
        sewn = sew_component(model, part.cad.bodies, SEW_TOLERANCE_FRACTION * model.diagonal)
        out[part.name] = (sewn.closed, sewn.free_edges)
    return out


def prepare(project: Project, strategy: str, cell_size: float | None = None) -> SurfacePrep:
    """Run the surface preparation on ``project`` (a snapshot; the project is not changed) and return
    its result. Files go to <project>/geometry/.

    Raises:
        SurfacePrepError: no saved project, no parts, or a part surface cannot be loaded.
    """
    if strategy not in STRATEGY_LABELS:
        raise SurfacePrepError(f"Unknown surface preparation strategy '{strategy}'")
    if project.folder is None:
        raise SurfacePrepError("Save the project first.")
    parts = list(project.sim.geometry.parts)
    if not parts:
        raise SurfacePrepError("Import at least one part.")
    start = time.monotonic()
    names = [p.name for p in parts]
    try:
        meshes = [_original_surface(project, p) for p in parts]
    except Exception as exc:  # a missing or unreadable file
        raise SurfacePrepError(f"Cannot load the parts: {exc}") from exc
    if cell_size is None:
        cell_size = surface_cell_size(project)
    folder = project.folder / GEOMETRY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    all_curves = prep_geometry.intersection_curves(meshes, drop_hidden=False)
    curves = prep_geometry.intersection_curves(meshes)
    sewing = _sewing(project, parts)
    diagnostics = prep_geometry.diagnose(names, meshes, cell_size, all_curves, sewing, curves)
    report = [("Strategy", STRATEGY_LABELS[strategy])] + diagnostics.rows()
    prepared: list[PreparedPart] = []
    features: Path | None = None
    if strategy == "intersection_features":
        features = _write_features(folder, curves.segments)
        prepared = [PreparedPart(part=n, strategy="intersection_features") for n in names]
        report.append(("Intersection curves", f"{curves.length():.4g} m in {len(curves.segments)} segments"))
    else:
        cad_parts = [p for p in parts if p.cad is not None]
        components = [ComponentSource(p.name, project.folder / p.cad.file, p.cad.bodies, UNIT_TO_METRE[p.units])
                      for p in cad_parts]
        linear = min((p.cad.linear_deflection for p in cad_parts), default=0.0)
        angular = min((p.cad.angular_deflection for p in cad_parts), default=cad_module.ANGULAR_DEFLECTION_DEG)
        union = union_components(components, linear, angular) if components else None
        surfaces = list(meshes)
        fallback = []
        for k, part in enumerate(parts):
            piece = union.meshes.get(part.name) if union is not None else None
            if piece is None:
                note = ("not a CAD part" if part.cad is None else
                        (union.failed.get(part.name) if union is not None else None) or "not in the union")
                prepared.append(PreparedPart(part=part.name, strategy="intersection_features",
                                             note=f"fell back to intersection features: {note}"))
                fallback.append(k)
                continue
            stem = f"{file_stem(part.name)}_union"
            stl = _write_stl(folder, stem, piece)
            ids = regions.write_ids(folder, stem,
                                    np.asarray(piece.cell_data[cad_module.FACE_ARRAY]))
            surfaces[k] = load_surface(stl, "m")
            prepared.append(PreparedPart(part=part.name, strategy="cad_union", surface_file=_relative(project, stl),
                                         region_ids=_relative(project, ids)))
        if fallback:  # the fallback parts against everything else (the union's shares included)
            fallback_curves = prep_geometry.intersection_curves(surfaces, subset=fallback)
            features = _write_features(folder, fallback_curves.segments)
            report.append(("Intersection curves (fallback parts)",
                           f"{fallback_curves.length():.4g} m in {len(fallback_curves.segments)} segments"))
        if union is not None:
            if union.sew_tolerance:
                report.append(("Sewing tolerance", ", ".join(sorted({f"{t * 1000:.3g} mm" for t in union.sew_tolerance.values()}))))
            if union.meshes:
                closed = "closed" if union.open_edges == 0 else f"not closed ({union.open_edges} open edges)"
                if union.non_manifold_edges:
                    closed += f", {union.non_manifold_edges} non-manifold edges"
                report.append(("Union", f"{len(union.meshes)} of {len(parts)} parts, volume {union.volume:.4g} m3, "
                                        f"{closed}, {union.time_s:.1f} s"))
            report += [(f"Union: {n}", reason) for n, reason in union.failed.items()]
            report += [("Union note", note) for note in union.notes]
        for entry in prepared:
            report.append((f"{entry.part}: strategy", STRATEGY_LABELS[entry.strategy] + (f" ({entry.note})" if entry.note else "")))
    elapsed = time.monotonic() - start
    report.append(("Preparation time", f"{elapsed:.1f} s"))
    return SurfacePrep(strategy=strategy, inputs_hash=geometry_hash(project), parts=prepared,
                       features_file=_relative(project, features), report=report, time_s=round(elapsed, 3))
