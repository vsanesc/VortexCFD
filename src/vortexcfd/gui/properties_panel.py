"""Properties panel: edits the node selected in the simulation tree through the Project."""

from typing import get_args

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vortexcfd.core.model import Domain, Part
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.mesh_case import safe_part_names
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.gui.scene import ERROR, MISSING, NONE, OK, domain_box_for, part_status, report_for_part
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, mono_font, section_title_font

# Allowed units are read from the model so the two never drift apart.
ALLOWED_UNITS: tuple[str, ...] = get_args(Part.model_fields["units"].annotation)


DOMAIN_SYMMETRY = get_args(Domain.model_fields["symmetry"].annotation)

def _spin(low: int, high: int, suffix: str = "", special: str | None = None) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    if special:
        box.setSpecialValueText(special)
    return box


def _dspin(low: float, high: float, decimals: int, suffix: str = "", special: str | None = None) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    if special:
        box.setSpecialValueText(special)
    return box


# Editable Mesh settings: (Mesh field, label, widget factory). "auto" is the minimum special
# value of the optional fields (stored as None).
MESH_SETTINGS = (
    ("background_cells_target", "Background cells target", lambda: _spin(1000, 100_000_000, " cells")),
    ("target_surface_size", "Target surface size", lambda: _dspin(0.0001, 1.0, 4, " L")),
    ("base_size", "Base size override", lambda: _dspin(0.0, 1000.0, 5, " m", "auto")),
    ("surface_level_min", "Min surface level", lambda: _spin(-1, 30, "", "auto")),
    ("surface_level_max", "Max surface level", lambda: _spin(-1, 30, "", "auto")),
    ("feature_angle", "Feature angle", lambda: _dspin(1.0, 180.0, 1, "\u00b0")),
    ("layers", "Layers", lambda: _spin(0, 20)),
    ("expansion_ratio", "Expansion ratio", lambda: _dspin(1.0, 3.0, 3)),
    ("final_layer_thickness", "Final layer thickness", lambda: _dspin(0.001, 5.0, 3, " \u00d7 cell")),
    ("min_thickness", "Min layer thickness", lambda: _dspin(0.001, 5.0, 3, " \u00d7 cell")),
)
MESH_OPTIONAL = frozenset({"base_size", "surface_level_min", "surface_level_max"})

# Rows of the read-only mesh report on the Mesh node: (key, label).
MESH_ROWS = (
    ("cells", "Cells"),
    ("faces", "Faces"),
    ("points", "Points"),
    ("non_ortho", "Max non-orthogonality"),
    ("skewness", "Max skewness"),
    ("failed", "Failed checks"),
    ("ok", "Mesh OK"),
    ("extruded", "Surface faces with layers"),
    ("status", "Status"),
)

# Rows of the read-only Checks group: (key, label).
CHECK_ROWS = (
    ("triangles", "Triangles"),
    ("points", "Points"),
    ("size", "Size"),
    ("open", "Open edges"),
    ("non_manifold", "Non-manifold edges"),
    ("degenerate", "Degenerate triangles"),
    ("duplicates", "Duplicate faces"),
    ("orientation", "Flipped normals"),
    ("watertight", "Watertight"),
)


