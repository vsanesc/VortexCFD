"""Qt-free project document: current simulation, undo/redo history, dirty state, observers."""

from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vortexcfd.core import workspace as ws
from vortexcfd.core.model import Part, Simulation
from vortexcfd.core.project_io import load_simulation, save_simulation

MAX_OBSERVER_ERRORS = 20

Observer = Callable[["Project"], None]


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
        workspace: Path | None = None,
    ) -> None:
        """Wrap a simulation as a document.

        Args:
            sim: Initial state.
            path: File the state was loaded from, if any.
            saved: True if ``sim`` equals the content of ``path`` on disk (clean state).
            max_depth: Maximum number of undo steps kept; the oldest is dropped beyond it.
            workspace: The temporary folder of an untitled project (its geometry/ until the
                first save, D-076); created on demand by ``ensure_folder``.
        """
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        self._sim = sim
        self._path = Path(path) if path is not None else None
        self._saved: Simulation | None = sim.model_copy(deep=True) if saved else None
        self._max_depth = max_depth
        self._workspace = Path(workspace) if workspace is not None and path is None else None
        self._undo: list[tuple[Simulation, str]] = []  # (state before the edit, edit label)
        self._redo: list[tuple[Simulation, str]] = []  # (state before the undo, edit label)
        self._observers: list[Observer] = []
        self.observer_errors: deque[Exception] = deque(maxlen=MAX_OBSERVER_ERRORS)

    @classmethod
    def new(cls, name: str, *, max_depth: int = 100) -> "Project":
        """Create an unsaved project (dirty until first saved)."""
        name = cls._clean_name(name, "Simulation")
        return cls(Simulation(name=name), max_depth=max_depth)

    @classmethod
    def open(cls, path: Path, *, max_depth: int = 100) -> "Project":
        """Open a project file. ProjectFileError propagates on failure."""
        path = Path(path)
        return cls(load_simulation(path), path, saved=True, max_depth=max_depth)

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
        """The folder part files are relative to: the project file's folder, or the temporary
        workspace of an untitled project (None until something was imported into it)."""
        return self._path.parent if self._path is not None else self._workspace

    @property
    def workspace(self) -> Path | None:
        return self._workspace

    def ensure_folder(self) -> Path:
        """The project folder, creating the untitled project's workspace when needed (D-076)."""
        if self._path is None and self._workspace is None:
            self._workspace = ws.new_workspace()
        return self.folder

    def discard_workspace(self) -> None:
        """Delete the untitled project's workspace (closing without saving)."""
        ws.remove_workspace(self._workspace)
        self._workspace = None

    def geometry_sources(self) -> list[Path]:
        """Every file the parts read (surface, region ids, CAD source), resolved."""
        folder = self.folder
        if folder is None:
            return []
        out = []
        for part in self._sim.geometry.parts:
            for rel in (part.source_file, part.region_ids, part.cad.file if part.cad else None):
                if rel:
                    out.append(folder / rel)
        return out

    def save(self, path: Path | None = None) -> None:
        """Save atomically to ``path`` (or to ``self.path``) and clear the dirty state.

        The target is checked first (``workspace.check_save_target``): never a geometry file of
        any kind or of this project, never an existing file that is not a VortexCFD project
        (SaveTargetError). The first save of an untitled project moves its workspace's geometry/
        next to the project file (files renamed on a name clash, the parts' paths updated in the
        whole undo history) and deletes the workspace.
        """
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ValueError("Project has no path yet: pass a path to save()")
        ws.check_save_target(target, self.geometry_sources())
        plan: dict[str, str] = {}
        if self._path is None and self._workspace is not None:
            plan = ws.plan_geometry_move(self._workspace, target.parent)
        renamed = {old: new for old, new in plan.items() if old != new}
        sim = self._remapped(self._sim, renamed) if renamed else self._sim
        save_simulation(sim, target)  # nothing has moved yet if this fails
        if plan:
            ws.apply_geometry_move(self._workspace, target.parent, plan)
        if renamed:
            self._sim = sim
            self._undo = [(self._remapped(state, renamed), label) for state, label in self._undo]
            self._redo = [(self._remapped(state, renamed), label) for state, label in self._redo]
        if self._path is None:
            ws.remove_workspace(self._workspace)
            self._workspace = None
        self._path = target
        self._saved = self._sim.model_copy(deep=True)
        self._notify()

    @staticmethod
    def _remapped(sim: Simulation, renamed: dict[str, str]) -> Simulation:
        """``sim`` with the parts' file paths renamed (source, region ids, CAD source)."""
        data = sim.model_dump()
        for part in data["geometry"]["parts"]:
            for key in ("source_file", "region_ids"):
                if part.get(key) in renamed:
                    part[key] = renamed[part[key]]
            if part.get("cad") and part["cad"]["file"] in renamed:
                part["cad"]["file"] = renamed[part["cad"]["file"]]
        return Simulation.model_validate(data)

    def resolve_part_path(self, part: Part) -> Path:
        """Return the part's source file, relative paths taken from the project folder (the
        workspace of an untitled project)."""
        if self.folder is None:
            raise ValueError(
                "Cannot resolve part file paths: the project has no folder yet (nothing imported, "
                "not saved)."
            )
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

        self._edit(f"Remove part '{old_name}'", mutate)

    def update_part(self, index: int, **fields: Any) -> None:
        old_name = self._part_at(index).name
        if "name" in fields:
            fields["name"] = self._clean_name(fields["name"], "Part")
            self._require_unique_part_name(fields["name"], skip=index)

        def mutate(data: dict[str, Any]) -> None:
            data["geometry"]["parts"][index].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit part '{old_name}' ({changed})", mutate)

    def update_domain(self, **fields: Any) -> None:
        """Edit far-field domain fields as one undoable step (validated; no-ops leave no trace)."""

        def mutate(data: dict[str, Any]) -> None:
            data["domain"].update(fields)

        changed = ", ".join(fields) or "no fields"
        self._edit(f"Edit domain ({changed})", mutate)

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
