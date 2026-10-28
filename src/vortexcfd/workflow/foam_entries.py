"""Where a property is written in the OpenFOAM case (D-150; Qt-free): "Show in OpenFOAM file".

The map is not written by hand: for a property, the project is copied, that property is changed to another valid
value, both case file sets are built with the app's own writers (the meshing dictionaries of
foam/mesh_case.build_mesh_files and the solver files of foam/physics_case.build_solver_files) and the keyword paths
whose values differ are the property's entries. ``locate`` finds an entry's line in a written file.
"""

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from vortexcfd.core.model import Simulation
from vortexcfd.core.project import Project
from vortexcfd.foam.case_writer import write_spec
from vortexcfd.foam.mesh_case import build_mesh_files
from vortexcfd.foam.physics_case import build_solver_files

PREVIEW_DIR = "case_preview"  # the dictionaries as the app would write them, when the case has none yet

# The properties panel's rows that are written to the case: row key -> (Simulation section, field). The domain faces'
# types are "face_type:<face>".
PROPERTY_FIELDS: dict[str, tuple[str, str]] = {
    **{f"mset_{k}": ("mesh", k) for k in (
        "background_cells_target", "target_surface_size", "surface_size_reference", "base_size", "surface_level_min",
        "surface_level_max", "curvature_levels", "feature_angle", "layers", "expansion_ratio", "final_layer_thickness",
        "min_thickness", "layer_sizing", "target_yplus", "layer_controls")},
    "physics_nu": ("physics", "nu"),
    "physics_rho_ref": ("physics", "rho_ref"),
    "ref_rho": ("physics", "rho_ref"),
    "inflow_speed": ("inflow", "speed"),
    "inflow_turbulence_intensity": ("inflow", "turbulence_intensity"),
    "inflow_viscosity_ratio": ("inflow", "viscosity_ratio"),
    "geometry_alpha_deg": ("inflow", "alpha_deg"),
    "solvers_iterations": ("solvers", "iterations"),
    "solvers_write_interval": ("solvers", "write_interval"),
    "solvers_cores": ("solvers", "cores"),
    "stop_max": ("solvers", "iterations"),
    **{f"dom_{k}": ("domain", k) for k in ("upstream", "downstream", "lateral", "vertical", "radius", "symmetry")},
    "ref_length": ("reports", "reference_length"),
    "ref_area": ("reports", "reference_area"),
    "ref_cofr": ("reports", "center_of_rotation"),
    "dom_ground_enabled": ("domain", "ground.enabled"),
    "dom_ground_motion": ("domain", "ground.motion"),
    "dom_ground_z": ("domain", "ground.z"),
    "dom_ground_start": ("domain", "ground.wall_start_x"),
    "dom_ground_layers": ("domain", "ground.layers"),
}
# A refinement volume's rows (the volume selected in the panel): "volume:<index>:<field>".
VOLUME_FIELDS = {"vol_target": "target_size", "vol_enabled": "enabled"}


@dataclass(frozen=True)
class Entry:
    """An entry of a case file: its path relative to the case and the keyword path inside it."""

    file: str
    keys: tuple[str, ...]

    def text(self) -> str:
        return f"{self.file}: {'/'.join(self.keys)}"


def case_files(project: Project) -> dict:
    """The case's files as the app writes them for ``project``: the meshing dictionaries, then the solver files (the
    solver's controlDict, fvSchemes and fvSolution replace the meshing ones, as Run Solver does)."""
    from vortexcfd.workflow.meshing import mesh_inputs
    from vortexcfd.workflow.solving import solver_input

    files = dict(build_mesh_files(mesh_inputs(project)[0]))
    files.update(build_solver_files(solver_input(project)))
    return files