class PropertiesPanel(QWidget):
    """Form for the selected node. Never mutates the model: all edits use the Project API.

    The panel does not subscribe to the project; its owner calls ``refresh()`` on changes.
    """

    message = Signal(str)  # short text for the status bar
    pending_changed = Signal()  # an uncommitted name edit appeared or was resolved

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._kind = "root"
        self._index: int | None = None
        self._name_pending = False  # user typed in the name field without committing yet

        self.name_edit = QLineEdit()
        self.source_label = QLineEdit()  # read-only field (import comes in Phase 3)
        self.source_label.setReadOnly(True)
        self.patch_label = QLineEdit()  # name of the part's patch in the mesh (read-only)
        self.patch_label.setReadOnly(True)
        self.units_combo = QComboBox()
        self.units_combo.addItems(ALLOWED_UNITS)
        self.info_label = QLabel("No properties yet")
        self.info_label.setObjectName("muted")

        # Rows: label on the left, value box on the right, 1px divider below.
        self._rows: dict[str, QWidget] = {}
        self._row_layouts: list[QHBoxLayout] = []
        self._labels: list[QLabel] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        for key, text, field in (
            ("name", "Name", self.name_edit),
            ("source", "Source file", self.source_label),
            ("units", "Units", self.units_combo),
            ("patch", "Patch name", self.patch_label),
        ):
            self._layout.addWidget(self._make_row(key, text, field))
        # File status and the read-only "Checks" group (surface report) for a Part.
        self.status_value = QLabel()
        self.status_value.setObjectName("checkValue")
        self._layout.addWidget(self._make_row("status", "File", self.status_value))
        self.checks_title = QLabel("CHECKS")
        self.checks_title.setObjectName("sectionTitle")
        self._layout.addWidget(self.checks_title)
        self.check_values: dict[str, QLabel] = {}
        for key, text in CHECK_ROWS:
            value = QLabel()
            value.setObjectName("checkValue")
            self.check_values[key] = value
            self._layout.addWidget(self._make_row(f"check_{key}", text, value))
        # Far-field domain rows (Fluid Domain node): edited through Project.update_domain.
        self.domain_enabled = QCheckBox()
        self.domain_fields: dict[str, QDoubleSpinBox] = {}
        self._domain_keys = ["enabled"]
        self._layout.addWidget(self._make_row("dom_enabled", "Enabled", self.domain_enabled))
        for key in ("upstream", "downstream", "lateral", "vertical"):
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.5)
            spin.setSuffix(" L")
            spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            self.domain_fields[key] = spin
            self._domain_keys.append(key)
            self._layout.addWidget(self._make_row(f"dom_{key}", key.capitalize(), spin))
            spin.editingFinished.connect(lambda k=key: self._commit_domain(k))
        self.domain_symmetry = QComboBox()
        self.domain_symmetry.addItems(list(DOMAIN_SYMMETRY))
        self._layout.addWidget(self._make_row("dom_symmetry", "Symmetry", self.domain_symmetry))
        self.domain_length = QLineEdit()
        self.domain_length.setReadOnly(True)
        self._layout.addWidget(self._make_row("dom_length", "Reference length L", self.domain_length))
        self.domain_size = QLineEdit()
        self.domain_size.setReadOnly(True)
        self._layout.addWidget(self._make_row("dom_size", "Box size", self.domain_size))
        self.domain_warning = QLabel()
        self.domain_warning.setObjectName("checkValue")
        self.domain_warning.setWordWrap(True)
        self._layout.addWidget(self.domain_warning)
        self.domain_enabled.toggled.connect(lambda _: self._commit_domain("enabled"))
        self.domain_symmetry.currentTextChanged.connect(lambda _: self._commit_domain("symmetry"))
        # Mesh node: editable sizing/layer settings (Project.update_mesh) with computed values
        # shown read-only next to their overrides, then the checkMesh report.
        self.mesh_fields: dict[str, QWidget] = {}
        for key, label, factory in MESH_SETTINGS:
            widget = factory()
            self.mesh_fields[key] = widget
            self._layout.addWidget(self._make_row(f"mset_{key}", label, widget))
            widget.editingFinished.connect(lambda k=key: self._commit_mesh(k))
            if key == "base_size":
                self.mesh_base_used = self._ro_row("mset_base_used", "Base size used")
            if key == "surface_level_max":
                self.mesh_levels_used = self._ro_row("mset_levels_used", "Levels used")
        self.mesh_bg_cells = self._ro_row("mset_bg_cells", "Background cells")
        self.mesh_surface_cells = self._ro_row("mset_surface_cells", "Surface cell size")
        self.mesh_title = QLabel("LAST MESH")
        self.mesh_title.setObjectName("sectionTitle")
        self._layout.addWidget(self.mesh_title)
        # Mesh node: the read-only checkMesh report (or the "No mesh" empty state).
        self._mesh_report: MeshReport | None = None
        self.mesh_values: dict[str, QLabel] = {}
        for key, text in MESH_ROWS:
            value = QLabel()
            value.setObjectName("checkValue")
            self.mesh_values[key] = value
            self._layout.addWidget(self._make_row(f"mesh_{key}", text, value))
        # Layer coverage: one row per part patch, filled in by _refresh_mesh.
        self._row_margins = (0, 0, 0, 0)
        self._layer_rows: list[QWidget] = []
        self.layer_labels: list[QLabel] = []
        self._layer_box = QVBoxLayout()
        self._layer_box.setContentsMargins(0, 0, 0, 0)
        self._layer_box.setSpacing(0)
        self._layout.addLayout(self._layer_box)
        self._mesh_stale = False
        self.mesh_empty = QLabel("No mesh")
        self.mesh_empty.setObjectName("muted")
        self._layout.addWidget(self.mesh_empty)
        self._layout.addWidget(self.info_label)
        self._layout.addStretch(1)
        self.apply_metrics(metrics(), DARK)

        self.name_edit.editingFinished.connect(self._commit_name)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.units_combo.currentTextChanged.connect(self._commit_units)
        self.refresh()

    def _ro_row(self, key: str, text: str) -> QLabel:
        """A read-only value row; returns its label."""
        value = QLabel()
        value.setObjectName("checkValue")
        self._layout.addWidget(self._make_row(key, text, value))
        return value

    def _make_row(self, key: str, text: str, field: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("propRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        label = QLabel(text)
        label.setObjectName("muted")
        box = QHBoxLayout(row)
        box.addWidget(label, 2)
        box.addWidget(field, 3)
        self._rows[key] = row
        self._row_layouts.append(box)
        self._labels.append(label)
        return row

    def apply_metrics(self, m: Metrics, theme: Theme) -> None:
        """Paddings and fonts derived from the font height."""
        self._row_margins = (m.s3, m.s2, m.s3, m.s2)
        for box in self._row_layouts:
            box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
            box.setSpacing(m.s3)
        self.checks_title.setFont(section_title_font(QApplication.font()))
        self.checks_title.setContentsMargins(m.s3, m.s3, m.s3, m.s2)
        mono = mono_font(QApplication.font(), 0.9)
        for label in (*self.check_values.values(), *self.mesh_values.values(), self.status_value):
            label.setFont(mono)
        for widget in (self.name_edit, self.source_label, self.units_combo, self.patch_label,
                       *self.mesh_fields.values()):
            widget.setFont(mono)
        self.mesh_title.setFont(section_title_font(QApplication.font()))
        self.mesh_title.setContentsMargins(m.s3, m.s3, m.s3, m.s2)
        for label in (self.mesh_base_used, self.mesh_levels_used, self.mesh_bg_cells, self.mesh_surface_cells):
            label.setFont(mono)
        self.info_label.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.mesh_empty.setContentsMargins(m.s3, m.s3, m.s3, m.s3)

    def set_project(self, project: Project) -> None:
        self._project = project
        self._name_pending = False
        self.show_node("root", None)

    def show_node(self, kind: str, index: int | None) -> None:
        if self._name_pending and (kind, index) != (self._kind, self._index):
            self._commit_name()  # commit the old node's pending edit before switching
        self._kind = kind
        self._index = index
        self.refresh()

    def refresh(self) -> None:
        """Repopulate from the project without triggering any commit."""
        sim = self._project.sim
        part: Part | None = None
        if self._kind == "part" and self._index is not None:
            if 0 <= self._index < len(sim.geometry.parts):
                part = sim.geometry.parts[self._index]
        show_name = self._kind == "root" or part is not None
        for widget in (self.name_edit, self.source_label, self.units_combo):
            widget.blockSignals(True)
        try:
            if self._kind == "root":
                self.name_edit.setText(sim.name)
            elif part is not None:
                self.name_edit.setText(part.name)
                self.source_label.setText(part.source_file)
                self.units_combo.setCurrentText(part.units)
        finally:
            for widget in (self.name_edit, self.source_label, self.units_combo):
                widget.blockSignals(False)
        for key in ("source", "units", "patch"):
            self._rows[key].setVisible(part is not None)
        if part is not None:
            patches = safe_part_names([p.name for p in sim.geometry.parts])
            self.patch_label.setText(patches[self._index])
        self._refresh_file_info(part)
        self._rows["name"].setVisible(show_name)
        is_domain = self._kind == "fluid_domain"
        self._refresh_domain(is_domain)
        self._refresh_mesh_settings(self._kind == "mesh")
        self._refresh_mesh(self._kind == "mesh")
        self.info_label.setVisible(not show_name and not is_domain and self._kind != "mesh")

    def _mesh_setting_rows(self) -> list[str]:
        keys = [f"mset_{k}" for k, _, _ in MESH_SETTINGS]
        return keys + ["mset_base_used", "mset_levels_used", "mset_bg_cells", "mset_surface_cells"]

    def _refresh_mesh_settings(self, show: bool) -> None:
        for key in self._mesh_setting_rows():
            self._rows[key].setVisible(show)
        self.mesh_title.setVisible(show and self._mesh_report is not None)
        if not show:
            return
        mesh = self._project.sim.mesh
        widgets = list(self.mesh_fields.values())
        for w in widgets:
            w.blockSignals(True)
        try:
            for key, _, _ in MESH_SETTINGS:
                value = getattr(mesh, key)
                widget = self.mesh_fields[key]
                if isinstance(widget, QSpinBox):
                    widget.setValue(widget.minimum() if value is None else value)
                else:
                    widget.setValue(widget.minimum() if value is None else float(value))
        finally:
            for w in widgets:
                w.blockSignals(False)
        box = domain_box_for(self._project)
        if box.bounds is None:
            for label in (self.mesh_base_used, self.mesh_levels_used, self.mesh_bg_cells,
                          self.mesh_surface_cells):
                label.setText("\u2014")
            self._set_warn(self.mesh_bg_cells, False)
            return
        est = estimate_mesh(box.bounds, box.reference_length, mesh)
        auto = "" if est.base_size_overridden else " (computed)"
        self.mesh_base_used.setText(f"{est.base_size:.4g} m{auto}")
        self.mesh_levels_used.setText(
            f"{est.level_min} \u2013 {est.level_max}" + ("" if est.levels_overridden else " (computed)")
        )
        nx, ny, nz = est.cells
        self.mesh_bg_cells.setText(f"{nx} \u00d7 {ny} \u00d7 {nz} = {est.total_cells:,}")
        self._set_warn(self.mesh_bg_cells, est.too_many_cells)
        self.mesh_surface_cells.setText(f"{est.surface_size:.4g} m")

    def _commit_mesh(self, key: str) -> None:
        if self._kind != "mesh":
            return
        widget = self.mesh_fields[key]
        value = widget.value()
        if value == widget.minimum() and key in MESH_OPTIONAL:
            value = None  # the "auto" special value
        try:
            self._project.update_mesh(**{key: value})
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value

    def set_mesh_report(self, report: MeshReport | None) -> None:
        """The checkMesh summary shown on the Mesh node (None: no mesh yet)."""
        self._mesh_report = report
        self.refresh()

    def _refresh_mesh(self, show: bool) -> None:
        report = self._mesh_report
        for key, _ in MESH_ROWS:
            self._rows[f"mesh_{key}"].setVisible(show and report is not None)
        self.mesh_empty.setVisible(show and report is None)
        if not show or report is None:
            self._fill_layer_rows(None)
            return

        def num(value, fmt: str = "{}") -> str:
            return fmt.format(value) if value is not None else "\u2014"

        values = {
            "cells": (num(report.cells), False),
            "faces": (num(report.faces), False),
            "points": (num(report.points), False),
            "non_ortho": (num(report.max_non_orthogonality, "{:.4g}\u00b0"), False),
            "skewness": (num(report.max_skewness, "{:.4g}"), False),
            "failed": (str(report.failed_checks), report.failed_checks > 0),
            "ok": ("yes" if report.mesh_ok else "no", not report.mesh_ok),
            "extruded": (num(report.extruded_percent, "{:g} %"), False),
            "status": (("Mesh out of date", True) if self._mesh_stale else ("Up to date", False)),
        }
        for key, (text, warn) in values.items():
            self.mesh_values[key].setText(text)
            self._set_warn(self.mesh_values[key], warn)
        self._rows["mesh_extruded"].setVisible(show and report.extruded_percent is not None)
        self._fill_layer_rows(report)

    def _fill_layer_rows(self, report: MeshReport | None) -> None:
        """One row per part patch: layers, thickness and coverage (warning below 80 %)."""
        for row in self._layer_rows:
            self._layer_box.removeWidget(row)
            row.deleteLater()
        self._layer_rows, self.layer_labels = [], []
        if report is None:
            return
        for cov in report.layers:
            label = QLabel(
                f"{cov.mesh_layers:g}/{cov.target_layers} layers, {cov.thickness_m:.4g} m, "
                f"{cov.coverage_percent:g} % of target {cov.basis}"
            )
            label.setObjectName("checkValue")
            label.setFont(mono_font(QApplication.font(), 0.9))
            self._set_warn(label, cov.below_threshold)
            row = QWidget()
            row.setObjectName("propRow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box = QHBoxLayout(row)
            box.setContentsMargins(*self._row_margins)
            title = QLabel(f"Layers: {cov.patch}")
            title.setObjectName("muted")
            box.addWidget(title, 2)
            box.addWidget(label, 3)
            self._layer_box.addWidget(row)
            self._layer_rows.append(row)
            self.layer_labels.append(label)

    def set_mesh_stale(self, stale: bool) -> None:
        """The shown mesh no longer matches the project's meshing inputs."""
        self._mesh_stale = stale
        self.refresh()

    def _refresh_domain(self, show: bool) -> None:
        """Populate the domain rows from the project (no commits) and show them if ``show``."""
        keys = [f"dom_{k}" for k in self._domain_keys] + ["dom_symmetry", "dom_length", "dom_size"]
        for key in keys:
            self._rows[key].setVisible(show)
        self.domain_warning.setVisible(show)
        if not show:
            return
        domain = self._project.sim.domain
        widgets = [self.domain_enabled, self.domain_symmetry, *self.domain_fields.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.domain_enabled.setChecked(domain.enabled)
            self.domain_symmetry.setCurrentText(domain.symmetry)
            for key, spin in self.domain_fields.items():
                spin.setValue(getattr(domain, key))
        finally:
            for w in widgets:
                w.blockSignals(False)
        box = domain_box_for(self._project)
        self.domain_length.setText(f"{box.reference_length:.4g} m" if box.bounds else "\u2014")
        self.domain_size.setText(
            " \u00d7 ".join(f"{v:.4g}" for v in box.size) + " m" if box.bounds else "\u2014"
        )
        self.domain_warning.setText("\n".join(box.warnings))
        self._set_warn(self.domain_warning, bool(box.warnings))

    def _commit_domain(self, key: str) -> None:
        if self._kind != "fluid_domain":
            return
        if key == "enabled":
            value = self.domain_enabled.isChecked()
        elif key == "symmetry":
            value = self.domain_symmetry.currentText()
        else:
            value = self.domain_fields[key].value()
        try:
            self._project.update_domain(**{key: value})
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value

    def _refresh_file_info(self, part: Part | None) -> None:
        """File status and the Checks group (shown only for a Part with a loadable file)."""
        status = part_status(self._project, part) if part is not None else NONE
        message = {MISSING: "File not found"}.get(status, "")
        report = report_for_part(self._project, part) if part is not None and status == OK else None
        if status == OK and report is None:
            status, message = ERROR, "Cannot load file"
        self.status_value.setText(message)
        self._set_warn(self.status_value, bool(message))
        self._rows["status"].setVisible(bool(message))
        self.checks_title.setVisible(report is not None)
        for key, _ in CHECK_ROWS:
            self._rows[f"check_{key}"].setVisible(report is not None)
        if report is None:
            return
        size = " \u00d7 ".join(f"{v:.4g}" for v in report.size)
        values = {
            "triangles": (str(report.n_triangles), False),
            "points": (str(report.n_points), False),
            "size": (f"{size} m", False),
            "open": (str(report.open_edges), report.open_edges > 0),
            "non_manifold": (str(report.non_manifold_edges), report.non_manifold_edges > 0),
            "degenerate": (str(report.degenerate_triangles), False),
            "duplicates": (str(report.duplicate_faces), False),
            "orientation": (str(report.inconsistent_orientation), False),
            "watertight": ("yes" if report.watertight else "no", not report.watertight),
        }
        for key, (text, warn) in values.items():
            self.check_values[key].setText(text)
            self._set_warn(self.check_values[key], warn)

    @staticmethod
    def _set_warn(label: QLabel, warn: bool) -> None:
        label.setProperty("warn", "true" if warn else "false")
        label.style().unpolish(label)
        label.style().polish(label)

    def commit_pending(self) -> None:
        """Commit an uncommitted name edit through the Project API (idempotent).

        A rejected value is reverted and reported through ``message``.
        """
        if self._name_pending:
            self._commit_name()

    @property
    def has_pending(self) -> bool:
        return self._name_pending

    def _on_name_edited(self, _text: str) -> None:
        self._name_pending = True
        self.pending_changed.emit()

    def _commit_name(self) -> None:
        was_pending = self._name_pending
        self._name_pending = False
        if was_pending:
            self.pending_changed.emit()
        text = self.name_edit.text()
        try:
            if self._kind == "root":
                self._project.rename(text)
            elif self._kind == "part" and self._index is not None:
                self._project.update_part(self._index, name=text)
        except (ValueError, TypeError, IndexError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value, normalizes a stripped one

    def _commit_units(self, units: str) -> None:
        try:
            if self._kind == "part" and self._index is not None:
                self._project.update_part(self._index, units=units)
        except (ValueError, TypeError, IndexError) as exc:
            self.message.emit(str(exc))
        self.refresh()
