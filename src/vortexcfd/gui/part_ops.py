"""Part geometry operations joining core and geometry (Qt-free): multi-solid STL and CAD import,
repair, region edits (Tasks 3.1, 3.2, 3.3, 3.5).

Every operation that changes a surface or its region ids writes NEW files under
<project>/geometry/ and returns the Part fields to set; the caller applies them with one
``Project.update_part`` (one undoable step: undo points the Part back to the old files).
"""

import os
import re
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.core.model import CadSource, Part, SurfaceRegion
from vortexcfd.core.project import Project
from vortexcfd.geometry import cad as cad_module
from vortexcfd.geometry import regions
from vortexcfd.geometry import repair as repair_module
from vortexcfd.geometry.loader import SOLID_ARRAY, UNIT_TO_METRE, load_surface

GEOMETRY_DIR = "geometry"


def relative(project_dir: Path, path: Path) -> str:
    return Path(os.path.relpath(path, project_dir)).as_posix()


def file_stem(name: str) -> str:
    """A file-name-safe stem for a part or region name."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip("._") or "part"


def unique_path(folder: Path, file_name: str) -> Path:
    candidate = folder / file_name
    stem, suffix, n = candidate.stem, candidate.suffix, 1
    while candidate.exists():
        n += 1
        candidate = folder / f"{stem}_{n}{suffix}"
    return candidate


def unique_name(base: str, taken: set[str]) -> str:
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}_{n}"
    return name


# -- multi-solid STL (Task 3.1) ----------------------------------------------------------------


def part_with_solid_regions(project_dir: Path, name: str, surface: Path, units: str,
                            solid_names: list[str]) -> Part:
    """One Part whose regions are the STL's solids (named after them); writes the region ids."""
    mesh = load_surface(surface, units)
    ids = np.asarray(mesh.cell_data[SOLID_ARRAY])
    ids_file = regions.write_ids(Path(project_dir) / GEOMETRY_DIR, file_stem(name), ids)
    present = set(int(i) for i in np.unique(ids))
    region_list = [SurfaceRegion(name=solid, members=[i]) for i, solid in enumerate(solid_names) if i in present]
    return Part(name=name, source_file=relative(project_dir, surface), units=units, regions=region_list,
                region_ids=relative(project_dir, ids_file))


def parts_per_solid(project_dir: Path, surface: Path, units: str, solid_names: list[str],
                    taken: set[str]) -> list[Part]:
    """One Part per STL solid: each solid is written to its own STL in the file's units (the
    combined file is left for the caller to delete)."""
    project_dir = Path(project_dir)
    mesh = load_surface(surface, units)
    ids = np.asarray(mesh.cell_data[SOLID_ARRAY])
    scale = 1.0 / UNIT_TO_METRE[units]
    parts, taken = [], set(taken)
    for i, solid in enumerate(solid_names):
        cells = np.flatnonzero(ids == i)
        if not len(cells):
            continue
        piece = mesh.extract_cells(cells).extract_surface(algorithm=None).clean()
        piece.points = piece.points * scale
        piece.cell_data.clear()
        path = unique_path(surface.parent, f"{surface.stem}_{file_stem(solid)}.stl")
        piece.save(str(path))
        name = unique_name(solid, taken)
        taken.add(name)
        parts.append(Part(name=name, source_file=relative(project_dir, path), units=units))
    return parts


# -- regions (Task 3.5) ------------------------------------------------------------------------


def part_mesh(project: Project, part: Part) -> pv.PolyData:
    return load_surface(project.resolve_part_path(part), part.units)


def part_base_ids(project: Project, part: Part) -> np.ndarray:
    return regions.base_ids(part, part_mesh(project, part), project.path.parent)


def effective_regions(part: Part, ids: np.ndarray) -> list[SurfaceRegion]:
    """The part's regions; a part without regions has one region holding every base id."""
    if part.regions:
        return [r.model_copy(deep=True) for r in part.regions]
    return [SurfaceRegion(name=part.name, members=sorted(int(i) for i in np.unique(ids)))]


