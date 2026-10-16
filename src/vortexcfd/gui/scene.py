"""Imported parts in the viewer: one VTK actor per Part, picking, visibility, file status."""

import logging
from collections.abc import Callable
from pathlib import Path

from vtkmodules.vtkRenderingCore import vtkPropPicker

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.checks import SurfaceReport, surface_report
from vortexcfd.geometry.loader import SurfaceLoadError, load_surface
from vortexcfd.gui.theme import PICK_MOVE_TOLERANCE_PX, Theme

log = logging.getLogger(__name__)

NONE, OK, MISSING, ERROR = "none", "ok", "missing", "error"


def part_file(project: Project, part: Part) -> Path | None:
    """Resolved source file of ``part`` (None if it has no file or the project is unsaved)."""
    if not part.source_file:
        return None
    try:
        return project.resolve_part_path(part)
    except ValueError:
        return None


def part_status(project: Project, part: Part) -> str:
    """NONE (no source file), OK (file exists) or MISSING (file not found)."""
    if not part.source_file:
        return NONE
    path = part_file(project, part)
    return OK if path is not None and path.is_file() else MISSING


def report_for_part(project: Project, part: Part) -> SurfaceReport | None:
    """Surface report for the part's file (cached); None if there is no loadable file."""
    path = part_file(project, part)
    if path is None or not path.is_file():
        return None
    try:
        return surface_report(path, part.units)  # cached: never recomputed on selection
    except (OSError, SurfaceLoadError):
        return None


class _Record:
    def __init__(self, key, actor, status: str, name: str) -> None:
        self.key, self.actor, self.status, self.name = key, actor, status, name


class PartScene:
    """Keeps one actor per Part in sync with the Project."""

    def __init__(self, plotter, theme: Theme, on_pick: Callable[[int], None]) -> None:
        self.plotter = plotter
        self.theme = theme
        self.on_pick = on_pick
        self.records: list[_Record] = []
        self._counter = 0
        self._press: tuple[int, int] | None = None

    @property
    def actors(self) -> list:
        """Actors of the parts that have geometry, in part order."""
        return [r.actor for r in self.records if r.actor is not None]

    def actor_for(self, index: int):
        return self.records[index].actor if 0 <= index < len(self.records) else None

    def sync(self, project: Project, visibility: dict[str, bool], selected: int | None) -> bool:
        """Make the actors match the project. Returns True if actors were added or removed."""
        parts = project.sim.geometry.parts
        pool: dict[tuple, list[_Record]] = {}
        for rec in self.records:
            if rec.key is not None and rec.actor is not None:
                pool.setdefault(rec.key, []).append(rec)
        changed = False
        new_records: list[_Record] = []
        for part in parts:
            status = part_status(project, part)
            key = None
            actor = None
            if status == OK:
                path = part_file(project, part).resolve()
                key = (str(path), path.stat().st_mtime_ns, part.units)
                reuse = pool.get(key)
                if reuse:
                    actor = reuse.pop(0).actor
                else:
                    try:
                        actor = self._add_actor(load_surface(path, part.units))
                        changed = True
                    except (OSError, SurfaceLoadError) as exc:
                        log.warning("Cannot load part '%s': %s", part.name, exc)
                        status, key = ERROR, None
            new_records.append(_Record(key, actor, status, part.name))
        for leftovers in pool.values():  # actors no part uses any more
            for rec in leftovers:
                self.plotter.remove_actor(rec.actor, render=False)
                changed = True
        self.records = new_records
        self.apply_visibility(visibility)
        self.set_selected(selected)
        return changed

    def _add_actor(self, mesh):
        self._counter += 1
        t = self.theme
        return self.plotter.add_mesh(
            mesh, color=t.part_surface, show_edges=False, edge_color=t.part_edge, line_width=1,
            pickable=True, reset_camera=False, render=False, name=f"part_{self._counter}",
        )

    def apply_visibility(self, visibility: dict[str, bool]) -> None:
        for rec in self.records:
            if rec.actor is not None:
                rec.actor.SetVisibility(visibility.get(rec.name, True))

    def set_selected(self, index: int | None) -> None:
        for i, rec in enumerate(self.records):
            if rec.actor is not None:
                rec.actor.prop.color = self.theme.part_selected if i == index else self.theme.part_surface

    def visible_bounds(self) -> tuple[float, ...] | None:
        """Union of the bounds of the visible part actors (None if there are none)."""
        boxes = [r.actor.GetBounds() for r in self.records
                 if r.actor is not None and r.actor.GetVisibility()]
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes), max(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes),
            min(b[4] for b in boxes), max(b[5] for b in boxes),
        )

    def has_visible(self) -> bool:
        return any(r.actor is not None and r.actor.GetVisibility() for r in self.records)

    # -- picking ---------------------------------------------------------------------

    def index_of(self, actor) -> int | None:
        for i, rec in enumerate(self.records):
            if rec.actor is not None and rec.actor is actor:
                return i
        return None

    def pick_actor(self, actor) -> bool:
        """Report a picked actor; True if it belongs to a part."""
        index = self.index_of(actor)
        if index is None:
            return False
        self.on_pick(index)
        return True

    def install_picking(self) -> None:
        """A left click (press and release within a few px) picks the part under the cursor."""
        iren = self.plotter.iren
        iren.add_observer("LeftButtonPressEvent", lambda *_: self._on_press())
        iren.add_observer("LeftButtonReleaseEvent", lambda *_: self._on_release())

    def _event_position(self) -> tuple[int, int]:
        return tuple(self.plotter.iren.interactor.GetEventPosition())  # type: ignore[return-value]

    def _on_press(self) -> None:
        self._press = self._event_position()

    def _on_release(self) -> None:
        press, self._press = self._press, None
        if press is None:
            return
        x, y = self._event_position()
        if abs(x - press[0]) > PICK_MOVE_TOLERANCE_PX or abs(y - press[1]) > PICK_MOVE_TOLERANCE_PX:
            return  # a camera drag, not a click
        picker = vtkPropPicker()
        if picker.Pick(x, y, 0, self.plotter.renderer):
            self.pick_actor(picker.GetActor())
