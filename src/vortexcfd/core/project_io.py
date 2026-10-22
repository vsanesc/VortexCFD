"""Simulation project persistence and validation."""

import json
from pathlib import Path
from typing import Any
from pydantic import ValidationError

from vortexcfd.core.atomic_io import write_text_atomic
from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Simulation


# v5 Solvers residual targets (SIMPLE residualControl, D-027): key, field, default.
V5_RESIDUAL_TARGETS = (("residual_p", "p", 1e-4), ("residual_u", "U", 1e-5), ("residual_k", "k", 1e-5),
                       ("residual_omega", "omega", 1e-5))
# The Mesh fields added in v10 (D-085) with the values that give the v9 behaviour.
V10_MESH_FIELDS = {"surface_size_reference": "largest_extent", "curvature_levels": 0}
# The v9 mesh behaviour that the v10 defaults changed (D-085, D-086): a v9 file that does not set these
# keys keeps them (the app always saved the layer settings; hand-written or older files may not).
# The Mesh field added in v13 (D-106) with the value that gives the v12 behaviour: the layer controls and
# the uncapped layer count of every project saved before task 5.4.
V13_MESH_FIELDS = {"layer_controls": "legacy"}
# The Mesh field added in v14 (D-107) with the value that gives the v13 behaviour: the target y+ distance
# used as the first-layer height.
V14_MESH_FIELDS = {"yplus_at": "cell_height"}
V9_MESH_BEHAVIOUR = {**V10_MESH_FIELDS, "layer_sizing": "relative", "target_yplus": 1.0, **V13_MESH_FIELDS,
                     **V14_MESH_FIELDS}


class ProjectFileError(Exception):
    """Exception raised when loading or validating a project file fails."""


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate project data dictionary from older schema versions to current.

    v1 -> v2 adds the default far-field ``domain`` and ``mesh``; v2 -> v3 adds the default
    ``physics``, ``inflow`` and ``solvers``; v3 -> v4 fills ``reports`` (reference value overrides and
    report slots, all unset; v3 had an empty placeholder); v4 -> v5 adds the per-part surface level
    overrides (unset: nothing to fill, the version is bumped); v5 -> v6 turns the residual targets
    (``solvers.residual_p/u/k/omega``, the SIMPLE residualControl) into residual stopping criteria
    combined with "all" (the same stop, D-058); a target the file did not set takes its old default;
    v6 -> v7 adds ``studies`` (mesh study and polar sweep settings, defaults: nothing to fill);
    v7 -> v8 adds the per-part surface regions, region id file and CAD source (unset: one region,
    the part's own patch, as before; D-070, D-071); v8 -> v9 adds the analysis type ("external" for
    every older project, the owner's decision), the preset provenance (unset) and the domain shape
    ("box", with the parts it is sized around unset: all of them; D-077, D-078); v9 -> v10 keeps the
    mesh behaviour of the project where the v10 defaults changed it (V9_MESH_BEHAVIOUR: the surface
    size from the largest extent, no curvature refinement, relative layers with target y+ 1; D-085,
    D-086); v10 -> v11 adds the surface preparation operation (unset: not run, the parts mesh as
    before; D-093); v11 -> v12 adds the user refinement volumes (none; D-103); v12 -> v13 keeps the
    layer controls of the project (V13_MESH_FIELDS: "legacy", no layer cap; D-106); v13 -> v14 keeps
    the project's first-layer convention (V14_MESH_FIELDS: the target y+ distance as the first-layer
    height; D-107); v14 -> v15 adds the meshing cores (unset: automatic, D-111); v15 -> v16 adds the
    domain's ground plane (off: the bottom face stays slip far field, D-116); v16 -> v17 adds the ground's
    wall start (unset: no slip strip) and the mean-stable criterion kind (D-118).
    Data already at the current version (or not a dict /
    without a version) is returned unchanged.
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if data.get("schema_version") == 1:
        data.setdefault("domain", {})  # an empty dict validates to the Domain defaults
        data.setdefault("mesh", {})  # ... and to the Mesh defaults
        data["schema_version"] = 2
    if data.get("schema_version") == 2:
        for key in ("physics", "inflow", "solvers"):
            data.setdefault(key, {})  # empty dicts validate to the defaults
        data["schema_version"] = 3
    if data.get("schema_version") == 3:
        reports = data.get("reports")
        data["reports"] = dict(reports) if isinstance(reports, dict) else {}  # {} = all unset
        data["schema_version"] = 4
    if data.get("schema_version") == 4:
        data["schema_version"] = 5  # Part.surface_level_min/max default to None (the mesh's levels)
    if data.get("schema_version") == 5:
        solvers = data.get("solvers")
        if isinstance(solvers, dict):
            solvers = dict(solvers)
            criteria = []
            for key, field, default in V5_RESIDUAL_TARGETS:
                criteria.append({"kind": "residual", "field": field, "threshold": solvers.pop(key, default)})
            solvers.setdefault("stopping", {"criteria": criteria, "combine": "all"})
            data["solvers"] = solvers
        data["schema_version"] = 6
    if data.get("schema_version") == 6:
        data["schema_version"] = 7  # Simulation.studies defaults (mesh study, polar sweep; D-066, D-067)
    if data.get("schema_version") == 7:
        data["schema_version"] = 8  # Part.regions / region_ids / cad default to unset (D-070, D-071)
    if data.get("schema_version") == 8:
        data.setdefault("analysis_type", "external")  # owner decision (D-077)
        data["schema_version"] = 9  # Domain.shape defaults to "box" (D-078)
    if data.get("schema_version") == 9:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V9_MESH_BEHAVIOUR.items():
            mesh.setdefault(key, value)  # the behaviour the project had (D-085)
        data["mesh"] = mesh
        data["schema_version"] = 10
    if data.get("schema_version") == 10:
        data["schema_version"] = 11  # Simulation.surface_prep defaults to None (not run, D-093)
    if data.get("schema_version") == 11:
        data["schema_version"] = 12  # Simulation.refinement_volumes defaults to [] (D-103)
    if data.get("schema_version") == 12:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V13_MESH_FIELDS.items():
            mesh.setdefault(key, value)  # the layer behaviour the project had (D-106)
        data["mesh"] = mesh
        data["schema_version"] = 13
    if data.get("schema_version") == 13:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V14_MESH_FIELDS.items():
            mesh.setdefault(key, value)  # the first-layer convention the project had (D-107)
        data["mesh"] = mesh
        data["schema_version"] = 14
    if data.get("schema_version") == 14:
        data["schema_version"] = 15  # Mesh.cores defaults to None: automatic meshing cores (D-111)
    if data.get("schema_version") == 15:
        data["schema_version"] = 16  # Domain.ground defaults to off: the bottom face stays far field (D-116)
    if data.get("schema_version") == 16:
        data["schema_version"] = 17  # Ground.wall_start_x defaults to None: the wall starts at the inlet (D-118)
    return data