def merge_regions(project: Project, index: int, names: list[str], new_name: str | None = None) -> dict:
    """Part fields after merging the named regions into the first one (renamed to ``new_name``)."""
    part = project.sim.geometry.parts[index]
    current = effective_regions(part, part_base_ids(project, part))
    chosen = [r for r in current if r.name in names]
    if len(chosen) < 2:
        raise regions.RegionError("Select at least two regions to merge.")
    keep = chosen[0]
    keep.members = sorted(m for r in chosen for m in r.members)
    if new_name:
        keep.name = new_name
    out = [r for r in current if r.name not in names or r is keep]
    return {"regions": [r.model_dump() for r in out]}


def rename_region(project: Project, index: int, old: str, new: str) -> dict:
    part = project.sim.geometry.parts[index]
    current = effective_regions(part, part_base_ids(project, part))
    for r in current:
        if r.name == old:
            r.name = new
    return {"regions": [r.model_dump() for r in current]}


def assign_patch(project: Project, index: int, names: list[str], patch: str | None) -> dict:
    """Part fields after assigning the named regions to ``patch`` (None: the part's own patch)."""
    part = project.sim.geometry.parts[index]
    current = effective_regions(part, part_base_ids(project, part))
    for r in current:
        if r.name in names:
            r.patch = patch
    return {"regions": [r.model_dump() for r in current]}


def patch_per_region(project: Project, index: int) -> dict:
    """Every region on its own patch named after it (made OpenFOAM-safe when meshing)."""
    part = project.sim.geometry.parts[index]
    current = effective_regions(part, part_base_ids(project, part))
    for r in current:
        r.patch = re.sub(r"[^A-Za-z0-9_]", "_", r.name)
        if not r.patch[:1].isalpha():
            r.patch = f"p_{r.patch}"
        r.patch = r.patch[:64]
    return {"regions": [r.model_dump() for r in current]}


def split_region(project: Project, index: int, name: str | None, feature_angle: float) -> dict:
    """Part fields after splitting a region (None: the whole part) by ``feature_angle``.

    A CAD part keeps its faces whole and only regroups them (the base ids are the CAD faces); any
    other part gets a new region id file in which the split region's triangles take new ids. The
    pieces are named <region>_1, <region>_2, ... and keep the region's patch and colour."""
    part = project.sim.geometry.parts[index]
    mesh = part_mesh(project, part)
    ids = regions.base_ids(part, mesh, project.path.parent)
    current = effective_regions(part, ids)
    target = current[0] if name is None and len(current) == 1 else next((r for r in current if r.name == name), None)
    if target is None:
        raise regions.RegionError("Select one region to split." if name is None else f"No region '{name}'.")
    selected = np.isin(ids, target.members)
    labels = regions.angle_split(mesh, feature_angle, selected=selected,
                                 groups=ids if part.cad is not None else None)
    count = int(labels.max()) + 1 if selected.any() else 0
    if count < 2:
        raise regions.RegionError(f"Region '{target.name}' has no edges sharper than {feature_angle:g} degrees.")
    if count > regions.MAX_SPLIT_REGIONS:
        raise regions.RegionError(f"The split gives {count} regions (more than {regions.MAX_SPLIT_REGIONS}); "
                                  "use a larger feature angle.")
    taken = {r.name for r in current if r is not target}
    pieces_names = []
    for k in range(count):
        n = unique_name(f"{target.name}_{k + 1}", taken)
        taken.add(n)
        pieces_names.append(n)
    fields: dict = {}
    if part.cad is not None:  # regroup whole faces
        members = [sorted(int(f) for f in np.unique(ids[labels == k])) for k in range(count)]
    else:
        new_ids = ids.copy()
        start = int(ids.max()) + 1
        new_ids[selected] = start + labels[selected]
        members = [[start + k] for k in range(count)]
        path = regions.write_ids(project.path.parent / GEOMETRY_DIR, file_stem(part.name), new_ids)
        fields["region_ids"] = relative(project.path.parent, path)
    pieces = [SurfaceRegion(name=n, members=m, patch=target.patch, color=target.color)
              for n, m in zip(pieces_names, members)]
    out = []
    for r in current:
        out.extend(pieces if r is target else [r])
    fields["regions"] = [r.model_dump() for r in out]
    return fields


