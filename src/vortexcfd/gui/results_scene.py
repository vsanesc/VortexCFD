"""Results Scene: solver fields on the wall patches and on the section plane (D-053).

``read_results`` runs on a worker thread (``ResultsLoader``); ``ResultsView`` adds VTK actors in the
GUI thread. Colours come from gui/colormaps.py; the scalar bar text uses the theme's ``text`` token.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv
from PySide6.QtCore import QObject, Signal

from vortexcfd.foam.results import FIELDS_BY_KEY, FieldSpec, available_fields, field_values
from vortexcfd.foam.wall_fields import skin_friction_along
from vortexcfd.gui.colormaps import DEFAULT_COLORMAP, matplotlib_name
from vortexcfd.gui.theme import Theme
from vortexcfd.workflow.results_objects import object_geometry, point_fields

SHOWN = "_shown"  # name of the computed array drawn on a dataset
RANGE_MODES = ("auto", "fixed", "symmetric")
DISPLAY_MODES = ("Walls", "Section", "Both")


@dataclass
class ResultsData:
    """One time of a solved case, read from disk."""

    case_dir: Path
    time: str
    fields: list[FieldSpec]
    patches: dict[str, pv.PolyData] = field(default_factory=dict)  # part wall patches (cell data)
    internal: pv.UnstructuredGrid | None = None


def read_results(case_dir: Path, time: str, patch_names) -> ResultsData:
    """Read the part patches and the internal mesh at ``time`` with PyVista's OpenFOAM reader
    (case.foam is created if missing). Slow for big meshes: call it off the GUI thread."""
    case_dir = Path(case_dir)
    foam = case_dir / "case.foam"
    foam.touch(exist_ok=True)
    reader = pv.OpenFOAMReader(str(foam))
    reader.set_active_time_value(float(time))
    reader.enable_all_patch_arrays()
    blocks = reader.read()
    boundary = blocks["boundary"]
    patches = {}
    for name in patch_names:
        if name in boundary.keys():
            surface = boundary[name].extract_surface(algorithm="dataset_surface")
            if surface.n_cells:
                patches[name] = surface
    internal = blocks["internalMesh"] if "internalMesh" in blocks.keys() else None
    return ResultsData(case_dir, time, available_fields(case_dir, time), patches, internal)


class ResultsLoader(QObject):
    """Reads results on a worker thread; the result reaches the GUI only through the signals."""

    loaded = Signal(object)  # ResultsData
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, case_dir: Path, time: str, patch_names) -> None:
        def work() -> None:
            try:
                self.loaded.emit(read_results(case_dir, time, tuple(patch_names)))
            except Exception as exc:  # VTK reader errors, missing files
                self.failed.emit(f"{type(exc).__name__}: {exc}")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


def apply_view(plotter, view) -> None:
    """Put a saved view's camera (core.model.SavedView, D-132) on ``plotter`` (no render)."""
    cam = plotter.camera
    cam.position = tuple(view.position)
    cam.focal_point = tuple(view.focal_point)
    cam.up = tuple(view.view_up)
    cam.parallel_projection = view.parallel
    cam.parallel_scale = view.parallel_scale
    plotter.renderer.ResetCameraClippingRange()


def color_range(values: np.ndarray, mode: str, fixed: tuple[float, float] | None = None) -> tuple[float, float]:
    """The colour scale limits: the data range (auto), the user's limits (fixed) or the data range
    made symmetric about zero (symmetric). A zero-width range is widened so VTK can draw it."""
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    if mode == "fixed":
        if fixed is None:
            raise ValueError("fixed range needs (min, max)")
        lo, hi = float(fixed[0]), float(fixed[1])
        if hi < lo:
            lo, hi = hi, lo
    elif mode == "symmetric":
        m = max(abs(lo), abs(hi))
        lo, hi = -m, m
    elif mode != "auto":
        raise ValueError(f"unknown range mode {mode!r}")
    if hi == lo:
        pad = abs(hi) * 1e-6 or 1e-12
        lo, hi = lo - pad, hi + pad
    return lo, hi


