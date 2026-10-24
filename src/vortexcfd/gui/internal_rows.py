"""Rows of the internal-flow nodes (D-129) for the properties panel: one surface patch (its role and its inlet or
outlet conditions, with units) and the Internal Flow Reports node (cutting planes and pressure drops).

``InternalRowsMixin`` is mixed into PropertiesPanel and uses its row helpers (_make_row, _ro_row, _section,
_probe-style dynamic rows, message). ``_kind`` "internal_patch" shows the patch ``_index`` of
workflow/internal.patches; "internal_reports" the planes and pressure drops. Every committed edit is one Project step.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import (
    INLET_KIND_LABELS,
    INLET_KINDS,
    LENGTH_SCALE_OF_DH,
    PATCH_ROLE_LABELS,
    PATCH_ROLES,
)
from vortexcfd.gui.theme import metrics, set_text_role
from vortexcfd.gui.widgets import discard
from vortexcfd.workflow import internal, meshing, solving

# When to use which inlet (the user-manual notes, docs/USER_MANUAL notes in docs/STATUS.md, repeated as tooltips).
KIND_TIPS = {
    "velocity": "A uniform velocity normal to the patch, into the domain. Use it when the inlet speed is known.",
    "mass_flow": "A mass flow rate (kg/s) imposed as a uniform velocity normal to the patch (Q = \u1e41 / \u03c1, "
                 "\u03c1 the reference density of Physics). Use it when the flow rate is known, e.g. a pump or a "
                 "duct with a metered flow.",
    "total_pressure": "A total pressure (Pa, gauge) at the inlet; the flow rate follows from the losses. Use it for a "
                      "plenum or a reservoir at a known pressure; the inflow is normal to the patch.",
}
ROLE_TIP = ("Inlet, outlet or wall. Every patch of the geometry is one of them; layers are added on walls only. "
            "A change puts the mesh out of date (the patch type and the layers change).")
PRESSURE_RANGE = 1e9


def _spin(low: float, high: float, decimals: int, suffix: str) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    return box


class InternalRowsMixin:
    """The internal-flow rows (D-129)."""

    def _build_internal_rows(self) -> None:
        self._section("ip_section", "Boundary")
        self.ip_patch = self._ro_row("ip_patch", "Patch")
        self.ip_role = QComboBox()
        for role in PATCH_ROLES:
            self.ip_role.addItem(PATCH_ROLE_LABELS[role], role)
        self.ip_role.setToolTip(ROLE_TIP)
        self.ip_role.currentIndexChanged.connect(lambda _i: self._commit_boundary(role=self.ip_role.currentData()))
        self._layout.addWidget(self._make_row("ip_role", "Role", self.ip_role))
        self.ip_kind = QComboBox()
        for kind in INLET_KINDS:
            self.ip_kind.addItem(INLET_KIND_LABELS[kind], kind)
            self.ip_kind.setItemData(self.ip_kind.count() - 1, KIND_TIPS[kind], Qt.ItemDataRole.ToolTipRole)
        self.ip_kind.currentIndexChanged.connect(lambda _i: self._commit_boundary(inlet={"kind": self.ip_kind.currentData()}))
        self._layout.addWidget(self._make_row("ip_kind", "Inlet type", self.ip_kind))
        self.ip_speed = _spin(1e-9, 1e5, 4, " m/s")
        self.ip_speed.setToolTip("Speed normal to the patch, into the domain")
        self.ip_speed.editingFinished.connect(lambda: self._commit_boundary(inlet={"speed": self.ip_speed.value()}))
        self._layout.addWidget(self._make_row("ip_speed", "Velocity", self.ip_speed))
        self.ip_mass = _spin(1e-12, 1e9, 6, " kg/s")
        self.ip_mass.setToolTip("Mass flow rate into the domain; the solver imposes Q = \u1e41 / \u03c1 (\u03c1: Physics > "
                                "Reference density)")
        self.ip_mass.editingFinished.connect(lambda: self._commit_boundary(inlet={"mass_flow": self.ip_mass.value()}))
        self._layout.addWidget(self._make_row("ip_mass", "Mass flow", self.ip_mass))
        self.ip_p0 = _spin(-PRESSURE_RANGE, PRESSURE_RANGE, 3, " Pa")
        self.ip_p0.setToolTip("Total pressure p + 0.5 rho |U|^2, gauge (relative to the outlets' reference)")
        self.ip_p0.editingFinished.connect(lambda: self._commit_boundary(inlet={"total_pressure": self.ip_p0.value()}))
        self._layout.addWidget(self._make_row("ip_p0", "Total pressure", self.ip_p0))
        self.ip_intensity = _spin(0.01, 100.0, 2, " %")
        self.ip_intensity.setToolTip("Turbulence intensity u'/U at the inlet: k = 1.5 (I |U|)^2")
        self.ip_intensity.editingFinished.connect(
            lambda: self._commit_boundary(inlet={"turbulence_intensity": self.ip_intensity.value() / 100.0}))
        self._layout.addWidget(self._make_row("ip_intensity", "Turbulence intensity", self.ip_intensity))
        self.ip_length = QLineEdit()
        self.ip_length.setPlaceholderText(f"auto: {LENGTH_SCALE_OF_DH:g} x D_h")
        self.ip_length.setToolTip("Turbulence length scale in metres (omega = k^0.5 / (Cmu^0.25 L)); empty: "
                                  f"{LENGTH_SCALE_OF_DH:g} x the patch's hydraulic diameter")
        self.ip_length.editingFinished.connect(self._commit_length_scale)
        self._layout.addWidget(self._make_row("ip_length", "Length scale", self.ip_length))
        self.ip_dh = self._ro_row("ip_dh", "Hydraulic diameter")
        self.ip_dh.setToolTip("D_h = 4 A / P of the patch (2D: twice its width)")
        self.ip_pout = _spin(-PRESSURE_RANGE, PRESSURE_RANGE, 3, " Pa")
        self.ip_pout.setToolTip("Static pressure, gauge; the velocity and turbulence are zero-gradient out and safe on "
                                "backflow (zero velocity, the inlet turbulence)")
        self.ip_pout.editingFinished.connect(lambda: self._commit_boundary(outlet={"pressure": self.ip_pout.value()}))
        self._layout.addWidget(self._make_row("ip_pout", "Static pressure", self.ip_pout))
        self.ip_note = self._ro_row("ip_note", "")
        # the Internal Flow Reports node: planes and pressure drops (dynamic rows, as the probes)
        self._section("ir_planes", "Cutting planes")
        self._section("ir_drops", "Pressure drops")
        self._ir_host = QWidget()
        host_box = QHBoxLayout(self._ir_host)
        host_box.setContentsMargins(0, 0, 0, 0)
        self.ir_add_plane = QPushButton("Add plane")
        self.ir_add_plane.setToolTip("A plane through the middle of the parts, normal to their longest extent")
        self.ir_add_plane.clicked.connect(self._add_plane)
        self.ir_add_drop = QPushButton("Add pressure drop")
        self.ir_add_drop.setToolTip("Between two inlets, outlets or planes (mass-averaged, upstream minus downstream)")
        self.ir_add_drop.clicked.connect(self._add_drop)
        host_box.addWidget(self.ir_add_plane)
        host_box.addWidget(self.ir_add_drop)
        host_box.addStretch(1)
        self._layout.addWidget(self._ir_host)
        self._ir_box = QVBoxLayout()
        self._ir_box.setContentsMargins(0, 0, 0, 0)
        self._ir_box.setSpacing(0)
        self._layout.addLayout(self._ir_box)
        self._ir_rows: list[QWidget] = []
        self._ir_titles: list = []
        self._ir_shape: tuple | None = None
        self.ir_widgets: dict[str, list[dict]] = {"planes": [], "drops": []}

    # -- the patch node ---------------------------------------------------------------------------

    def _internal_keys(self) -> list[str]:
        return ["ip_patch", "ip_role", "ip_kind", "ip_speed", "ip_mass", "ip_p0", "ip_intensity", "ip_length", "ip_dh",
                "ip_pout", "ip_note"]

    def _selected_patch(self):
        if self._kind != "internal_patch" or self._index is None:
            return None
        patches = internal.patches(self._project)
        return patches[self._index] if 0 <= self._index < len(patches) else None

    def _refresh_internal(self) -> None:
        patch = self._selected_patch()
        self._sections["ip_section"].setVisible(patch is not None)
        for key in self._internal_keys():
            self._rows[key].setVisible(False)
        self._refresh_internal_reports(self._kind == "internal_reports")
        if patch is None:
            return
        entry = self._project.sim.boundary(patch.name)
        widgets = (self.ip_role, self.ip_kind, self.ip_speed, self.ip_mass, self.ip_p0, self.ip_intensity, self.ip_length,
                   self.ip_pout)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.ip_role.setCurrentIndex(PATCH_ROLES.index(entry.role))
            self.ip_kind.setCurrentIndex(INLET_KINDS.index(entry.inlet.kind))
            self.ip_speed.setValue(entry.inlet.speed)
            self.ip_mass.setValue(entry.inlet.mass_flow)
            self.ip_p0.setValue(entry.inlet.total_pressure)
            self.ip_intensity.setValue(100.0 * entry.inlet.turbulence_intensity)
            self.ip_length.setText("" if entry.inlet.length_scale is None else f"{entry.inlet.length_scale:.6g}")
            self.ip_pout.setValue(entry.outlet.pressure)
        finally:
            for w in widgets:
                w.blockSignals(False)
        part = self._project.sim.geometry.parts[patch.part]
        self.ip_patch.setText(f"{patch.name} (part {part.name}; mesh patch {patch.safe})")
        visible = ["ip_patch", "ip_role"]
        if entry.role == "inlet":
            visible += ["ip_kind", {"velocity": "ip_speed", "mass_flow": "ip_mass", "total_pressure": "ip_p0"}[entry.inlet.kind],
                        "ip_intensity", "ip_length", "ip_dh", "ip_note"]
            self.ip_note.setText(KIND_TIPS[entry.inlet.kind])
            self.ip_dh.setText(self._dh_text(patch.safe, entry.inlet))
        elif entry.role == "outlet":
            visible += ["ip_pout", "ip_note"]
            self.ip_note.setText("Static-pressure outlet: p fixed; velocity and turbulence zero-gradient, safe on backflow.")
        else:
            visible += ["ip_note"]
            self.ip_note.setText("Wall: no slip, wall functions; the patch gets the prism layers.")
        for key in visible:
            self._rows[key].setVisible(True)

    def _dh_text(self, safe: str, spec) -> str:
        try:
            _names, meshes = meshing._body_parts(self._project)
            measures = internal.inlet_measures(self._project, meshes).get(safe)
        except Exception:  # an unloadable part: not available
            measures = None
        if measures is None:
            return "—"
        length = internal.length_scale(spec, measures.hydraulic_diameter)
        tag = "set" if spec.length_scale is not None else f"auto, {LENGTH_SCALE_OF_DH:g} D_h"
        return (f"{measures.hydraulic_diameter:.5g} m (area {measures.area:.5g} m²); length scale {length:.4g} m "
                f"({tag})")

    def _commit_length_scale(self) -> None:
        text = self.ip_length.text().strip().replace(",", ".")
        if not text:
            self._commit_boundary(inlet={"length_scale": None})
            return
        try:
            value = float(text)
        except ValueError:
            self.message.emit("Length scale: a number in metres, or empty for automatic")
            self.refresh()
            return
        self._commit_boundary(inlet={"length_scale": value})

    def _commit_boundary(self, role: str | None = None, inlet: dict | None = None, outlet: dict | None = None) -> None:
        patch = self._selected_patch()
        if patch is None:
            return
        try:
            self._project.update_boundary(patch.name, role=role, inlet=inlet, outlet=outlet)
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    # -- the reports node: planes and pressure drops --------------------------------------------------

    def _ir_row(self, text: str, field: QWidget) -> None:
        row = QWidget()
        row.setObjectName("propRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QHBoxLayout(row)
        box.setContentsMargins(*self._row_margins)
        from vortexcfd.gui.properties_panel import ElidedLabel

        title = ElidedLabel(text)
        title.setObjectName("muted")
        box.addWidget(title)
        box.addWidget(field, 1)
        if isinstance(field, QLineEdit):
            field.setMinimumHeight(metrics().field)
            field.setMinimumWidth(1)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            set_text_role(field, "value")
        row.setMinimumHeight(self._row_min_height)
        self._ir_titles.append((row, title))
        self._ir_box.addWidget(row)
        row.show()
        self._ir_rows.append(row)

    def _ir_heading(self, text: str) -> None:
        label = QLabel(text.upper())
        label.setObjectName("subSection")
        self._ir_box.addWidget(label)
        label.show()
        self._ir_rows.append(label)

    def _locations(self) -> list[str]:
        return solving.report_locations(self._project)[0]

    def _build_internal_report_rows(self, n_planes: int, n_drops: int, locations: list[str]) -> None:
        for row in self._ir_rows:
            self._ir_box.removeWidget(row)
            row.hide()
            discard(row)
        self._ir_rows, self._ir_titles = [], []
        self.ir_widgets = {"planes": [], "drops": []}
        self._ir_shape = (n_planes, n_drops, tuple(locations))
        if n_planes or n_drops:
            self._ir_heading("Cutting planes" if n_planes else "No cutting planes")
        for i in range(n_planes):
            remove = QPushButton("Remove")
            remove.setObjectName("tbBtn")
            remove.clicked.connect(lambda _=False, n=i: self._edit_internal_reports("planes", lambda v: v.pop(n)))
            self._ir_row(f"Plane {i + 1}", remove)
            widgets = {"remove": remove}
            for key, label, tip in (("name", "Name", "Letters, digits and _, starting with a letter"),
                                    ("point", "Point", "x y z in metres: a point of the plane"),
                                    ("normal", "Normal", "x y z: the plane's normal; the flow is positive along it")):
                edit = QLineEdit()
                edit.setToolTip(tip)
                edit.editingFinished.connect(lambda n=i, k=key: self._commit_plane(n, k))
                self._ir_row(label, edit)
                widgets[key] = edit
            self.ir_widgets["planes"].append(widgets)
        if n_drops:
            self._ir_heading("Pressure drops")
        for i in range(n_drops):
            remove = QPushButton("Remove")
            remove.setObjectName("tbBtn")
            remove.clicked.connect(lambda _=False, n=i: self._edit_internal_reports("pressure_drops", lambda v: v.pop(n)))
            self._ir_row(f"Pressure drop {i + 1}", remove)
            name = QLineEdit()
            name.setToolTip("Letters, digits and _, starting with a letter; used in the report names")
            name.editingFinished.connect(lambda n=i: self._commit_drop(n, "name"))
            self._ir_row("Name", name)
            widgets = {"remove": remove, "name": name}
            for key, label in (("upstream", "Upstream"), ("downstream", "Downstream")):
                combo = QComboBox()
                for loc in locations:
                    combo.addItem(loc.replace(":", " "), loc)
                combo.currentIndexChanged.connect(lambda _i, n=i, k=key: self._commit_drop(n, k))
                self._ir_row(label, combo)
                widgets[key] = combo
            self.ir_widgets["drops"].append(widgets)
        self._apply_label_column()

    def _refresh_internal_reports(self, show: bool) -> None:
        self._sections["ir_planes"].setVisible(False)
        self._sections["ir_drops"].setVisible(False)
        self._ir_host.setVisible(show)
        reports = self._project.sim.reports
        planes = reports.planes if show else []
        drops = reports.pressure_drops if show else []
        locations = self._locations() if show else []
        if (len(planes), len(drops), tuple(locations)) != self._ir_shape:
            self._build_internal_report_rows(len(planes), len(drops), locations)
        for row in self._ir_rows:
            row.setVisible(show)
        from vortexcfd.gui.properties_panel import format_vector

        for plane, w in zip(planes, self.ir_widgets["planes"]):
            for edit, text in ((w["name"], plane.name), (w["point"], format_vector(plane.point)),
                               (w["normal"], format_vector(plane.normal))):
                edit.blockSignals(True)
                edit.setText(text)
                edit.blockSignals(False)
        for drop, w in zip(drops, self.ir_widgets["drops"]):
            for widget in w.values():
                widget.blockSignals(True)
            w["name"].setText(drop.name)
            for key in ("upstream", "downstream"):
                combo, value = w[key], getattr(drop, key)
                if combo.findData(value) < 0:
                    combo.addItem(f"{value.replace(':', ' ')} (not found)", value)
                combo.setCurrentIndex(combo.findData(value))
            for widget in w.values():
                widget.blockSignals(False)

    def _edit_internal_reports(self, key: str, mutate) -> None:
        reports = self._project.sim.reports
        values = [v.model_dump() for v in getattr(reports, key)]
        try:
            mutate(values)
            self._project.update_reports(**{key: values})
        except (ValueError, TypeError, IndexError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    def _commit_plane(self, index: int, key: str) -> None:
        from vortexcfd.gui.properties_panel import parse_vector

        if index >= len(self.ir_widgets["planes"]):
            return
        text = self.ir_widgets["planes"][index][key].text()

        def mutate(planes: list[dict]) -> None:
            if key == "name":
                planes[index]["name"] = text.strip()
                return
            vector = parse_vector(text)
            if vector is None:
                raise ValueError(f"Plane {key}: expected three numbers (x y z)")
            planes[index][key] = vector

        self._edit_internal_reports("planes", mutate)

    def _commit_drop(self, index: int, key: str) -> None:
        if index >= len(self.ir_widgets["drops"]):
            return
        widget = self.ir_widgets["drops"][index][key]
        value = widget.text().strip() if key == "name" else widget.currentData()

        def mutate(drops: list[dict]) -> None:
            drops[index][key] = value

        self._edit_internal_reports("pressure_drops", mutate)

    def _add_plane(self) -> None:
        taken = {p.name for p in self._project.sim.reports.planes}
        n = 1
        while f"plane{n}" in taken:
            n += 1
        try:
            _box, _names, b = meshing.parts_layout(self._project)
        except meshing.MeshingNotReady:
            b = None
        if b is None:
            point, normal = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
        else:
            extents = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
            axis = max(range(3), key=lambda k: extents[k])
            point = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)
            normal = tuple(1.0 if k == axis else 0.0 for k in range(3))
        self._edit_internal_reports("planes", lambda v: v.append({"name": f"plane{n}", "point": point,
                                                                    "normal": normal}))

    def _add_drop(self) -> None:
        locations = self._locations()
        if len(locations) < 2:
            self.message.emit("A pressure drop needs two locations: set an inlet and an outlet first")
            return
        taken = {d.name for d in self._project.sim.reports.pressure_drops}
        n = 1
        while f"dp{n}" in taken:
            n += 1
        roles = internal.open_patches(self._project)
        inlets = [f"patch:{p}" for p, role in roles if role == "inlet"]
        outlets = [f"patch:{p}" for p, role in roles if role == "outlet"]
        upstream = inlets[0] if inlets else locations[0]
        downstream = outlets[0] if outlets else locations[-1]
        self._edit_internal_reports("pressure_drops", lambda v: v.append({"name": f"dp{n}", "upstream": upstream,
                                                                            "downstream": downstream}))