def region_of_triangle(project: Project, index: int, triangle: int) -> str | None:
    """Name of the region holding a picked triangle (None: on no region)."""
    part = project.sim.geometry.parts[index]
    ids = part_base_ids(project, part)
    if not 0 <= triangle < len(ids):
        return None
    for r in effective_regions(part, ids):
        if int(ids[triangle]) in r.members:
            return r.name
    return None


# -- CAD import (Task 3.2) ---------------------------------------------------------------------


def tessellation_files(project_dir: Path, part_name: str, cad: CadSource, units: str) -> tuple[str, str]:
    """(surface, region ids) of the CAD source's tessellation, relative to the project folder.

    The STL (model units) and the per-triangle CAD face ids are written once per (file content,
    deflections, bodies) and reused afterwards: the files are the tessellation cache."""
    project_dir = Path(project_dir)
    cad_path = project_dir / cad.file
    scale = UNIT_TO_METRE[units]
    linear = cad.linear_deflection / scale  # model units
    key = cad_module.tessellation_key(cad_path, linear, cad.angular_deflection, cad.bodies)
    folder = project_dir / GEOMETRY_DIR
    stl = folder / f"{file_stem(part_name)}_tess_{key}.stl"
    ids = folder / f"{file_stem(part_name)}_tess_{key}_faces.npy"
    if not (stl.is_file() and ids.is_file()):
        model = cad_module.read_cad(cad_path)
        mesh = cad_module.tessellate(model, linear, cad.angular_deflection, cad.bodies)
        face_ids = np.asarray(mesh.cell_data[cad_module.FACE_ARRAY], dtype=np.int32)
        mesh.cell_data.clear()
        folder.mkdir(parents=True, exist_ok=True)
        mesh.save(str(stl))
        np.save(ids, face_ids, allow_pickle=False)
        if load_surface(stl, units).n_cells != len(face_ids):  # the reader dropped a triangle
            stl.unlink()
            ids.unlink()
            raise cad_module.CadImportError(f"{cad_path.name}: the tessellation does not read back intact")
    return relative(project_dir, stl), relative(project_dir, ids)


def cad_parts(project_dir: Path, cad_file: Path, units: str | None, mode: str, taken: set[str],
              model: "cad_module.CadModel | None" = None) -> list[Part]:
    """Parts for a CAD file copied into <project>/geometry/: one Part holding every body (``mode``
    "regions") or one Part per body ("parts"). Regions follow the face names (faces sharing a name
    form one region; unnamed faces take their body's name) with the file's colours. ``units`` is
    the file's model units for BREP (STEP and IGES are millimetres); default deflections: 1/1000
    of the model's bounding-box diagonal and 20 degrees (D-070)."""
    project_dir = Path(project_dir)
    model = model if model is not None else cad_module.read_cad(cad_file)
    units = model.units or units or "m"
    linear_m = model.default_linear_deflection() * UNIT_TO_METRE[units]
    if linear_m <= 0:
        raise cad_module.CadImportError(f"{cad_file.name} has no extent")
    rel = relative(project_dir, cad_file)
    selections = [None] if mode != "parts" or len(model.bodies) == 1 else [[b] for b in range(len(model.bodies))]
    parts, taken = [], set(taken)
    for bodies in selections:
        base = cad_file.stem if bodies is None else model.bodies[bodies[0]].name
        name = unique_name(base, taken)
        taken.add(name)
        cad = CadSource(file=rel, linear_deflection=float(f"{linear_m:.3g}"),
                        angular_deflection=cad_module.ANGULAR_DEFLECTION_DEG, bodies=bodies)
        surface, ids = tessellation_files(project_dir, name, cad, units)
        groups = model.face_groups(bodies)
        region_list = [SurfaceRegion(name=g, members=sorted(members), color=color) for g, members, color in groups]
        parts.append(Part(name=name, source_file=surface, units=units, cad=cad, region_ids=ids,
                          regions=region_list if len(region_list) > 1 else []))
    return parts


