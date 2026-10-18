"""Part geometry operations joining core and geometry (Qt-free): multi-solid STL import, region
edits (Tasks 3.1, 3.5).

Every operation that changes a surface or its region ids writes NEW files under
<project>/geometry/ and returns the Part fields to set; the caller applies them with one
``Project.update_part`` (one undoable step: undo points the Part back to the old files).
"""

import os
import re
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.core.model import Part, SurfaceRegion
from vortexcfd.core.project import Project
from vortexcfd.geometry import regions
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
