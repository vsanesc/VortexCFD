"""Qt-free project document: current simulation, undo/redo history, dirty state, observers."""

import re
import shutil
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vortexcfd.core import save_rules
from vortexcfd.core.model import Part, RefinementVolume, Simulation, SurfacePrep
from vortexcfd.core.project_io import load_simulation, save_simulation

MAX_OBSERVER_ERRORS = 20

Observer = Callable[["Project"], None]

# A project name is also its folder and file name (D-077): letters, digits, space, "_", "-" and ".",
# starting with a letter or digit, not ending with a space or a dot, at most 64 characters.
PROJECT_NAME_RE = re.compile(r"^\w[\w .-]{0,63}$")
GEOMETRY_DIR = save_rules.GEOMETRY_DIR
CASE_DIR = "case"


class ProjectFolderError(ValueError):
    """A new project's folder cannot be used; the message says why."""


def validate_project_name(name: str) -> str:
    """The stripped name, or ValueError saying why it cannot be a folder and file name."""
    if not isinstance(name, str):
        raise TypeError(f"Project name must be a string, got {type(name).__name__}")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Enter a project name.")
    if len(cleaned) > 64:
        raise ValueError("A project name has at most 64 characters.")
    if not PROJECT_NAME_RE.match(cleaned) or cleaned.endswith("."):
        raise ValueError("A project name has only letters, digits, spaces, '_', '-' and '.', starts with a "
                         "letter or digit and does not end with a dot.")
    return cleaned


def check_new_project_folder(parent: Path, name: str) -> Path:
    """<parent>/<name> for a new project; ProjectFolderError if it exists and is not an empty folder."""
    name = validate_project_name(name)
    if not str(parent).strip():
        raise ProjectFolderError("Choose the parent folder.")
    parent = Path(parent)
    if parent.exists() and not parent.is_dir():
        raise ProjectFolderError(f"{parent} is not a folder.")
    folder = parent / name
    if folder.exists():
        if not folder.is_dir():
            raise ProjectFolderError(f"{folder} exists and is a file: choose another name.")
        if any(folder.iterdir()):
            raise ProjectFolderError(f"The folder {folder} already exists and is not empty: choose another "
                                     "name or parent folder.")
    return folder


