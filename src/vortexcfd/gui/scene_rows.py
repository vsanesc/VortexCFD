"""Rows of the Results node, of each results scene object and of each saved view (D-132), mixed into
PropertiesPanel. ``_kind`` "results" shows the add buttons; "scene_object" one object (``_index`` into
Simulation.results.objects); "saved_view" one view. The panel owns the signal ``scene_action(str)`` ("add:<kind>",
"save_view", "go_view:<name>", "image", "report", "line_png:<id>", "line_csv:<id>"), handled by the main window, which
knows the viewer and the results. Every committed edit is one Project step. A line plot's rows show its chart
(matplotlib, embedded) from the samples the Results Scene computed (D-136).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from vortexcfd.core.model import COLOR_RANGE_MODES, SCENE_OBJECT_KINDS, SCENE_OBJECT_LABELS
from vortexcfd.foam.results import FIELD_SPECS, FIELDS_BY_KEY
from vortexcfd.gui.colormaps import COLORMAPS
from vortexcfd.gui.volume_rows import COORD_RANGE, VectorEdit
from vortexcfd.gui.widgets import FlowLayout

# The volume fields an isosurface or streamlines can use (the wall-only fields are not in the volume).
VOLUME_FIELDS = tuple(f for f in FIELD_SPECS if f.source in ("p", "U", "k", "omega", "nut"))
KEEP_LABELS = {"behind": "Behind the normal", "front": "In front of the normal"}
DIRECTION_LABELS = {"both": "Both ways", "forward": "Forward", "backward": "Backward"}
SEED_LABELS = {"line": "Line", "plane": "Plane"}
# The streamlines' own colormap (D-136): None follows the scene's.
COLORMAP_CHOICES = {None: "Scene's colormap", **{name: name for name in COLORMAPS}}
RANGE_LABELS = {m: m for m in COLOR_RANGE_MODES}
# (field, label, widget kind) per object kind; "vector", "float", "length", "int", "check", "fields" or a combo.
OBJECT_FIELDS = {
    "clip": (("origin", "Plane point", "vector"), ("normal", "Plane normal", "vector"), ("keep", "Side kept", "keep")),
    "isosurface": (("field", "Field", "field"), ("value", "Value", "float")),
    "streamlines": (("seed", "Seeds on", "seed"), ("point1", "Line start / plane centre", "vector"),
                    ("point2", "Line end", "vector"), ("normal", "Plane normal", "vector"),
                    ("size", "Plane side", "length"), ("n_seeds", "Seeds", "int"),
                    ("max_length", "Maximum length", "length"), ("direction", "Direction", "direction"),
                    ("color_field", "Coloured by", "field"), ("colormap", "Colormap", "colormap"),
                    ("range_mode", "Colour range", "range"), ("range_min", "Range minimum", "float"),
                    ("range_max", "Range maximum", "float"), ("scalar_bar", "Scalar bar", "check")),
    "line_plot": (("point1", "Start point", "vector"), ("point2", "End point", "vector"),
                  ("n_samples", "Samples", "int"), ("fields", "Fields", "fields")),
}


# Units of the count fields, and the values given in a field's unit: (value, the field it is in) per object kind.
COUNT_SUFFIXES = {"n_seeds": " seeds", "n_samples": " points"}
FIELD_VALUES = {"isosurface": (("value", "field"),),
                "streamlines": (("range_min", "color_field"), ("range_max", "color_field"))}


class FieldChecks(QWidget):
    """One check box per volume field; ``value()`` the checked keys in FIELD_SPECS order (a line plot's fields)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = FlowLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.boxes: dict[str, QCheckBox] = {}
        for spec in VOLUME_FIELDS:
            box = QCheckBox(spec.label)
            layout.addWidget(box)
            self.boxes[spec.key] = box

    def value(self) -> list[str]:
        return [k for k, b in self.boxes.items() if b.isChecked()]

    def setValue(self, keys) -> None:  # noqa: N802 (the Qt spelling, as the spin boxes)
        for k, b in self.boxes.items():
            b.setChecked(k in keys)


def _combo(choices: dict) -> QComboBox:
    box = QComboBox()
    for key, label in choices.items():
        box.addItem(label, key)
    return box


class SceneRowsMixin:
    """The results scene rows (D-132)."""

    def _build_scene_rows(self) -> None:
        self._section("sc_list", "Results scene")
        self.sc_summary = self._ro_row("sc_summary", "Objects")
        adds = QWidget()
        layout = FlowLayout(adds)  # four buttons: wrap in a narrow panel
        layout.setContentsMargins(0, 0, 0, 0)
        layout.set_spacing(4, 4)
        self.sc_add_buttons = {}
        for kind in SCENE_OBJECT_KINDS:
            button = QPushButton(SCENE_OBJECT_LABELS[kind])
            button.setToolTip(f"Add a {SCENE_OBJECT_LABELS[kind].lower()} to the Results Scene")
            button.clicked.connect(lambda _=False, k=kind: self.scene_action.emit(f"add:{k}"))
            layout.addWidget(button)
            self.sc_add_buttons[kind] = button
        adds.setToolTip("Add a results object: a clip, an isosurface, streamlines or a line plot")
        self._layout.addWidget(self._make_row("sc_add", "Add", adds))
        actions = QWidget()
        box = FlowLayout(actions)  # three buttons: wrap in a narrow panel
        box.setContentsMargins(0, 0, 0, 0)
        box.set_spacing(4, 4)
        self.sc_save_view = QPushButton("Save view")
        self.sc_save_view.setToolTip("Save the viewer's camera as a view (the report shows every saved view)")
        self.sc_save_view.clicked.connect(lambda: self.scene_action.emit("save_view"))
        self.sc_image = QPushButton("Export image…")
        self.sc_image.setToolTip("Write the viewer as a PNG at a chosen size (rendered again, not a screenshot)")
        self.sc_image.clicked.connect(lambda: self.scene_action.emit("image"))
        self.sc_report = QPushButton("Create report")
        self.sc_report.setToolTip("Write an HTML report to <project>/reports/")
        self.sc_report.clicked.connect(lambda: self.scene_action.emit("report"))
        for b in (self.sc_save_view, self.sc_image, self.sc_report):
            box.addWidget(b)
        actions.setToolTip("Save the camera as a view, export an image, or write the HTML report")
        self._layout.addWidget(self._make_row("sc_actions", "", actions))
        # one object
        self._section("sc_object", "Scene object")
        self.sc_name = QLineEdit()
        self.sc_name.editingFinished.connect(lambda: self._commit_scene(name=self.sc_name.text().strip()))
        self._layout.addWidget(self._make_row("sc_name", "Name", self.sc_name))
        self.sc_visible = QCheckBox()
        self.sc_visible.toggled.connect(lambda on: self._commit_scene(visible=on))
        self._layout.addWidget(self._make_row("sc_visible", "Visible", self.sc_visible))
        self.sc_status = self._ro_row("sc_status", "Status")
        self.sc_fields: dict[tuple[str, str], QWidget] = {}
        for kind, fields in OBJECT_FIELDS.items():
            for name, label, widget_kind in fields:
                widget = self._scene_widget(widget_kind)
                if name in COUNT_SUFFIXES:
                    widget.setSuffix(COUNT_SUFFIXES[name])
                self.sc_fields[(kind, name)] = widget
                self._connect_scene_widget(widget, name)
                self._layout.addWidget(self._make_row(f"sc_{kind}_{name}", label, widget))
        # the line plot's chart and exports (D-136)
        from vortexcfd.gui.line_chart import LinePlotCanvas

        self.sc_chart = LinePlotCanvas()
        self._layout.addWidget(self._make_row("sc_chart", "Chart", self.sc_chart))
        line_actions = QWidget()
        box = QHBoxLayout(line_actions)
        box.setContentsMargins(0, 0, 0, 0)
        self.sc_line_png = QPushButton("Export PNG…")
        self.sc_line_csv = QPushButton("Export CSV…")
        for button, what in ((self.sc_line_png, "png"), (self.sc_line_csv, "csv")):
            button.clicked.connect(lambda _=False, w=what: self._line_action(w))
            box.addWidget(button)
        self._layout.addWidget(self._make_row("sc_line_actions", "", line_actions))
        self.sc_delete = QPushButton("Delete")
        self.sc_delete.clicked.connect(self._delete_scene_object)
        self._layout.addWidget(self._make_row("sc_delete", "", self.sc_delete))
        # one saved view
        self._section("sv_section", "Saved view")
        self.sv_camera = self._ro_row("sv_camera", "Camera")
        view_actions = QWidget()
        box = QHBoxLayout(view_actions)
        box.setContentsMargins(0, 0, 0, 0)
        self.sv_go = QPushButton("Show")
        self.sv_go.clicked.connect(self._go_view)
        self.sv_delete = QPushButton("Delete")
        self.sv_delete.clicked.connect(self._delete_view)
        box.addWidget(self.sv_go)
        box.addWidget(self.sv_delete)
        self._layout.addWidget(self._make_row("sv_actions", "", view_actions))

    def _scene_widget(self, kind: str) -> QWidget:
        if kind == "vector":
            return VectorEdit(" m")
        if kind in ("float", "length"):
            box = QDoubleSpinBox()
            box.setRange(1e-9 if kind == "length" else -1e12, 1e12)
            box.setDecimals(6)
            box.setKeyboardTracking(False)
            if kind == "length":
                box.setSuffix(" m")
            return box
        if kind == "int":
            box = QSpinBox()
            box.setRange(1, 10_000)
            box.setKeyboardTracking(False)
            return box
        if kind == "field":
            return _combo({f.key: f"{f.label}" + (f" ({f.units})" if f.units else "") for f in VOLUME_FIELDS})
        if kind == "check":
            return QCheckBox()
        if kind == "fields":
            return FieldChecks()
        return _combo({"keep": KEEP_LABELS, "seed": SEED_LABELS, "direction": DIRECTION_LABELS,
                       "colormap": COLORMAP_CHOICES, "range": RANGE_LABELS}[kind])

    def _connect_scene_widget(self, widget: QWidget, name: str) -> None:
        if isinstance(widget, VectorEdit):
            for spin in widget.spins:
                spin.editingFinished.connect(lambda w=widget, n=name: self._commit_scene(**{n: w.value()}))
        elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            widget.editingFinished.connect(lambda w=widget, n=name: self._commit_scene(**{n: w.value()}))
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda on, n=name: self._commit_scene(**{n: on}))
        elif isinstance(widget, FieldChecks):
            for box in widget.boxes.values():
                box.toggled.connect(lambda _on, w=widget, n=name: self._commit_scene(**{n: w.value()}))
        else:
            # applied after the popup has closed (D-152): the commit redraws the scene
            widget.currentIndexChanged.connect(
                lambda _i, w=widget, n=name: QTimer.singleShot(0, lambda: self._commit_scene(**{n: w.currentData()})))

    def _scene_keys(self) -> list[str]:
        return (["sc_name", "sc_visible", "sc_status", "sc_delete", "sc_chart", "sc_line_actions"]
                + [f"sc_{k}_{n}" for k, n in self.sc_fields])

    def _selected_scene_object(self):
        objects = self._project.sim.results.objects
        if self._kind == "scene_object" and self._index is not None and 0 <= self._index < len(objects):
            return objects[self._index]
        return None

    def _selected_view(self):
        views = self._project.sim.results.views
        if self._kind == "saved_view" and self._index is not None and 0 <= self._index < len(views):
            return views[self._index]
        return None

    def set_scene_status(self, errors: dict[str, str], has_results: bool, has_viewer: bool,
                         samples: dict | None = None) -> None:
        """The viewer's state for these rows: why an object draws nothing, whether results and a viewer exist, and
        the line plots' samples (D-136)."""
        self._scene_errors, self._scene_results, self._scene_viewer = errors, has_results, has_viewer
        self._line_samples = samples or {}
        if self._kind in ("results", "scene_object", "saved_view"):
            self._refresh_scene()

    def _refresh_scene(self) -> None:
        show_list = self._kind == "results"
        obj, view = self._selected_scene_object(), self._selected_view()
        self._sections["sc_list"].setVisible(show_list)
        for key in ("sc_summary", "sc_add", "sc_actions"):
            self._rows[key].setVisible(show_list)
        self._sections["sc_object"].setVisible(obj is not None)
        for key in self._scene_keys():
            self._rows[key].setVisible(False)
        self._sections["sv_section"].setVisible(view is not None)
        for key in ("sv_camera", "sv_actions"):
            self._rows[key].setVisible(view is not None)
        has_viewer = getattr(self, "_scene_viewer", False)
        has_results = getattr(self, "_scene_results", False)
        if show_list:
            sim = self._project.sim
            self.sc_summary.setText("\n".join(f"{o.name}: {SCENE_OBJECT_LABELS[o.kind].lower()}"
                                              + ("" if o.visible else " (hidden)") for o in sim.results.objects)
                                    or "none: add one below")
            self.sc_save_view.setEnabled(has_viewer)
            self.sc_image.setEnabled(has_viewer)
            self.sc_report.setEnabled(self._project.path is not None)
        if view is not None:
            self.sv_camera.setText(f"from ({', '.join(f'{v:.4g}' for v in view.position)}) to "
                                   f"({', '.join(f'{v:.4g}' for v in view.focal_point)})")
            self.sv_go.setEnabled(has_viewer)
        if obj is None:
            return
        for key in ("sc_name", "sc_visible", "sc_status", "sc_delete"):
            self._rows[key].setVisible(True)
        for name, *_ in OBJECT_FIELDS[obj.kind]:
            visible = not (obj.kind == "streamlines" and ((obj.seed == "line" and name in ("normal", "size"))
                                                         or (obj.seed == "plane" and name == "point2")
                                                         or (obj.range_mode != "fixed"
                                                             and name in ("range_min", "range_max"))))
            self._rows[f"sc_{obj.kind}_{name}"].setVisible(visible)
        widgets = [self.sc_name, self.sc_visible, *self.sc_fields.values()]
        spins = [s for w in self.sc_fields.values() for s in getattr(w, "spins", [])]
        spins += [b for w in self.sc_fields.values() for b in getattr(w, "boxes", {}).values()]
        for w in widgets + spins:
            w.blockSignals(True)
        try:
            self.sc_name.setText(obj.name)
            self.sc_visible.setChecked(obj.visible)
            for name, *_ in OBJECT_FIELDS[obj.kind]:
                widget, value = self.sc_fields[(obj.kind, name)], getattr(obj, name)
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(max(0, widget.findData(value)))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                else:
                    widget.setValue(value)
        finally:
            for w in widgets + spins:
                w.blockSignals(False)
        for name, field in FIELD_VALUES.get(obj.kind, ()):  # a value in its field's unit (D-166)
            spec = FIELDS_BY_KEY.get(getattr(obj, field))
            self.sc_fields[(obj.kind, name)].setSuffix(f" {spec.units}" if spec is not None and spec.units else "")
        if obj.kind == "line_plot":
            samples = getattr(self, "_line_samples", {}).get(obj.id)
            self._rows["sc_chart"].setVisible(True)
            self._rows["sc_line_actions"].setVisible(True)
            self.sc_chart.set_samples(samples, obj.name)
            for button in (self.sc_line_png, self.sc_line_csv):
                button.setEnabled(samples is not None)
                button.setToolTip("" if samples is not None else "No samples: the line needs results inside the fluid")
        error = getattr(self, "_scene_errors", {}).get(obj.id)
        self.sc_status.setText(error or ("shown" if obj.visible and has_results else
                                         "hidden" if not obj.visible else "no results yet: run the solver"))
        self._set_warn(self.sc_status, error is not None)

    def _commit_scene(self, **fields) -> None:
        obj = self._selected_scene_object()
        if obj is None:
            return
        try:
            self._project.update_scene_object(obj.id, **fields)
        except (ValueError, TypeError, KeyError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    def _line_action(self, what: str) -> None:
        obj = self._selected_scene_object()
        if obj is not None and obj.kind == "line_plot":
            self.scene_action.emit(f"line_{what}:{obj.id}")

    def _delete_scene_object(self) -> None:
        obj = self._selected_scene_object()
        if obj is not None:
            self._project.remove_scene_object(obj.id)

    def _go_view(self) -> None:
        view = self._selected_view()
        if view is not None:
            self.scene_action.emit(f"go_view:{view.name}")

    def _delete_view(self) -> None:
        view = self._selected_view()
        if view is not None:
            self._project.remove_view(view.name)


__all__ = ["SceneRowsMixin", "VOLUME_FIELDS", "COORD_RANGE"]
