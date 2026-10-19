"""The checks on a project save target and the project file extension (D-076, D-077).

A save target must never be a geometry file or a file that is not a VortexCFD project. Every project
has a folder from its creation (D-077): there are no untitled projects and no temporary workspaces.
"""

import json
from pathlib import Path

PROJECT_EXTENSION = ".vcfd"
LEGACY_PROJECT_EXTENSIONS = (".json",)  # opened, then saved as .vcfd
# Every extension a geometry source may have (surfaces and CAD); a save target never has one.
GEOMETRY_EXTENSIONS = (".stl", ".obj", ".ply", ".step", ".stp", ".iges", ".igs", ".brep", ".brp")
GEOMETRY_DIR = "geometry"


class SaveTargetError(ValueError):
    """The chosen file must not be written as a project; the message says why."""


def with_project_extension(path: Path) -> Path:
    """``path`` ending in .vcfd: kept when it does (any case), a legacy .json suffix replaced,
    otherwise .vcfd appended ("wing" -> "wing.vcfd", "wing.v2" -> "wing.v2.vcfd")."""
    path = Path(path)
    if path.suffix.lower() == PROJECT_EXTENSION:
        return path
    if path.suffix.lower() in LEGACY_PROJECT_EXTENSIONS:
        return path.with_suffix(PROJECT_EXTENSION)
    return path.with_name(path.name + PROJECT_EXTENSION)


def is_project_file(path: Path) -> bool:
    """A JSON object with a ``schema_version`` (a VortexCFD project of any version)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(1)
            if head.strip() not in (b"{", b""):
                return False
            fh.seek(0)
            data = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return isinstance(data, dict) and "schema_version" in data


def check_save_target(path: Path, geometry_sources: list[Path] = ()) -> None:
    """Raise SaveTargetError unless ``path`` may be written as a project file.

    Never: a file with a geometry extension, one of the project's geometry sources, a directory,
    or an existing file that is not a VortexCFD project. An existing project may be overwritten
    (the GUI asks first)."""
    path = Path(path)
    if path.suffix.lower() in GEOMETRY_EXTENSIONS:
        raise SaveTargetError(f"{path.name} is a geometry file: a project is never saved over it.")
    target = path.resolve()
    for source in geometry_sources:
        try:
            same = Path(source).resolve() == target
        except OSError:
            same = False
        if same:
            raise SaveTargetError(f"{path.name} is a geometry file of this project: a project is never saved over it.")
    if path.is_dir():
        raise SaveTargetError(f"{path} is a folder.")
    if path.exists() and not is_project_file(path):
        raise SaveTargetError(f"{path.name} exists and is not a VortexCFD project: it was not overwritten.")