class Project:
    """A simulation document with snapshot-based undo/redo and change observers.

    Every edit goes through ``_commit``, which stores a deep-copied snapshot of the previous
    state. ``sim`` returns an independent copy of the current state: change the project only
    through the edit methods.
    """

    def __init__(
        self,
        sim: Simulation,
        path: Path | None = None,
        *,
        saved: bool = False,
        max_depth: int = 100,
    ) -> None:
        """Wrap a simulation as a document.

        Args:
            sim: Initial state.
            path: File the state was loaded from, if any.
            saved: True if ``sim`` equals the content of ``path`` on disk (clean state).
            max_depth: Maximum number of undo steps kept; the oldest is dropped beyond it.
        """
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        self._sim = sim
        self._path = Path(path) if path is not None else None
        self._saved: Simulation | None = sim.model_copy(deep=True) if saved else None
        self._max_depth = max_depth
        self._undo: list[tuple[Simulation, str]] = []  # (state before the edit, edit label)
        self._redo: list[tuple[Simulation, str]] = []  # (state before the undo, edit label)
        self._observers: list[Observer] = []
        self.observer_errors: deque[Exception] = deque(maxlen=MAX_OBSERVER_ERRORS)
        self.migration_notes: list[str] = []  # notes of the schema migration when opened (D-120)

    @classmethod
    def new(cls, name: str, *, max_depth: int = 100) -> "Project":
        """An in-memory project without a file (dirty until saved). The app never offers one to the
        user (every project is created with ``create``, D-077); scripts and tests use it."""
        name = cls._clean_name(name, "Simulation")
        return cls(Simulation(name=name), max_depth=max_depth)

    @classmethod
    def create(cls, parent: Path, name: str, sim: Simulation | None = None, *, max_depth: int = 100) -> "Project":
        """Create <parent>/<name>/ with <name>.vcfd, geometry/ and case/ and save at once (D-077).

        ``sim`` (its name is replaced by ``name``) defaults to a new Simulation. Raises ValueError for
        an invalid name and ProjectFolderError when <parent>/<name> exists and is not an empty folder.
        """
        folder = check_new_project_folder(Path(parent), name)
        name = validate_project_name(name)
        sim = (sim or Simulation(name=name)).model_copy(update={"name": name}, deep=True)
        sim = Simulation.model_validate(sim.model_dump())
        folder.mkdir(parents=True, exist_ok=True)
        (folder / GEOMETRY_DIR).mkdir(exist_ok=True)
        (folder / CASE_DIR).mkdir(exist_ok=True)
        project = cls(sim, max_depth=max_depth)
        project.save(folder / f"{name}{save_rules.PROJECT_EXTENSION}")
        return project

    def _geometry_files(self) -> list[str]:
        """Every project-relative file the geometry reads: per part its surface or CAD tessellation,
        region ids and CAD source, then the surface preparation's files (D-093)."""
        out: list[str | None] = []
        for part in self._sim.geometry.parts:
            out += [part.source_file, part.region_ids, part.cad.file if part.cad else None]
        prep = self._sim.surface_prep
        if prep is not None:
            out += [f for p in prep.parts for f in (p.surface_file, p.region_ids)] + [prep.features_file]
        return [rel for rel in out if rel]

    def referenced_files(self) -> list[str]:
        """The project-relative paths of every file the parts read (surface or CAD tessellation,
        region ids, CAD source) and of the surface preparation's result, each once, in part order."""
        out: list[str] = []
        for rel in self._geometry_files():
            if rel not in out:
                out.append(rel)
        return out

    def duplicate(self, parent: Path, name: str, *, max_depth: int = 100) -> tuple["Project", list[str]]:
        """Save As (D-079): a new project <parent>/<name>/<name>.vcfd with the current state (renamed
        ``name``) and a copy of every file the parts reference; case/ is created empty (no mesh, no
        results). This project and its folder are not changed. Returns the new project and the
        referenced files that were missing (not copied).

        Raises ValueError for an invalid name, ProjectFolderError when <parent>/<name> exists and is
        not an empty folder or a referenced path leaves the project folder.
        """
        if self.folder is None:
            raise ProjectFolderError("The project has no folder to duplicate (never saved).")
        target = check_new_project_folder(Path(parent), name)
        name = validate_project_name(name)
        source = self.folder.resolve()
        if target.resolve() == source or source in target.resolve().parents:
            raise ProjectFolderError("The duplicate cannot be inside the project's own folder.")
        files = self.referenced_files()
        for rel in files:
            resolved = (source / rel).resolve()
            if Path(rel).is_absolute() or source not in resolved.parents:
                raise ProjectFolderError(f"{rel} is outside the project folder: it cannot be duplicated.")
        sim = self._sim.model_copy(update={"name": name}, deep=True)
        existed = target.exists()
        duplicate = Project.create(parent, name, sim, max_depth=max_depth)
        missing = []
        try:
            for rel in files:
                src = source / rel
                if not src.is_file():
                    missing.append(rel)
                    continue
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        except OSError:  # leave nothing half-copied behind (the folder was new or empty)
            for child in list(target.iterdir()):
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            if not existed:
                target.rmdir()
            raise
        return duplicate, missing

    @classmethod
    def open(cls, path: Path, *, max_depth: int = 100) -> "Project":
        """Open a project file. ProjectFileError propagates on failure."""
        path = Path(path)
        notes: list[str] = []
        project = cls(load_simulation(path, notes), path, saved=True, max_depth=max_depth)
        project.migration_notes = notes  # shown to the user by the GUI (D-120)
        return project

    # -- state ---------------------------------------------------------------

    @property
    def sim(self) -> Simulation:
        """Independent deep copy of the current state.

        Mutating it has no effect on the project; all changes go through the edit API.
        """
        return self._sim.model_copy(deep=True)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def dirty(self) -> bool:
        """True unless the current state equals the last saved/opened state."""
        return self._saved is None or self._sim != self._saved

    # -- persistence ---------------------------------------------------------

    @property
    def folder(self) -> Path | None:
        """The folder part files are relative to: the project file's folder (None for an in-memory
        project that was never saved)."""
        return self._path.parent if self._path is not None else None

    def geometry_sources(self) -> list[Path]:
        """Every file the parts read (surface, region ids, CAD source) and the surface preparation's
        files, resolved."""
        folder = self.folder
        if folder is None:
            return []
        return [folder / rel for rel in self._geometry_files()]

    def save(self, path: Path | None = None) -> None:
        """Save atomically to ``path`` (or to ``self.path``) and clear the dirty state.

        The target is checked first (``save_rules.check_save_target``): never a geometry file of
        any kind or of this project, never an existing file that is not a VortexCFD project
        (SaveTargetError).
        """
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ValueError("Project has no path yet: pass a path to save()")
        save_rules.check_save_target(target, self.geometry_sources())
        save_simulation(self._sim, target)
        self._path = target
        self._saved = self._sim.model_copy(deep=True)
        self._notify()

    def resolve_part_path(self, part: Part) -> Path:
        """Return the part's source file, relative paths taken from the project folder."""
        if self.folder is None:
            raise ValueError("Cannot resolve part file paths: the project has no folder (never saved).")
        return self.folder / part.source_file

    # -- edits ---------------------------------------------------------------

    def rename(self, name: str) -> None:
        name = self._clean_name(name, "Simulation")
        self._edit(f"Rename simulation to '{name}'", lambda data: data.update(name=name))

    def add_part(self, part: Part) -> None:
        part_data = part.model_dump()
        part_data["name"] = self._clean_name(part_data["name"], "Part")
        self._require_unique_part_name(part_data["name"], skip=None)

        def mutate(data: dict[str, Any]) -> None:
            data["geometry"]["parts"].append(part_data)

        self._edit(f"Add part '{part_data['name']}'", mutate)

    def add_parts(self, parts: list[Part], label: str | None = None) -> None:
        """Add several parts as one undoable step (e.g. one part per solid of an STL file)."""
        names = [self._clean_name(p.name, "Part") for p in parts]
        taken = {p.name for p in self._sim.geometry.parts}
        for name in names:
            if name in taken:
                raise ValueError(f"A part named '{name}' already exists")
            taken.add(name)
        dumps = [{**p.model_dump(), "name": n} for p, n in zip(parts, names)]

        def mutate(data: dict[str, Any]) -> None:
            data["geometry"]["parts"].extend(dumps)

        self._edit(label or f"Add parts {', '.join(repr(n) for n in names)}", mutate)

    def remove_part(self, index: int) -> None:
        old_name = self._part_at(index).name

        def mutate(data: dict[str, Any]) -> None:
            del data["geometry"]["parts"][index]
            listed = data["domain"].get("parts")
            if listed is not None and old_name in listed:  # an empty list falls back to every part
                listed = [n for n in listed if n != old_name]
                data["domain"]["parts"] = listed or None

        self._edit(f"Remove part '{old_name}'", mutate)

    def update_part(self, index: int, **fields: Any) -> None:
        old_name = self._part_at(index).name
        if "name" in fields:
            fields["name"] = self._clean_name(fields["name"], "Part")
            self._require_unique_part_name(fields["name"], skip=index)

        def mutate(data: dict[str, Any]) -> None:
            data["geometry"]["parts"][index].update(fields)
            listed = data["domain"].get("parts")
            if "name" in fields and listed is not None:  # the domain follows a renamed part
                data["domain"]["parts"] = [fields["name"] if n == old_name else n for n in listed]

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit part '{old_name}' ({changed})", mutate)

    def update_domain(self, label: str | None = None, **fields: Any) -> None:
        """Edit far-field domain fields as one undoable step (validated; no-ops leave no trace)."""

        def mutate(data: dict[str, Any]) -> None:
            data["domain"].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(label or f"Edit domain ({changed})", mutate)

    def set_surface_prep(self, prep: SurfacePrep | None, label: str | None = None) -> None:
        """Apply (or, with None, remove) the surface preparation result as one undoable step (D-093)."""
        value = prep.model_dump() if prep is not None else None
        default = (f"Surface preparation ({prep.strategy})" if prep is not None else "Remove surface preparation")

        def mutate(data: dict[str, Any]) -> None:
            data["surface_prep"] = value

        self._edit(label or default, mutate)

    # -- refinement volumes (D-103) ---------------------------------------------------------------

    def volume(self, volume_id: str) -> RefinementVolume:
        for v in self._sim.refinement_volumes:
            if v.id == volume_id:
                return v
        raise KeyError(f"No refinement volume with id {volume_id!r}")

    def free_volume_name(self, base: str) -> str:
        """``base``, or ``base_2``, ``base_3``, ... : the first name no volume uses (case-insensitive)."""
        taken = {v.name.casefold() for v in self._sim.refinement_volumes}
        name, n = base, 1
        while name.casefold() in taken:
            n += 1
            name = f"{base}_{n}"
        return name

    def _free_volume_id(self) -> str:
        used = {v.id for v in self._sim.refinement_volumes}
        n = len(used) + 1
        while f"v{n}" in used:
            n += 1
        return f"v{n}"

    def add_refinement_volume(self, volume: RefinementVolume, label: str | None = None) -> str:
        """Append ``volume`` as one undoable step with a new id (its name made unique); returns the id."""
        data = volume.model_dump()
        data["id"] = self._free_volume_id()
        data["name"] = self.free_volume_name(data["name"])

        def mutate(sim: dict[str, Any]) -> None:
            sim["refinement_volumes"].append(data)

        self._edit(label or f"Add refinement volume '{data['name']}'", mutate)
        return data["id"]

    def duplicate_refinement_volume(self, volume_id: str) -> str:
        source = self.volume(volume_id)
        return self.add_refinement_volume(source, f"Duplicate refinement volume '{source.name}'")

    def remove_refinement_volume(self, volume_id: str) -> None:
        name = self.volume(volume_id).name

        def mutate(sim: dict[str, Any]) -> None:
            sim["refinement_volumes"] = [v for v in sim["refinement_volumes"] if v["id"] != volume_id]

        self._edit(f"Delete refinement volume '{name}'", mutate)

    def update_refinement_volume(self, volume_id: str, **fields: Any) -> None:
        """Edit a volume's fields (name, target_size, enabled, or ``shape`` as a dict merged into the
        current shape) as one undoable step (validated; no-ops leave no trace)."""
        old = self.volume(volume_id)
        if "name" in fields:
            fields["name"] = self._clean_name(fields["name"], "Volume")
            if any(v.id != volume_id and v.name.casefold() == fields["name"].casefold()
                   for v in self._sim.refinement_volumes):
                raise ValueError(f"A refinement volume named '{fields['name']}' already exists")

        def mutate(sim: dict[str, Any]) -> None:
            for v in sim["refinement_volumes"]:
                if v["id"] == volume_id:
                    for key, value in fields.items():
                        if key == "shape" and isinstance(value, dict) and value.get("kind", v["shape"]["kind"]) == v["shape"]["kind"]:
                            v["shape"] = {**v["shape"], **value}
                        else:
                            v[key] = value

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit refinement volume '{old.name}' ({changed})", mutate)

    def replace_simulation(self, sim: Simulation, label: str) -> None:
        """Make ``sim`` the current state as one undoable step (a preset applied, for example)."""
        self._commit(Simulation.model_validate(sim.model_dump()), label)

    def update_mesh(self, **fields: Any) -> None:
        """Edit meshing controls as one undoable step (validated; no-ops leave no trace)."""

        def mutate(data: dict[str, Any]) -> None:
            data["mesh"].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit mesh ({changed})", mutate)

    def update_physics(self, **fields: Any) -> None:
        """Edit flow physics as one undoable step (validated; no-ops leave no trace)."""
        self._update_section("physics", "physics", fields)

    def update_inflow(self, **fields: Any) -> None:
        """Edit inflow conditions as one undoable step."""
        self._update_section("inflow", "inflow", fields)

    def update_solver(self, **fields: Any) -> None:
        """Edit solver settings as one undoable step."""
        self._update_section("solvers", "solver", fields)

    def update_reports(self, **fields: Any) -> None:
        """Edit reference value overrides or report slots as one undoable step."""
        self._update_section("reports", "reports", fields)

    def update_study(self, study: str, **fields: Any) -> None:
        """Edit the mesh study ("mesh") or polar sweep ("polar") settings as one undoable step."""

        def mutate(data: dict[str, Any]) -> None:
            data["studies"][study].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit {study} study ({changed})", mutate)

    def _update_section(self, key: str, label: str, fields: dict[str, Any]) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data[key].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit {label} ({changed})", mutate)

    # -- history -------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1][1] if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1][1] if self._redo else None

    def undo(self) -> bool:
        """Revert the last edit. Returns False if there is nothing to undo."""
        if not self._undo:
            return False
        before, label = self._undo.pop()
        self._redo.append((self._sim.model_copy(deep=True), label))
        self._sim = before
        self._notify()
        return True

    def redo(self) -> bool:
        """Re-apply the last undone edit. Returns False if there is nothing to redo."""
        if not self._redo:
            return False
        after, label = self._redo.pop()
        self._undo.append((self._sim.model_copy(deep=True), label))
        self._sim = after
        self._notify()
        return True

    # -- observers -----------------------------------------------------------

    def subscribe(self, callback: Observer) -> Callable[[], None]:
        """Register callback(project), called synchronously after every state change.

        Returns a function that removes the subscription (safe to call more than once).
        """
        self._observers.append(callback)

        def unsubscribe() -> None:
            if callback in self._observers:
                self._observers.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        for callback in list(self._observers):
            try:
                callback(self)
            except Exception as exc:  # one observer must not affect the others
                self.observer_errors.append(exc)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _clean_name(name: Any, what: str) -> str:
        if not isinstance(name, str):
            raise TypeError(f"{what} name must be a string, got {type(name).__name__}")
        cleaned = name.strip()
        if not cleaned:
            raise ValueError(f"{what} name must not be empty")
        return cleaned

    def _part_at(self, index: int) -> Part:
        parts = self._sim.geometry.parts
        if not 0 <= index < len(parts):
            raise IndexError(f"Part index {index} out of range (0..{len(parts) - 1})")
        return parts[index]

    def _require_unique_part_name(self, name: str, skip: int | None) -> None:
        for i, part in enumerate(self._sim.geometry.parts):
            if i != skip and part.name == name:
                raise ValueError(f"A part named '{name}' already exists")

    def _edit(self, label: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        """Apply mutate to a dump of the current state; validate; commit."""
        data = self._sim.model_dump()
        mutate(data)
        self._commit(Simulation.model_validate(data), label)

    def _commit(self, new_sim: Simulation, label: str) -> None:
        """Make new_sim current as one undoable step. No-op edits leave no trace."""
        if new_sim == self._sim:
            return
        self._undo.append((self._sim.model_copy(deep=True), label))
        if len(self._undo) > self._max_depth:
            del self._undo[0]
        self._redo.clear()
        self._sim = new_sim
        self._notify()
