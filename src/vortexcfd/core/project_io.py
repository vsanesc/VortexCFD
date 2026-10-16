"""Simulation project persistence and validation."""

import json
import os
from pathlib import Path
import tempfile
from typing import Any
from pydantic import ValidationError

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Simulation


class ProjectFileError(Exception):
    """Exception raised when loading or validating a project file fails."""


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate project data dictionary from older schema versions to current.

    v1 -> v2 adds the default far-field ``domain``. Data already at the current version (or
    not a dict / without a version) is returned unchanged.
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if data.get("schema_version") == 1:
        data.setdefault("domain", {})  # an empty dict validates to the Domain defaults
        data.setdefault("mesh", {})  # ... and to the Mesh defaults
        data["schema_version"] = 2
    return data


def save_simulation(sim: Simulation, path: Path) -> None:
    """Save a simulation model to a human-readable indented JSON file atomically.

    Args:
        sim: The Simulation instance to serialize.
        path: Destination filesystem path.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = sim.model_dump_json(indent=2)

    tmp_file = tempfile.NamedTemporaryFile(
        mode="w",
        dir=file_path.parent,
        prefix=f".{file_path.name}.",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    )
    try:
        with tmp_file:
            tmp_file.write(json_text + "\n")
        os.replace(tmp_file.name, file_path)
    except BaseException:
        if os.path.exists(tmp_file.name):
            os.remove(tmp_file.name)
        raise


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
