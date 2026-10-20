"""Rows of the Refinement volumes node and of each volume (D-103) for the properties panel.

``VolumeRowsMixin`` is mixed into PropertiesPanel and uses its row helpers (_make_row, _ro_row, _section,
_set_warn, message). The panel owns the signals ``volume_action(str)`` ("add:<shape>", "wake",
"duplicate", "delete") and ``volume_preview(object)`` (a RefinementVolume drawn while a field is being
edited, None to go back to the project's volumes). Every committed edit is one Project step.
"""

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QLineEdit, QPushButton, QWidget
from pydantic import ValidationError

from vortexcfd.core.model import VOLUME_SHAPES, RefinementVolume
from vortexcfd.workflow import meshing, refinement

# The editable fields of each shape: (field, label, vector?, suffix).
SHAPE_FIELDS: dict[str, tuple[tuple[str, str, bool, str], ...]] = {
    "box": (("centre", "Centre", True, " m"), ("size", "Size", True, " m"),
            ("pitch_deg", "Pitch (about y)", False, "\u00b0"), ("yaw_deg", "Yaw (about z)", False, "\u00b0")),
    "cylinder": (("point1", "End point 1", True, " m"), ("point2", "End point 2", True, " m"), ("radius", "Radius", False, " m")),
    "sphere": (("centre", "Centre", True, " m"), ("radius", "Radius", False, " m")),
    "cone": (("point1", "End point 1", True, " m"), ("radius1", "Radius 1", False, " m"),
             ("point2", "End point 2", True, " m"), ("radius2", "Radius 2", False, " m")),
}
SHAPE_LABELS = {"box": "Box", "cylinder": "Cylinder", "sphere": "Sphere", "cone": "Cone"}
COORD_RANGE = 1e6
ANGLE_RANGES = {"pitch_deg": (-90.0, 90.0), "yaw_deg": (-360.0, 360.0)}


class VectorEdit(QWidget):
    """Three spin boxes (x, y, z) with one suffix."""

    def __init__(self, suffix: str, low: float = -COORD_RANGE) -> None:
        super().__init__()
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.spins = []
        for axis in "xyz":
            spin = QDoubleSpinBox()
            spin.setRange(low, COORD_RANGE)
            spin.setDecimals(4)
            spin.setSuffix(suffix)
            spin.setToolTip(axis)
            spin.setKeyboardTracking(False)
            box.addWidget(spin, 1)
            self.spins.append(spin)

    def value(self) -> tuple[float, float, float]:
        return tuple(s.value() for s in self.spins)  # type: ignore[return-value]

    def setValue(self, value) -> None:
        for s, v in zip(self.spins, value):
            s.setValue(float(v))