def save_simulation(sim: Simulation, path: Path) -> None:
    """Save a simulation model to a human-readable indented JSON file atomically.

    Args:
        sim: The Simulation instance to serialize.
        path: Destination filesystem path.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(file_path, sim.model_dump_json(indent=2) + "\n")


def load_simulation(path: Path) -> Simulation:
    """Load and validate a simulation from a JSON file.

    Args:
        path: Path to the JSON project file.

    Returns:
        Validated Simulation instance.

    Raises:
        ProjectFileError: If the file cannot be read, contains invalid JSON,
            has an unsupported schema_version, or fails schema validation.
    """
    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise ProjectFileError(f"Failed to read project file '{file_path}': {err}") from err

    try:
        data = json.loads(content)
    except json.JSONDecodeError as err:
        raise ProjectFileError(f"Invalid JSON in project file '{file_path}': {err}") from err

    if not isinstance(data, dict):
        raise ProjectFileError(
            f"Expected a JSON object at root of '{file_path}', got {type(data).__name__}"
        )

    if "schema_version" not in data:
        raise ProjectFileError(
            f"Missing required 'schema_version' key in project file '{file_path}'"
        )

    schema_version = data["schema_version"]
    if isinstance(schema_version, (int, float)) and schema_version > CURRENT_SCHEMA_VERSION:
        raise ProjectFileError(
            f"Unsupported schema_version {schema_version} in '{file_path}'; "
            f"current supported version is {CURRENT_SCHEMA_VERSION}"
        )

    # Call migration hook for backwards compatibility with older schema versions
    data = migrate(data)

    if not isinstance(data, dict):
        raise ProjectFileError(
            f"Migration returned non-dict object for project file '{file_path}'"
        )

    try:
        return Simulation.model_validate(data)
    except ValidationError as err:
        raise ProjectFileError(f"Validation failed for project file '{file_path}': {err}") from err
