"""Imported parts in the viewer: one VTK actor per Part, picking, visibility, file status."""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyvista as pv
from vtkmodules.vtkRenderingCore import vtkPropPicker

from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.checks import SurfaceReport, surface_report
from vortexcfd.geometry.domain import DomainBox, compute_domain, face_corners
from vortexcfd.geometry.loader import SurfaceLoadError, load_surface
from vortexcfd.gui.theme import BOUNDARY_FACE_OPACITY, SECTION_EPS_FRACTION, DOMAIN_OPACITY, HIGHLIGHT_OPACITY, PICK_MOVE_TOLERANCE_PX, Theme

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
        self.enabled = True  # False hides every part actor (e.g. in the mesh scene)
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
                rec.actor.SetVisibility(self.enabled and visibility.get(rec.name, True))

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


# -- far-field domain -----------------------------------------------------------------------


def domain_box_for(project: Project) -> DomainBox:
    """The domain box for the project's loadable parts (their bounds in metres)."""
    bounds, names = [], []
    for part in project.sim.geometry.parts:
        path = part_file(project, part)
        if path is None or not path.is_file():
            continue
        try:
            bounds.append(tuple(float(b) for b in load_surface(path, part.units).bounds))
            names.append(part.name)
        except (OSError, SurfaceLoadError):
            continue
    return compute_domain(bounds, project.sim.domain, names)


class DomainView:
    """The domain box as a translucent wireframe, plus a highlighted boundary face."""

    BOX = "domain_box"
    HIGHLIGHT = "domain_highlight"

    def __init__(self, plotter, theme: Theme) -> None:
        self.plotter = plotter
        self.theme = theme
        self.box_actor = None
        self.highlight_actor = None

    def update(self, box: DomainBox | None, visible: bool, boundary: str | None) -> None:
        """Show the box (edges only) when ``visible``; highlight ``boundary``'s faces."""
        self._clear()
        if box is None or box.bounds is None or not visible:
            return
        t = self.theme
        self.box_actor = self.plotter.add_mesh(
            pv.Box(bounds=box.bounds), style="wireframe", color=t.border_active, line_width=1,
            opacity=DOMAIN_OPACITY, lighting=False, pickable=False, reset_camera=False,
            render=False, name=self.BOX,
        )
        faces = box.boundaries.get(boundary or "", ())
        if faces:
            quads = [pv.PolyData(np.array(face_corners(box.bounds, axis, side)), faces=[4, 0, 1, 2, 3])
                     for axis, side in faces]
            merged = quads[0] if len(quads) == 1 else quads[0].merge(quads[1:])
            self.highlight_actor = self.plotter.add_mesh(
                merged, color=t.accent_secondary, opacity=HIGHLIGHT_OPACITY, lighting=False,
                pickable=False, reset_camera=False, render=False, name=self.HIGHLIGHT,
            )

    def _clear(self) -> None:
        for name in (self.BOX, self.HIGHLIGHT):
            self.plotter.remove_actor(name, render=False)
        self.box_actor = self.highlight_actor = None


# -- mesh view ----------------------------------------------------------------------------------