class VolumeRowsMixin:
    """The volume rows; ``_kind`` "refinement_volumes" shows the list, "refinement_volume" one volume
    (``_index`` into Simulation.refinement_volumes)."""

    def _build_volume_rows(self) -> None:
        self._section("vol_list", "Refinement volumes")
        self.vol_summary = self._ro_row("vol_summary", "Volumes")
        self.vol_total = self._ro_row("vol_total", "Extra cells")
        self.vol_total.setToolTip(refinement.OVERLAP_NOTE)
        adds = QWidget()
        add_box = QHBoxLayout(adds)
        add_box.setContentsMargins(0, 0, 0, 0)
        self.vol_add_buttons = {}
        for kind in VOLUME_SHAPES:
            button = QPushButton(SHAPE_LABELS[kind])
            button.setToolTip(f"Add a {kind} refinement volume over the parts")
            button.clicked.connect(lambda _=False, k=kind: self.volume_action.emit(f"add:{k}"))
            add_box.addWidget(button)
            self.vol_add_buttons[kind] = button
        self.vol_wake_button = QPushButton("Wake")
        self.vol_wake_button.setToolTip("Add a wake box behind the selected part (or all parts) aligned with the free stream")
        self.vol_wake_button.clicked.connect(lambda: self.volume_action.emit("wake"))
        add_box.addWidget(self.vol_wake_button)
        self._make_row_added("vol_add", "Add", adds)
        # one volume
        self._section("vol_edit", "Refinement volume")
        self.vol_name = QLineEdit()
        self.vol_name.editingFinished.connect(self._commit_volume_name)
        self._make_row_added("vol_name", "Name", self.vol_name)
        self.vol_enabled = QCheckBox()
        self.vol_enabled.toggled.connect(lambda checked: self._commit_volume(enabled=checked))
        self._make_row_added("vol_enabled", "Enabled", self.vol_enabled)
        self.vol_shape = self._ro_row("vol_shape", "Shape")
        self.vol_shape_fields: dict[tuple[str, str], QWidget] = {}
        for kind, fields in SHAPE_FIELDS.items():
            for field, label, vector, suffix in fields:
                if vector:
                    widget = VectorEdit(suffix)
                    if field == "size":
                        for s in widget.spins:
                            s.setRange(1e-6, COORD_RANGE)
                    spins = widget.spins
                else:
                    widget = QDoubleSpinBox()
                    widget.setDecimals(4)
                    widget.setSuffix(suffix)
                    widget.setKeyboardTracking(False)
                    widget.setRange(*ANGLE_RANGES.get(field, (0.0, COORD_RANGE)))
                    spins = [widget]
                for spin in spins:
                    spin.valueChanged.connect(lambda _v, k=kind: self._preview_volume(k))
                    spin.editingFinished.connect(lambda k=kind, f=field: self._commit_volume_field(k, f))
                self.vol_shape_fields[(kind, field)] = widget
                self._make_row_added(f"vol_{kind}_{field}", label, widget)
        self.vol_target = QDoubleSpinBox()
        self.vol_target.setRange(1e-6, COORD_RANGE)
        self.vol_target.setDecimals(5)
        self.vol_target.setSuffix(" m")
        self.vol_target.setKeyboardTracking(False)
        self.vol_target.setToolTip("Requested cell size inside the volume; the mesh uses the first refinement level "
                                   "at or below it (rounded towards the finer level)")
        self.vol_target.editingFinished.connect(lambda: self._commit_volume(target_size=self.vol_target.value()))
        self._make_row_added("vol_target", "Target cell size", self.vol_target)
        self.vol_achieved = self._ro_row("vol_achieved", "Achieved")
        self.vol_cells = self._ro_row("vol_cells", "Extra cells")
        self.vol_cells.setToolTip(refinement.OVERLAP_NOTE)
        self.vol_status = self._ro_row("vol_status", "Domain")
        actions = QWidget()
        act_box = QHBoxLayout(actions)
        act_box.setContentsMargins(0, 0, 0, 0)
        self.vol_duplicate = QPushButton("Duplicate")
        self.vol_duplicate.clicked.connect(lambda: self.volume_action.emit("duplicate"))
        self.vol_delete = QPushButton("Delete")
        self.vol_delete.clicked.connect(lambda: self.volume_action.emit("delete"))
        act_box.addWidget(self.vol_duplicate)
        act_box.addWidget(self.vol_delete)
        self._make_row_added("vol_actions", "", actions)

    def _make_row_added(self, key: str, text: str, widget: QWidget) -> None:
        self._layout.addWidget(self._make_row(key, text, widget))

    def _volume_keys(self) -> list[str]:
        return ["vol_name", "vol_enabled", "vol_shape", "vol_target", "vol_achieved", "vol_cells", "vol_status",
                "vol_actions"] + [f"vol_{k}_{f}" for (k, f) in self.vol_shape_fields]

    def _selected_volume(self) -> RefinementVolume | None:
        volumes = self._project.sim.refinement_volumes
        if self._kind == "refinement_volume" and self._index is not None and 0 <= self._index < len(volumes):
            return volumes[self._index]
        return None

    def _volume_infos(self):
        """(VolumeInfo list, or None when the parts cannot be loaded or there is no domain)."""
        from vortexcfd.gui.scene import domain_box_for

        box = domain_box_for(self._project)
        if box.bounds is None:
            return None
        try:
            est = meshing.project_estimate(self._project, box)
        except Exception:  # an unloadable part: the estimate is not available
            return None
        return refinement.volume_infos(self._project, box, est)

    def _refresh_volumes(self) -> None:
        show_list = self._kind == "refinement_volumes"
        volume = self._selected_volume()
        self._sections["vol_list"].setVisible(show_list)
        for key in ("vol_summary", "vol_total", "vol_add"):
            self._rows[key].setVisible(show_list)
        self._sections["vol_edit"].setVisible(volume is not None)
        for key in self._volume_keys():
            self._rows[key].setVisible(volume is not None and not key.startswith(
                tuple(f"vol_{k}_" for k in SHAPE_FIELDS)))
        if volume is not None:
            for field, *_ in SHAPE_FIELDS[volume.shape.kind]:
                self._rows[f"vol_{volume.shape.kind}_{field}"].setVisible(True)
        if not show_list and volume is None:
            return
        infos = self._volume_infos()
        has_parts = bool(self._project.sim.geometry.parts)
        for button in (*self.vol_add_buttons.values(), self.vol_wake_button):
            button.setEnabled(has_parts and self._project.sim.domain.enabled)
        if show_list:
            volumes = self._project.sim.refinement_volumes
            self.vol_summary.setText("\n".join(
                f"{v.name}: {v.shape.kind}, {v.target_size:.4g} m" + ("" if v.enabled else " (disabled)")
                for v in volumes) or "none: add one below")
            total = sum(i.extra_cells for i in infos) if infos is not None else None
            self.vol_total.setText("—" if total is None else f"+{total:,} cells (estimate)")
            return
        self._fill_volume(volume, next((i for i in infos or () if i.volume.id == volume.id), None))

    def _fill_volume(self, volume: RefinementVolume, info) -> None:
        widgets = [self.vol_name, self.vol_enabled, self.vol_target, *self.vol_shape_fields.values()]
        spins = [s for w in self.vol_shape_fields.values() for s in getattr(w, "spins", [w])]
        for w in widgets + spins:
            w.blockSignals(True)
        try:
            self.vol_name.setText(volume.name)
            self.vol_enabled.setChecked(volume.enabled)
            self.vol_target.setValue(volume.target_size)
            for field, *_ in SHAPE_FIELDS[volume.shape.kind]:
                self.vol_shape_fields[(volume.shape.kind, field)].setValue(getattr(volume.shape, field))
        finally:
            for w in widgets + spins:
                w.blockSignals(False)
        self.vol_shape.setText(SHAPE_LABELS[volume.shape.kind])
        if info is None:
            for label in (self.vol_achieved, self.vol_cells, self.vol_status):
                label.setText("—")
                self._set_warn(label, False)
            return
        self.vol_achieved.setText(f"{info.achieved_size:.4g} m (level {info.level}; requested "
                                  f"{volume.target_size:.4g} m)")
        self.vol_cells.setText(
            f"+{info.extra_cells:,} cells (estimate; the level staircase reaches {info.buffer:.4g} m beyond it)"
            if volume.enabled else "\u2014 (disabled)")
        status = {"inside": ("inside the domain",), "partial": ("partly outside the domain",),
                  "outside": (), "disabled": ("disabled: not written",)}[info.status]  # outside: its message says it
        self.vol_status.setText("\n".join((*status, *info.messages)))
        self._set_warn(self.vol_status, bool(info.messages))

    def _candidate_shape(self, kind: str) -> dict:
        volume = self._selected_volume()
        data = volume.shape.model_dump() if volume is not None else {"kind": kind}
        for field, *_ in SHAPE_FIELDS[kind]:
            data[field] = self.vol_shape_fields[(kind, field)].value()
        return data

    def _preview_volume(self, kind: str) -> None:
        """Draw the shape as it is being edited (not committed; an invalid shape draws nothing new)."""
        volume = self._selected_volume()
        if volume is None or volume.shape.kind != kind:
            return
        try:
            candidate = RefinementVolume.model_validate({**volume.model_dump(), "shape": self._candidate_shape(kind)})
        except ValidationError:
            return
        self.volume_preview.emit(candidate)

    def _commit_volume_field(self, kind: str, field: str) -> None:
        volume = self._selected_volume()
        if volume is None or volume.shape.kind != kind:
            return
        self._commit_volume(shape={field: self.vol_shape_fields[(kind, field)].value()})

    def _commit_volume_name(self) -> None:
        if self._selected_volume() is not None:
            self._commit_volume(name=self.vol_name.text())

    def _commit_volume(self, **fields) -> None:
        volume = self._selected_volume()
        if volume is None:
            return
        try:
            self._project.update_refinement_volume(volume.id, **fields)
        except (ValueError, TypeError, KeyError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.volume_preview.emit(None)
        self.refresh()  # reverts a rejected value