def _perturbed(value):
    """Another valid value of the same kind (a number scaled, a choice changed, a flag flipped)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1 if abs(value) < 10 else round(value * 2)
    if isinstance(value, float):
        return value * 2 if value else 0.5  # doubled: a size crosses a refinement level
    if isinstance(value, (list, tuple)):
        return type(value)(_perturbed(v) for v in value)
    return value


CHOICES = {
    ("domain", "ground.motion"): ("stationary", "moving"),
    ("mesh", "surface_size_reference"): ("l_ref", "largest_extent"),
    ("mesh", "layer_sizing"): ("absolute_yplus", "relative"),
    ("mesh", "layer_controls"): ("robust", "legacy", "wall_resolved"),
    ("domain", "symmetry"): ("none", "y_min"),
}
OPTIONAL = {("domain", "ground.wall_start_x"): 0.0, ("mesh", "base_size"): 0.3, ("mesh", "surface_level_min"): 3, ("mesh", "surface_level_max"): 6,
            ("reports", "reference_length"): 1.3, ("reports", "reference_area"): 0.7,
            ("reports", "center_of_rotation"): (0.1, 0.0, 0.0)}


# Written only with relative layer sizing: compared with both projects in that mode.
RELATIVE_ONLY = {("mesh", "layers"), ("mesh", "final_layer_thickness")}


def _pair(sim: Simulation, key: str) -> tuple[Simulation, Simulation]:
    """(the simulation the entries are read from, the same with ``key`` changed to another valid value)."""
    data = copy.deepcopy(sim.model_dump())
    if key.startswith("face_layers:"):  # a wall face's prism layers (D-161)
        face = key.split(":", 1)[1]
        changed = copy.deepcopy(data)
        layered = set(sim.domain.wall_layers)
        changed["domain"]["wall_layers"] = sorted(layered ^ {face})
        return sim, Simulation.model_validate(changed)
    if key.startswith("face_type:"):
        face = key.split(":", 1)[1]
        current = sim.domain.face_kind(face)
        changed = copy.deepcopy(data)
        changed["domain"]["boundary_types"][face] = next(k for k in ("wall", "slip") if k != current)
        return sim, Simulation.model_validate(changed)
    if key.startswith("volume:"):
        _prefix, index, field = key.split(":", 2)
        changed = copy.deepcopy(data)
        volume = changed["refinement_volumes"][int(index)]
        volume[field] = _perturbed(volume[field])
        return sim, Simulation.model_validate(changed)
    section, field = PROPERTY_FIELDS[key]
    if (section, field) in RELATIVE_ONLY:
        data["mesh"]["layer_sizing"] = "relative"
        sim = Simulation.model_validate(data)
    if section == "domain" and field.startswith("ground.") and field != "ground.enabled":
        data["domain"]["ground"]["enabled"] = True  # the ground's settings are written only with the ground on
        sim = Simulation.model_validate(data)
    changed = copy.deepcopy(data)
    *parents, leaf = [section, *field.split(".")]
    holder = changed
    for name in parents:
        holder = holder[name]
    value = holder[leaf]
    if (section, field) in CHOICES:
        options = CHOICES[(section, field)]
        holder[leaf] = options[(options.index(value) + 1) % len(options)] if value in options else options[0]
    elif value is None:
        holder[leaf] = OPTIONAL[(section, field)]
        if (section, field) == ("reports", "reference_area"):
            changed["reports"]["reference_area_basis"] = "custom"
    else:
        holder[leaf] = _perturbed(value)
    return sim, Simulation.model_validate(changed)


def _leaves(content, prefix=()) -> dict[tuple, object]:
    out = {}
    if isinstance(content, dict):
        for k, v in content.items():
            out.update(_leaves(v, prefix + (str(k),)))
    else:
        out[prefix] = content
    return out


def _prefixes(leaves) -> set[tuple]:
    return {path[:i] for path in leaves for i in range(1, len(path) + 1)}


def diff_entries(before: dict, after: dict) -> list[Entry]:
    """The keyword paths of ``before`` (the current files) whose values differ in ``after``. A path that only the
    changed files have is reported at its longest part the current files have (e.g. a new keyword inside an
    existing dictionary: that dictionary); files only in ``after`` are left out (nothing to show yet)."""
    entries: list[Entry] = []
    for rel in sorted(before):
        a = _leaves(before[rel].content)
        b = _leaves(after[rel].content) if rel in after else {}
        known = _prefixes(a)
        for path in sorted(set(a) | set(b)):
            if a.get(path) == b.get(path) or not path:
                continue
            while path and path not in known:
                path = path[:-1]
            if path and Entry(rel, path) not in entries:
                entries.append(Entry(rel, path))
    return entries


# The entry shown first when a property is written to several (picked among the found ones, never added).
PRIMARY = {"inflow_speed": ("0/U", "internalField"), "physics_nu": ("constant/transportProperties", "nu"),
           "inflow_turbulence_intensity": ("0/k", "internalField"), "inflow_viscosity_ratio": ("0/omega", "internalField"),
           "geometry_alpha_deg": ("system/controlDict", "liftDir")}
FILE_ORDER = ("constant/", "system/", "0/")


def _rank(key: str, entry: Entry) -> tuple:
    primary = PRIMARY.get(key)
    first = primary is not None and entry.file == primary[0] and entry.keys[-1] == primary[1]
    order = next((i for i, prefix in enumerate(FILE_ORDER) if entry.file.startswith(prefix)), len(FILE_ORDER))
    return (not first, order, len(entry.keys), entry.file, entry.keys)


def entries_for(project: Project, key: str) -> list[Entry]:
    """The case entries the property ``key`` (a PROPERTY_FIELDS row key or "face_type:<face>") is written to, found
    by changing it and comparing what the writers make. Empty when it changes nothing written (e.g. a value only the
    estimate uses), or the project cannot be meshed (MeshingNotReady propagates)."""
    base, changed = _pair(project.sim, key)
    before = case_files(Project(base, project.path))
    after = case_files(Project(changed, project.path))
    return sorted(diff_entries(before, after), key=lambda e: _rank(key, e))


def is_mapped(key: str) -> bool:
    return key in PROPERTY_FIELDS or key in VOLUME_FIELDS or key.startswith(("face_type:", "face_layers:", "volume:"))


# -- the written file ---------------------------------------------------------------------------------------------


def case_file(project: Project, entry: Entry) -> tuple[Path, bool]:
    """(the file to show, whether it is the real case's). Without it in <project>/case the dictionaries are
    written to <project>/case_preview/ (no meshing or solving) and that preview is shown."""
    case = project.folder / "case"
    real = case / entry.file
    if real.is_file():
        return real, True
    preview = project.folder / PREVIEW_DIR
    for rel, spec in case_files(project).items():
        write_spec(preview / rel, spec)
    return preview / entry.file, False


def locate(text: str, keys: tuple[str, ...]) -> int | None:
    """The 0-based line of the entry ``keys`` (nested keyword names) in an OpenFOAM file's text, or None. Each key is
    looked for after the line of the previous one (a dictionary's name, or a quoted regex key); a list index is
    not a keyword and ends the search there."""
    lines = text.splitlines()
    start, found = 0, None
    for key in keys:
        if key.isdigit():
            break
        pattern = re.compile(rf'^\s*"?{re.escape(key)}"?(\s|$|;|\{{)')
        for i in range(start, len(lines)):
            if pattern.match(lines[i]):
                found, start = i, i + 1
                break
        else:
            return found
    return found
