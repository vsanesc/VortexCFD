"""Temporary workspaces of untitled projects and the checks on a project save target (D-076).

An unsaved project keeps its imported geometry in a workspace under the user's cache directory
(one per untitled project); the first save moves the workspace's geometry next to the project
file. A save target must never be a geometry file or a file that is not a VortexCFD project.
"""

import json
import os
import shutil
import uuid
from pathlib import Path

PROJECT_EXTENSION = ".vcfd"
LEGACY_PROJECT_EXTENSIONS = (".json",)  # opened, then saved as .vcfd
# Every extension a geometry source may have (surfaces and CAD); a save target never has one.
GEOMETRY_EXTENSIONS = (".stl", ".obj", ".ply", ".step", ".stp", ".iges", ".igs", ".brep", ".brp")
GEOMETRY_DIR = "geometry"
WORKSPACE_PREFIX = "untitled-"


class SaveTargetError(ValueError):
    """The chosen file must not be written as a project; the message says why."""


def cache_root() -> Path:
    """<XDG cache>/vortexcfd/workspaces (~/.cache/vortexcfd/workspaces by default)."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "vortexcfd" / "workspaces"


def new_workspace() -> Path:
    """Create a fresh, empty workspace folder for an untitled project."""
    folder = cache_root() / f"{WORKSPACE_PREFIX}{uuid.uuid4().hex[:12]}"
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def remove_workspace(folder: Path | None) -> None:
    """Delete a workspace folder (only one created by ``new_workspace``)."""
    if folder is None:
        return
    folder = Path(folder)
    if folder.parent == cache_root() and folder.name.startswith(WORKSPACE_PREFIX):
        shutil.rmtree(folder, ignore_errors=True)


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


def plan_geometry_move(workspace: Path, target_dir: Path) -> dict[str, str]:
    """{relative path in the workspace: relative path in target_dir} for every file of
    <workspace>/geometry/; a name already taken in <target_dir>/geometry/ gets a numeric suffix."""
    source = Path(workspace) / GEOMETRY_DIR
    plan: dict[str, str] = {}
    if not source.is_dir():
        return plan
    dest = Path(target_dir) / GEOMETRY_DIR
    taken: set[str] = set()
    for item in sorted(source.iterdir()):
        name, n = item.name, 1
        while (dest / name).exists() or name in taken:
            n += 1
            name = f"{item.stem}_{n}{item.suffix}"
        taken.add(name)
        plan[f"{GEOMETRY_DIR}/{item.name}"] = f"{GEOMETRY_DIR}/{name}"
    return plan


def apply_geometry_move(workspace: Path, target_dir: Path, plan: dict[str, str]) -> None:
    (Path(target_dir) / GEOMETRY_DIR).mkdir(parents=True, exist_ok=True)
    for old, new in plan.items():
        shutil.move(str(Path(workspace) / old), str(Path(target_dir) / new))