class MeshView:
    """The generated mesh in the viewer.

    Shows the part (wall) patches with their edges, a section plane through the VOLUME mesh
    (a slice of the OpenFOAM internal mesh: the cut cells drawn with edges over an elevated
    surface, showing the background cells, the refinement and the prism layers) and,
    optionally, the domain boundary patches as translucent faces. With the section on, the part
    patches are clipped to the side behind the plane so the plane is not hidden.
    """

    SECTION_NAME = "mesh_section"

    def __init__(self, plotter, theme: Theme) -> None:
        self.plotter = plotter
        self.theme = theme
        self.actors: list = []  # part patch actors
        self.boundary_actors: list = []  # domain boundary patch actors
        self.section_actor = None
        self.n_faces = 0
        self.stale = False
        self._font_size = 12
        self._visible = True
        self._patch_surfaces: dict[str, pv.PolyData] = {}
        self._patch_names: tuple[str, ...] = ()
        self._internal = None  # the internal (volume) mesh
        self._symmetric = False
        self.section_enabled = True
        self.section_axis = 1  # normal +y
        self.section_position: float | None = None  # plane offset along the axis, metres
        self.boundaries_enabled = False

    @property
    def has_mesh(self) -> bool:
        return bool(self.actors)

    @property
    def has_volume(self) -> bool:
        return self._internal is not None and self._internal.n_cells > 0

    def load(self, case_dir: Path, patch_names, symmetric: bool = False) -> bool:
        """Read <case_dir>/case.foam: part patches, domain patches and the internal mesh.

        False if no part patch was found.
        """
        self.clear()
        reader = pv.OpenFOAMReader(str(Path(case_dir) / "case.foam"))
        reader.enable_all_patch_arrays()
        blocks = reader.read()
        boundary = blocks["boundary"]
        self._patch_names = tuple(patch_names)
        self._symmetric = symmetric
        t = self.theme
        for name in boundary.keys():
            surface = boundary[name].extract_surface(algorithm="dataset_surface")
            if name in self._patch_names:
                self._patch_surfaces[name] = surface
                self.n_faces += surface.n_cells
            elif surface.n_cells:
                self.boundary_actors.append(self.plotter.add_mesh(
                    surface, color=t.border_active, opacity=BOUNDARY_FACE_OPACITY, lighting=False,
                    pickable=False, reset_camera=False, render=False, name=f"mesh_domain_{name}",
                ))
        try:
            internal = blocks["internalMesh"]
            self._internal = internal if internal.n_cells else None
        except KeyError:
            self._internal = None
        self.section_position = self.default_position(self.section_axis)
        self._rebuild()
        return self.has_mesh

    # -- section plane ----------------------------------------------------------------------

    def volume_bounds(self):
        return tuple(self._internal.bounds) if self._internal is not None else None

    def parts_bounds(self):
        boxes = [tuple(s.bounds) for s in self._patch_surfaces.values()]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes),
                max(b[3] for b in boxes), min(b[4] for b in boxes), max(b[5] for b in boxes))

    def default_position(self, axis: int) -> float | None:
        """Plane offset through the parts' centre; the symmetry plane for +y with symmetry on
        (nudged a hair inside the domain so it does not coincide with the boundary face)."""
        vol, parts = self.volume_bounds(), self.parts_bounds()
        if vol is None or parts is None:
            return None
        lo, hi = vol[2 * axis], vol[2 * axis + 1]
        if axis == 1 and self._symmetric:
            return lo + SECTION_EPS_FRACTION * (hi - lo)
        return (parts[2 * axis] + parts[2 * axis + 1]) / 2

    def set_section(self, enabled: bool | None = None, axis: int | None = None,
                    position: float | None = None) -> None:
        """Change the section plane: toggle it, change its normal (offset resets to the default)
        or move it along the normal (metres)."""
        if enabled is not None:
            self.section_enabled = enabled
        if axis is not None and axis != self.section_axis:
            self.section_axis = axis
            position = self.default_position(axis) if position is None else position
        if position is not None:
            self.section_position = position
        self._rebuild()

    def set_boundaries(self, shown: bool) -> None:
        self.boundaries_enabled = shown
        self._apply_visibility()

    def section_origin(self):
        vol = self.volume_bounds()
        origin = [(vol[2 * i] + vol[2 * i + 1]) / 2 for i in range(3)]
        origin[self.section_axis] = self.section_position
        return tuple(origin)

    def normal(self):
        n = [0.0, 0.0, 0.0]
        n[self.section_axis] = 1.0
        return tuple(n)

    def _rebuild(self) -> None:
        """(Re)create the section and the part patch actors for the current plane."""
        for actor in self.actors:
            self.plotter.remove_actor(actor, render=False)
        self.actors = []
        self.plotter.remove_actor(self.SECTION_NAME, render=False)
        self.section_actor = None
        t = self.theme
        use_section = self.has_volume and self.section_position is not None
        origin, normal = (self.section_origin(), self.normal()) if use_section else (None, None)
        if use_section:
            cut = self._internal.slice(normal=normal, origin=origin)
            if cut.n_cells:
                self.section_actor = self.plotter.add_mesh(
                    cut, color=t.elevated, show_edges=True, edge_color=t.part_edge, line_width=1,
                    lighting=False, pickable=False, reset_camera=False, render=False,
                    name=self.SECTION_NAME,
                )
        for name, surface in self._patch_surfaces.items():
            shown = surface
            if use_section and self.section_enabled and self.section_actor is not None:
                # keep the side behind the plane (the camera looks along +normal)
                shown = surface.clip(normal=normal, origin=origin, invert=False)
                if shown.n_cells == 0:
                    continue
            self.actors.append(self.plotter.add_mesh(
                shown, color=t.part_surface, show_edges=True, edge_color=t.part_edge, line_width=1,
                pickable=False, reset_camera=False, render=False, name=f"mesh_{name}",
            ))
        self._apply_visibility()

    def bounds(self):
        """Bounds to frame: the section if shown, else the part patches."""
        if self.section_actor is not None and self.section_enabled:
            return tuple(self.section_actor.GetBounds())
        boxes = [a.GetBounds() for a in self.actors]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes),
                max(b[3] for b in boxes), min(b[4] for b in boxes), max(b[5] for b in boxes))

    FOCUS_MARGIN = 0.75  # section framing: the parts' box grown by this many part extents

    def focus_bounds(self):
        """Bounds to frame: the parts' box with a margin (so the refinement and the prism layers
        around the parts are large in the view), clamped to what is shown."""
        shown, parts = self.bounds(), self.parts_bounds()
        if shown is None or parts is None or not (self.section_actor and self.section_enabled):
            return shown
        extent = max(parts[1] - parts[0], parts[3] - parts[2], parts[5] - parts[4])
        grown = [parts[i] + (-1 if i % 2 == 0 else 1) * self.FOCUS_MARGIN * extent for i in range(6)]
        return tuple(max(grown[i], shown[i]) if i % 2 == 0 else min(grown[i], shown[i]) for i in range(6))

    def camera_for_section(self):
        """Camera position/focal point/up that look at the plane from its negative side."""
        b = self.focus_bounds()
        if b is None:
            return None
        center = [(b[2 * i] + b[2 * i + 1]) / 2 for i in range(3)]
        extent = max(b[1] - b[0], b[3] - b[2], b[5] - b[4]) or 1.0
        position = list(center)
        position[self.section_axis] -= 2.0 * extent
        up = (0.0, 1.0, 0.0) if self.section_axis == 2 else (0.0, 0.0, 1.0)
        return [tuple(position), tuple(center), up]

    def _apply_visibility(self) -> None:
        for actor in self.actors:
            actor.SetVisibility(self._visible)
        if self.section_actor is not None:
            self.section_actor.SetVisibility(self._visible and self.section_enabled)
        for actor in self.boundary_actors:
            actor.SetVisibility(self._visible and self.boundaries_enabled)
        self._apply_stale()

    STALE_NAME = "mesh_stale"
    STALE_TEXT = "MESH OUT OF DATE"

    def set_stale(self, stale: bool, font_size: int) -> None:
        """Warn inside the viewport (VTK text) that the shown mesh no longer matches the inputs."""
        self.stale = stale
        self._font_size = font_size
        self._apply_stale()

    def _apply_stale(self) -> None:
        self.plotter.remove_actor(self.STALE_NAME, render=False)
        if self.stale and self.actors and self._visible:
            self.plotter.add_text(
                self.STALE_TEXT, position="upper_right", font_size=self._font_size,
                color=self.theme.warning, font="courier", name=self.STALE_NAME, render=False,
            )

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        self._apply_visibility()

    def clear(self) -> None:
        for actor in (*self.actors, *self.boundary_actors):
            self.plotter.remove_actor(actor, render=False)
        self.plotter.remove_actor(self.SECTION_NAME, render=False)
        self.actors, self.boundary_actors = [], []
        self.section_actor = None
        self._patch_surfaces = {}
        self._internal = None
        self.section_position = None
        self.n_faces = 0
        self._apply_stale()