def retessellate(project: Project, index: int, linear_deflection: float | None = None,
                 angular_deflection: float | None = None) -> dict:
    """Part fields for new deflections (metres, degrees): the cached or new tessellation files.
    Regions keep their CAD faces, so they survive the new triangles."""
    part = project.sim.geometry.parts[index]
    if part.cad is None:
        raise cad_module.CadImportError(f"Part '{part.name}' was not imported from CAD")
    update = {}
    if linear_deflection is not None:
        update["linear_deflection"] = linear_deflection
    if angular_deflection is not None:
        update["angular_deflection"] = angular_deflection
    cad = CadSource.model_validate({**part.cad.model_dump(), **update})
    surface, ids = tessellation_files(project.path.parent, part.name, cad, part.units)
    return {"cad": cad.model_dump(), "source_file": surface, "region_ids": ids}


# -- repair (Task 3.3) -------------------------------------------------------------------------

REPAIR_ROWS = (
    ("Watertight", lambda r: "yes" if r.watertight else "no"),
    ("Open edges", lambda r: str(r.open_edges)),
    ("Non-manifold edges", lambda r: str(r.non_manifold_edges)),
    ("Self-intersections", lambda r: str(r.self_intersections) if r.self_intersections is not None
     else r.intersections_note),
    ("Duplicate faces", lambda r: str(r.duplicate_faces)),
    ("Flipped normals", lambda r: str(r.inconsistent_orientation)),
    ("Triangles", lambda r: str(r.n_triangles)),
)


def repair_rows(result: repair_module.RepairResult) -> list[tuple[str, str, str]]:
    """(quantity, before, after) rows of the repair report, then the fidelity metrics of the
    accepted surface (D-072, D-074) in the "after" column."""
    rows = [(label, value(result.before), value(result.after)) for label, value in REPAIR_ROWS]
    f = result.fidelity
    if f is not None:
        rows += [
            ("Bounding box change", "", f"{f.box_change:.2%} of the diagonal (limit {repair_module.BOX_TOLERANCE:.0%})"),
            ("Points on the original surface", "",
             f"{f.on_surface:.1%} within {repair_module.DISTANCE_TOLERANCE:.0%} of the diagonal "
             f"(limit {repair_module.ON_SURFACE_FRACTION:.0%})"),
        ]
    return rows


def repair_part(project: Project, index: int) -> tuple[dict, repair_module.RepairResult]:
    """Repair a part's surface into a NEW file <geometry>/<stem>_repaired[_n].stl (the part's
    units; the original stays) and return (Part fields, result). Region ids are carried to the new
    triangles (nearest old triangle). Fields are empty when nothing needed repair."""
    part = project.sim.geometry.parts[index]
    project_dir = project.path.parent
    source = project.resolve_part_path(part)
    mesh = load_surface(source, part.units)
    result = repair_module.repair_surface(mesh)
    if result.method == "none":
        return {}, result
    repaired = result.mesh.copy()
    repaired.points = repaired.points / UNIT_TO_METRE[part.units]
    folder = project_dir / GEOMETRY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem = source.stem.split("_repaired")[0]
    path = unique_path(folder, f"{stem}_repaired.stl")
    repaired.save(str(path))
    fields: dict = {"source_file": relative(project_dir, path)}
    if part.region_ids:
        old_ids = regions.base_ids(part, mesh, project_dir)
        new_mesh = load_surface(path, part.units)
        new_ids = regions.transfer_ids(mesh, old_ids, new_mesh)
        fields["region_ids"] = relative(project_dir, regions.write_ids(folder, file_stem(part.name), new_ids))
    return fields, result