class ResultsView:
    """Field colouring of the walls and/or the section plane, with one scalar bar."""

    SECTION_NAME = "results_section"

    def __init__(self, plotter, theme: Theme) -> None:
        self.plotter = plotter
        self.theme = theme
        self.data: ResultsData | None = None
        self.field_key: str | None = None
        self.colormap = DEFAULT_COLORMAP
        self.range_mode = "auto"
        self.fixed_range: tuple[float, float] | None = None
        self.display = "Walls"
        self.u_ref = 1.0
        self.flow_direction = (1.0, 0.0, 0.0)
        self.highlight_separation = False  # walls with Cf_x < 0 in the error colour (D-061)
        self.separation_actors: list = []
        self.section_axis = 1
        self.section_position: float | None = None
        self.font_size = 11
        self.actors: list = []
        # The results scene objects (D-132): the model's clips, isosurfaces and streamlines; their actors and the
        # reason an object draws nothing (by id).
        self.scene_objects: list = []
        self.object_actors: list = []
        self.object_errors: dict[str, str] = {}
        self._points = None  # the internal mesh with point fields (cached per data)
        self.section_actor = None
        self.scalar_bar = None
        self._bar_title = ""
        self._visible = True

    # -- state ----------------------------------------------------------------------------

    @property
    def has_results(self) -> bool:
        return self.data is not None and bool(self.data.patches)

    def field(self) -> FieldSpec | None:
        return FIELDS_BY_KEY.get(self.field_key) if self.field_key else None

    def set_data(self, data: ResultsData | None) -> None:
        self.data = data
        self._points = None
        keys = [f.key for f in data.fields] if data is not None else []
        if self.field_key not in keys:
            self.field_key = "Cp" if "Cp" in keys else (keys[0] if keys else None)
        if data is not None and data.internal is not None and self.section_position is None:
            self.section_position = self.default_position(self.section_axis)
        self.rebuild()

    def clear(self) -> None:
        self.data = None
        self._remove_actors()

    def configure(self, **state) -> None:
        """Change any of field_key, colormap, range_mode, fixed_range, display, u_ref, font_size,
        section_axis, section_position and redraw."""
        for key, value in state.items():
            if not hasattr(self, key):
                raise AttributeError(key)
            setattr(self, key, value)
        self.rebuild()

    def set_section(self, enabled: bool | None = None, axis: int | None = None,
                    position: float | None = None) -> None:
        """Move the section plane (same API as MeshView.set_section; ``enabled`` is ignored, the
        display mode decides)."""
        if axis is not None and axis != self.section_axis:
            self.section_axis = axis
            position = self.default_position(axis) if position is None else position
        if position is not None:
            self.section_position = position
        self.rebuild()

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        for actor in (*self.actors, *self.separation_actors, *self.object_actors, self.section_actor, self.scalar_bar):
            if actor is not None:
                actor.SetVisibility(visible)

    # -- geometry helpers -------------------------------------------------------------------

    def volume_bounds(self):
        internal = self.data.internal if self.data is not None else None
        return tuple(internal.bounds) if internal is not None and internal.n_cells else None

    def parts_bounds(self):
        if not self.has_results:
            return None
        boxes = [tuple(s.bounds) for s in self.data.patches.values()]
        return (min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes),
                max(b[3] for b in boxes), min(b[4] for b in boxes), max(b[5] for b in boxes))

    def default_position(self, axis: int) -> float | None:
        parts = self.parts_bounds()
        return (parts[2 * axis] + parts[2 * axis + 1]) / 2 if parts is not None else None

    def _origin_normal(self):
        vol = self.volume_bounds()
        origin = [(vol[2 * i] + vol[2 * i + 1]) / 2 for i in range(3)]
        origin[self.section_axis] = self.section_position
        normal = [0.0, 0.0, 0.0]
        normal[self.section_axis] = 1.0
        return tuple(origin), tuple(normal)

    # -- values ----------------------------------------------------------------------------

    def _values(self, dataset) -> np.ndarray | None:
        spec = self.field()
        if spec is None or spec.source not in dataset.cell_data:
            return None
        return field_values(spec, {spec.source: dataset.cell_data[spec.source]}, self.u_ref, self.flow_direction)

    def shown_values(self) -> np.ndarray:
        """All values currently drawn (walls and/or section)."""
        parts = []
        if self.display in ("Walls", "Both") and self.has_results:
            for surface in self.data.patches.values():
                v = self._values(surface)
                if v is not None:
                    parts.append(v)
        if self.display in ("Section", "Both") and self.section_actor is not None:
            parts.append(np.asarray(self.section_actor.mapper.dataset.cell_data[SHOWN]))
        return np.concatenate(parts) if parts else np.array([])

    def field_range(self) -> tuple[float, float] | None:
        """(min, max) of the values shown (the telemetry "Field range")."""
        values = self.shown_values()
        values = values[np.isfinite(values)]
        return (float(values.min()), float(values.max())) if values.size else None

    def clim(self) -> tuple[float, float]:
        return color_range(self.shown_values(), self.range_mode, self.fixed_range)

    # -- drawing -----------------------------------------------------------------------------

    @property
    def can_show_separation(self) -> bool:
        """The walls carry wallShearStress (Cf_x can be computed)."""
        return self.has_results and any("wallShearStress" in s.cell_data for s in self.data.patches.values())

    def separated_fraction(self) -> float | None:
        """Share of the wall faces with Cf_x < 0 (None without wallShearStress)."""
        values = [skin_friction_along(s.cell_data["wallShearStress"], self.flow_direction, self.u_ref)
                  for s in self.data.patches.values() if "wallShearStress" in s.cell_data] if self.has_results else []
        if not values:
            return None
        allv = np.concatenate(values)
        return float(np.mean(allv < 0)) if allv.size else None

    def _remove_actors(self) -> None:
        for actor in (*self.actors, *self.separation_actors, *self.object_actors):
            self.plotter.remove_actor(actor, render=False)
        self.actors = []
        self.separation_actors = []
        self.object_actors = []
        self.plotter.remove_actor(self.SECTION_NAME, render=False)
        self.section_actor = None
        if self.scalar_bar is not None:
            try:
                self.plotter.remove_scalar_bar(self._bar_title, render=False)
            except (KeyError, ValueError, AttributeError):
                pass
            self.scalar_bar = None

    def _point_values(self, spec: FieldSpec | None, dataset) -> np.ndarray | None:
        if spec is None or spec.source not in dataset.point_data:
            return None
        return field_values(spec, {spec.source: dataset.point_data[spec.source]}, self.u_ref, self.flow_direction)

    def object_datasets(self) -> list:
        """(object, dataset with the SHOWN point array) of every visible scene object that draws something
        (D-132); ``object_errors`` gets the reason for the others. Clips and isosurfaces show the scene's field,
        streamlines their own ``color_field``."""
        self.object_errors = {}
        out = []
        if not self.has_results or not self.scene_objects:
            return out
        if self.data.internal is None:
            self.object_errors = {o.id: "no volume mesh in the results" for o in self.scene_objects}
            return out
        if self._points is None:
            self._points = point_fields(self.data.internal)
        for obj in self.scene_objects:
            if not obj.visible:
                continue
            try:
                geometry = object_geometry(self._points, obj, self.u_ref, self.flow_direction)
            except ValueError as exc:
                self.object_errors[obj.id] = str(exc)
                continue
            spec = FIELDS_BY_KEY.get(obj.color_field) if obj.kind == "streamlines" else self.field()
            values = self._point_values(spec, geometry) if geometry.n_points else None
            if values is None:
                self.object_errors[obj.id] = ("nothing to draw (the plane, value or seeds are outside the fluid)"
                                              if not geometry.n_points else "the field is not in the results")
                continue
            geometry = geometry.copy()
            geometry.point_data[SHOWN] = values
            out.append((obj, geometry))
        return out

    def rebuild(self) -> None:
        self._remove_actors()
        spec = self.field()
        if not self.has_results or spec is None:
            return
        use_section = (self.display in ("Section", "Both") and self.data.internal is not None
                       and self.section_position is not None)
        origin, normal = self._origin_normal() if use_section else (None, None)
        section = None
        if use_section:
            cut = self.data.internal.slice(normal=normal, origin=origin)
            values = self._values(cut) if cut.n_cells else None
            if values is not None:
                cut.cell_data[SHOWN] = values
                section = cut
        walls = []
        if self.display in ("Walls", "Both"):
            for name, surface in self.data.patches.items():
                shown = surface
                if section is not None:  # keep the side behind the plane, as in the Mesh Scene
                    shown = surface.clip(normal=normal, origin=origin, invert=False)
                values = self._values(shown) if shown.n_cells else None
                if values is None:
                    continue
                shown = shown.copy()
                shown.cell_data[SHOWN] = values
                walls.append((name, shown))
        datasets = [d for _, d in walls] + ([section] if section is not None else [])
        objects = self.object_datasets()
        shared = [d for o, d in objects if o.kind != "streamlines"]  # the scene field's colour range
        if not datasets and not objects:
            return
        all_values = np.concatenate([np.asarray(d.cell_data[SHOWN]) for d in datasets]
                                    + [np.asarray(d.point_data[SHOWN]) for d in shared] or [np.zeros(1)])
        lo, hi = color_range(all_values, self.range_mode, self.fixed_range)
        cmap = matplotlib_name(self.colormap)
        common = dict(scalars=SHOWN, cmap=cmap, clim=(lo, hi), show_scalar_bar=False, lighting=True,
                      pickable=False, reset_camera=False, render=False, preference="cell")
        for name, dataset in walls:
            self.actors.append(self.plotter.add_mesh(dataset, name=f"results_{name}", **common))
            if self.highlight_separation and "wallShearStress" in dataset.cell_data:
                cfx = skin_friction_along(dataset.cell_data["wallShearStress"], self.flow_direction, self.u_ref)
                ids = np.flatnonzero(cfx < 0)
                if ids.size:
                    back = dataset.extract_cells(ids)
                    actor = self.plotter.add_mesh(back, name=f"results_sep_{name}", color=self.theme.error,
                                                  lighting=True, pickable=False, reset_camera=False, render=False)
                    mapper = actor.GetMapper()  # drawn over the field: same faces, pulled forward
                    mapper.SetResolveCoincidentTopologyToPolygonOffset()
                    mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1.0, -1.0)
                    self.separation_actors.append(actor)
        if section is not None:
            self.section_actor = self.plotter.add_mesh(section, name=self.SECTION_NAME,
                                                       **{**common, "lighting": False})
        for obj, dataset in objects:
            own = obj.kind == "streamlines"
            clim = color_range(np.asarray(dataset.point_data[SHOWN]), "auto") if own else (lo, hi)
            extra = {"line_width": 2.0} if own else {}
            self.object_actors.append(self.plotter.add_mesh(
                dataset, name=f"results_obj_{obj.id}", **{**common, "clim": clim, "preference": "point"}, **extra))
        first = self.actors[0] if self.actors else self.section_actor
        if first is None:
            first = next((a for (o, _d), a in zip(objects, self.object_actors) if o.kind != "streamlines"),
                         self.object_actors[0] if self.object_actors else None)
        mapper = first.mapper
        self._add_scalar_bar(mapper, spec)
        self.set_visible(self._visible)

    def _add_scalar_bar(self, mapper, spec: FieldSpec) -> None:
        t = self.theme
        size = max(10, round(self.font_size * 1.25))  # VTK font size in px for a Qt point size
        self.scalar_bar = self.plotter.add_scalar_bar(
            title=spec.title, mapper=mapper, color=t.text, title_font_size=size + 2, label_font_size=size,
            n_labels=5, fmt="%.3g", vertical=True, position_x=0.86, position_y=0.12, width=0.07, height=0.7,
            bold=False, shadow=False, font_family="arial", render=False,
        )
        self._bar_title = spec.title  # PyVista keys scalar bars by their title
        self.scalar_bar.SetVerticalTitleSeparation(size)  # keep the title clear of the top label

    def bounds(self):
        return self.parts_bounds()
