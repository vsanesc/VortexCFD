"""Properties panel: edits the node selected in the simulation tree through the Project."""

from typing import get_args

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QFrame,
    QScrollArea,
    QSizePolicy,
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
from vortexcfd.foam.physics_case import inlet_turbulence
from vortexcfd.gui.meshing import plan_layers_for
from vortexcfd.gui.scene import ERROR, MISSING, NONE, OK, domain_box_for, part_status, report_for_part
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, mono_font, section_title_font

# Allowed units are read from the model so the two never drift apart.
ALLOWED_UNITS: tuple[str, ...] = get_args(Part.model_fields["units"].annotation)


DOMAIN_SYMMETRY = get_args(Domain.model_fields["symmetry"].annotation)

def _spin(low: int, high: int, suffix: str = "", special: str | None = None) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    if special:
        box.setSpecialValueText(special)
    return box


def _dspin(low: float, high: float, decimals: int, suffix: str = "", special: str | None = None) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    if special:
        box.setSpecialValueText(special)
    return box


class SciEdit(QLineEdit):
    """Line edit for a positive number shown in scientific notation (e.g. 1.5e-05)."""

    def __init__(self, suffix: str = "") -> None:
        super().__init__()
        self._suffix = suffix
        self.setValidator(QDoubleValidator(self))

    def value(self) -> float:
        return float(self.text().replace(",", ".").strip() or "nan")

    def setValue(self, value: float) -> None:
        self.setText(f"{value:.6g}")


def _combo(items) -> QComboBox:
    box = QComboBox()
    box.addItems(list(items))
    return box


def _sci(suffix: str = "") -> SciEdit:
    return SciEdit(suffix)


def _widget_get(widget):
    return widget.currentText() if isinstance(widget, QComboBox) else widget.value()


def _widget_set(widget, value) -> None:
    if isinstance(widget, QComboBox):
        widget.setCurrentText(str(value))
    elif isinstance(widget, QSpinBox):
        widget.setValue(int(value))
    elif isinstance(widget, SciEdit):
        widget.setValue(float(value))
    else:
        widget.setValue(float(value))


def _connect_commit(widget, slot) -> None:
    """Commit when a field is edited: combos on change, everything else on editing finished."""
    if isinstance(widget, QComboBox):
        widget.currentTextChanged.connect(lambda _text: slot())
    else:
        widget.editingFinished.connect(slot)


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
    ("layer_sizing", "Layer sizing", lambda: _combo(("relative", "absolute_yplus"))),
    ("target_yplus", "Target y+", lambda: _dspin(0.01, 1000.0, 3)),
)
MESH_OPTIONAL = frozenset({"base_size", "surface_level_min", "surface_level_max"})

# Physics / Inflow / Solvers nodes: model section, update method and editable fields.
GROUPS: dict[str, dict] = {
    "physics": {
        "model": lambda sim: sim.physics, "update": "update_physics",
        "fields": (
            ("flow", "Flow", lambda: _combo(("incompressible_steady",))),
            ("nu", "Kinematic viscosity", lambda: _sci(" m\u00b2/s")),
            ("rho_ref", "Reference density", lambda: _dspin(0.001, 100000.0, 4, " kg/m\u00b3")),
            ("turbulence_model", "Turbulence model", lambda: _combo(("kOmegaSST",))),
        ),
    },
    "inflow": {
        "model": lambda sim: sim.inflow, "update": "update_inflow",
        "fields": (
            ("speed", "Speed", lambda: _dspin(0.001, 10000.0, 3, " m/s")),
            ("alpha_deg", "Angle of attack", lambda: _dspin(-90.0, 90.0, 3, "\u00b0")),
            ("turbulence_intensity", "Turbulence intensity", lambda: _dspin(0.0001, 1.0, 4)),
            ("viscosity_ratio", "Viscosity ratio", lambda: _dspin(0.001, 100000.0, 3)),
        ),
    },
    "solvers": {
        "model": lambda sim: sim.solvers, "update": "update_solver",
        "fields": (
            ("iterations", "Iterations", lambda: _spin(1, 10_000_000)),
            ("write_interval", "Write interval", lambda: _spin(1, 10_000_000)),
            ("relaxation", "Relaxation preset", lambda: _combo(("robust",))),
            ("residual_p", "Residual target p", lambda: _sci()),
            ("residual_u", "Residual target U", lambda: _sci()),
            ("residual_k", "Residual target k", lambda: _sci()),
            ("residual_omega", "Residual target omega", lambda: _sci()),
        ),
    },
}

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


def _wrap(label: QLabel) -> None:
    """A value label that wraps instead of forcing the panel wider than its viewport."""
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


class ElidedLabel(QLabel):
    """Label with a fixed column width: text that does not fit is elided with "…" and the full
    text becomes the tooltip. It never paints outside its own width."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full = text
        self.setMinimumWidth(0)

    def full_text(self) -> str:
        return self._full

    def set_full_width(self) -> None:
        """Stacked layout: the label takes the whole row width and shows its full text."""
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setText(self._full)
        self.setToolTip("")

    def set_column_width(self, width: int) -> None:
        self.setFixedWidth(width)
        available = max(0, width - self.contentsMargins().left() - self.contentsMargins().right())
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, available)
        self.setText(elided)
        self.setToolTip(self._full if elided != self._full else "")


MIN_LABEL_U = 8  # label column width bounds, in u (and a fraction of the panel width)
MAX_LABEL_FRACTION = 0.50
MIN_FIELD_U = 7  # a field is never narrower than this in the side-by-side layout

# First Mesh field of each section header in the Mesh rows.
MESH_SECTIONS = {
    "background_cells_target": "Sizing",
    "surface_level_min": "Refinement",
    "layers": "Layers",
}


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
        _wrap(self.info_label)

        # Rows: label on the left, value box on the right, 1px divider below.
        self._rows: dict[str, QWidget] = {}
        self._row_layouts: list[QHBoxLayout] = []
        self._row_labels: dict[str, ElidedLabel] = {}  # row key -> its label
        self._fields: list[QWidget] = []  # input widgets (kept at a minimum height)
        self._sections: dict[str, QLabel] = {}
        self._label_column = 0
        self.stacked = False
        self._row_fields: dict[str, QWidget] = {}
        # The rows live in a scroll area: they never shrink below their designed height; a
        # vertical scrollbar appears when they do not fit.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("propScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._content = QWidget()
        self._content.setObjectName("panel")
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)
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
        self._section("dom_size", "Size")
        for key in ("upstream", "downstream", "lateral", "vertical"):
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.5)
            spin.setSuffix(" L")
            self.domain_fields[key] = spin
            self._domain_keys.append(key)
            self._layout.addWidget(self._make_row(f"dom_{key}", key.capitalize(), spin))
            spin.editingFinished.connect(lambda k=key: self._commit_domain(k))
        self._section("dom_symmetry", "Symmetry")
        self.domain_symmetry = QComboBox()
        self.domain_symmetry.addItems(list(DOMAIN_SYMMETRY))
        self._layout.addWidget(self._make_row("dom_symmetry", "Symmetry", self.domain_symmetry))
        self._section("dom_computed", "Computed")
        self.domain_length = QLineEdit()
        self.domain_length.setReadOnly(True)
        self._layout.addWidget(self._make_row("dom_length", "Reference length L", self.domain_length))
        self.domain_size = QLineEdit()
        self.domain_size.setReadOnly(True)
        self._layout.addWidget(self._make_row("dom_size", "Box size", self.domain_size))
        self.domain_warning = QLabel()
        self.domain_warning.setObjectName("checkValue")
        _wrap(self.domain_warning)
        self._layout.addWidget(self.domain_warning)
        self.domain_enabled.toggled.connect(lambda _: self._commit_domain("enabled"))
        self.domain_symmetry.currentTextChanged.connect(lambda _: self._commit_domain("symmetry"))
        # Mesh node: editable sizing/layer settings (Project.update_mesh) with computed values
        # shown read-only next to their overrides, then the checkMesh report.
        self.mesh_fields: dict[str, QWidget] = {}
        for key, label, factory in MESH_SETTINGS:
            if key in MESH_SECTIONS:
                self._section(f"mesh_{MESH_SECTIONS[key].lower()}", MESH_SECTIONS[key])
            widget = factory()
            self.mesh_fields[key] = widget
            self._layout.addWidget(self._make_row(f"mset_{key}", label, widget))
            _connect_commit(widget, lambda k=key: self._commit_mesh(k))
            if key == "base_size":
                self.mesh_base_used = self._ro_row("mset_base_used", "Base size used")
            if key == "surface_level_max":
                self.mesh_levels_used = self._ro_row("mset_levels_used", "Levels used")
        self._section("mesh_estimate", "Estimate")
        self.mesh_bg_cells = self._ro_row("mset_bg_cells", "Background cells")
        self.mesh_surface_cells = self._ro_row("mset_surface_cells", "Surface cell size")
        self.mesh_first_layer = self._ro_row("mset_first_layer", "First layer thickness")
        self.mesh_layer_count = self._ro_row("mset_layer_count", "Layers (computed)")
        self.mesh_layer_stack = self._ro_row("mset_layer_stack", "Stack / final layer")
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
        self._row_min_height = 0
        self._layer_titles: list[tuple[QWidget, ElidedLabel]] = []
        self._layer_rows: list[QWidget] = []
        self.layer_labels: list[QLabel] = []
        self._layer_box = QVBoxLayout()
        self._layer_box.setContentsMargins(0, 0, 0, 0)
        self._layer_box.setSpacing(0)
        self._layout.addLayout(self._layer_box)
        self._mesh_stale = False
        self.mesh_empty = QLabel("No mesh")
        self.mesh_empty.setObjectName("muted")
        _wrap(self.mesh_empty)
        self._layout.addWidget(self.mesh_empty)
        # Physics / Inflow / Solvers nodes: editable fields, one generic group each.
        self.group_fields: dict[str, dict[str, QWidget]] = {}
        for gkind, spec in GROUPS.items():
            fields: dict[str, QWidget] = {}
            for key, label, factory in spec["fields"]:
                widget = factory()
                fields[key] = widget
                self._layout.addWidget(self._make_row(f"{gkind}_{key}", label, widget))
                _connect_commit(widget, lambda k=key, g=gkind: self._commit_group(g, k))
            self.group_fields[gkind] = fields
        self._section("inflow_computed", "Computed")
        self.inflow_k = self._ro_row("inflow_k", "Turbulence k")
        self.inflow_omega = self._ro_row("inflow_omega", "Turbulence omega")
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
        label = ElidedLabel(text)
        label.setObjectName("muted")
        box = QHBoxLayout(row)
        box.addWidget(label)  # fixed width, set by _apply_label_column
        box.addWidget(field, 1)
        self._rows[key] = row
        self._row_layouts.append(box)
        self._row_labels[key] = label
        self._row_fields[key] = field
        if isinstance(field, (QLineEdit, QComboBox, QAbstractSpinBox, QCheckBox)):
            self._fields.append(field)
        elif isinstance(field, QLabel):
            _wrap(field)
        return row

    def _section(self, key: str, text: str) -> QLabel:
        """A small section header inside a node's rows."""
        title = QLabel(text.upper())
        title.setObjectName("subSection")
        self._layout.addWidget(title)
        self._sections[key] = title
        return title

    # -- label column -------------------------------------------------------------------

    def _apply_label_column(self) -> None:
        """Lay out the label column.

        Side by side (panel at least 8u + 7u + margins and gap wide, about 17u): label width = the widest visible label, clamped
        to [8u, 50 % of the panel] and such that the field keeps at least 7u; labels that still
        do not fit are elided with "…" and carry the full text as a tooltip, so a label never
        overlaps its field. Narrower panels stack every row instead: label above field.
        """
        m = metrics()
        pairs = [(self._rows[k], lab) for k, lab in self._row_labels.items() if not self._rows[k].isHidden()]
        pairs += [(row, lab) for row, lab in self._layer_titles if not row.isHidden()]
        widest = max((lab.fontMetrics().horizontalAdvance(lab.full_text()) for _, lab in pairs), default=0)
        # A scrollbar's width is always reserved, so the layout does not depend on whether it shows.
        panel_w = max(self.width() - m.s3, 1)
        # Side by side as soon as the real space is there: minimum label + minimum field + the
        # row margins and the gap between them.
        self.stacked = self.width() < (MIN_LABEL_U + MIN_FIELD_U) * m.u + 3 * m.s3
        room_for_field = panel_w - 3 * m.s3 - MIN_FIELD_U * m.u  # keeps the field >= 7u
        column = max(1, min(max(widest + m.s1, MIN_LABEL_U * m.u),
                            int(MAX_LABEL_FRACTION * panel_w), room_for_field))
        self._label_column = column
        every = [*self._rows.items(), *((None, r) for r, _ in self._layer_titles)]
        for row in (r for _, r in every):
            box = row.layout()
            box.setDirection(
                QBoxLayout.Direction.TopToBottom if self.stacked else QBoxLayout.Direction.LeftToRight
            )
            box.setSpacing(m.s1 if self.stacked else m.s3)
            # Explicit minimum heights replace the layout's own: a stacked row needs the label
            # line as well, or its field would be squeezed into a sliver.
            label_h = box.itemAt(0).widget().fontMetrics().height()
            row.setMinimumHeight(m.field + 2 * m.s2 + (label_h + m.s1 if self.stacked else 0))
        for lab in (*self._row_labels.values(), *(l for _, l in self._layer_titles)):
            if self.stacked:
                lab.set_column_width(max(panel_w - 2 * m.s3, 1))  # the row's whole width
            else:
                lab.set_column_width(column)
        self._fit_content_height()

    def _fit_content_height(self) -> None:
        """Make the scroll area aware of the rows' real height (a layout change inside the content
        widget does not resize it by itself), so the scrollbar appears when they do not fit."""
        layout = self._content.layout()
        layout.activate()
        height = layout.minimumSize().height()
        if layout.hasHeightForWidth():
            height = max(height, layout.totalHeightForWidth(max(self._scroll.viewport().width(), 1)))
        self._content.setMinimumHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_label_column()

    def apply_metrics(self, m: Metrics, theme: Theme) -> None:
        """Paddings and fonts derived from the font height."""
        self._row_margins = (m.s3, m.s2, m.s3, m.s2)
        for box in self._row_layouts:
            box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
            box.setSpacing(m.s3)
        mono_fields = mono_font(QApplication.font(), 0.9)
        for field in self._fields:  # inputs and rows never shrink below their designed height
            field.setMinimumHeight(m.field)
            field.setMinimumWidth(1)  # the content (e.g. a spin box's widest value) must not force a width
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            if not isinstance(field, QCheckBox):
                field.setFont(mono_fields)
        self._row_min_height = m.field + 2 * m.s2
        for row in self._rows.values():
            row.setMinimumHeight(m.field + 2 * m.s2)
        sub = section_title_font(QApplication.font())
        sub.setPointSizeF(sub.pointSizeF() * 0.9)
        for title in self._sections.values():
            title.setFont(sub)
            title.setContentsMargins(m.s3, m.s3, m.s3, m.s1)
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
        for label in (self.mesh_base_used, self.mesh_levels_used, self.mesh_bg_cells, self.mesh_surface_cells,
                      self.mesh_first_layer, self.mesh_layer_count, self.mesh_layer_stack, self.inflow_k, self.inflow_omega):
            label.setFont(mono)
        self.info_label.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.mesh_empty.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self._apply_label_column()

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
        self._refresh_groups()
        self._refresh_mesh_settings(self._kind == "mesh")
        self._refresh_mesh(self._kind == "mesh")
        self.info_label.setVisible(
            not show_name and not is_domain and self._kind != "mesh" and self._kind not in GROUPS
        )
        self._apply_label_column()

    def _mesh_setting_rows(self) -> list[str]:
        keys = [f"mset_{k}" for k, _, _ in MESH_SETTINGS]
        return keys + ["mset_base_used", "mset_levels_used", "mset_bg_cells", "mset_surface_cells",
                       "mset_first_layer", "mset_layer_count", "mset_layer_stack"]

    def _refresh_mesh_settings(self, show: bool) -> None:
        for key in self._mesh_setting_rows():
            self._rows[key].setVisible(show)
        for key in ("mesh_sizing", "mesh_refinement", "mesh_layers", "mesh_estimate"):
            self._sections[key].setVisible(show)
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
                if value is None:
                    widget.setValue(widget.minimum())  # the "auto" special value
                else:
                    _widget_set(widget, value)
        finally:
            for w in widgets:
                w.blockSignals(False)
        box = domain_box_for(self._project)
        absolute = mesh.layer_sizing == "absolute_yplus"
        plan = plan_layers_for(self._project, box) if box.bounds is not None and absolute else None
        if plan is not None:
            self.mesh_first_layer.setText(f"{plan.first:.4g} m (for y+ {mesh.target_yplus:g})")
            self.mesh_layer_count.setText(f"{plan.count}" + (" (limit 30)" if plan.warning else ""))
            self.mesh_layer_stack.setText(f"{plan.total:.4g} m / {plan.final:.4g} m")
        else:
            blank = "relative sizing" if not absolute else "\u2014"
            self.mesh_first_layer.setText(blank)
            self.mesh_layer_count.setText(f"{mesh.layers} (set)" if not absolute else "\u2014")
            self.mesh_layer_stack.setText("\u2014")
        warn = plan is not None and plan.warning is not None
        for label in (self.mesh_first_layer, self.mesh_layer_count, self.mesh_layer_stack):
            self._set_warn(label, warn)
        for label in (self.mesh_layer_count, self.mesh_layer_stack):
            label.setToolTip(plan.warning if warn else "")
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

    def _refresh_groups(self) -> None:
        """Show the group of the selected node (Physics, Inflow or Solvers) and fill it."""
        sim = self._project.sim
        for gkind, spec in GROUPS.items():
            show = self._kind == gkind
            for key, _, _ in spec["fields"]:
                self._rows[f"{gkind}_{key}"].setVisible(show)
            if not show:
                continue
            model = spec["model"](sim)
            widgets = list(self.group_fields[gkind].values())
            for w in widgets:
                w.blockSignals(True)
            try:
                for key, _, _ in spec["fields"]:
                    _widget_set(self.group_fields[gkind][key], getattr(model, key))
            finally:
                for w in widgets:
                    w.blockSignals(False)
        inflow = self._kind == "inflow"
        self._sections["inflow_computed"].setVisible(inflow)
        self._rows["inflow_k"].setVisible(inflow)
        self._rows["inflow_omega"].setVisible(inflow)
        if inflow:
            k, omega = inlet_turbulence(sim.inflow.speed, sim.inflow.turbulence_intensity,
                                        sim.physics.nu, sim.inflow.viscosity_ratio)
            self.inflow_k.setText(f"{k:.4g} m\u00b2/s\u00b2")
            self.inflow_omega.setText(f"{omega:.4g} 1/s")

    def _commit_group(self, gkind: str, key: str) -> None:
        if self._kind != gkind:
            return
        value = _widget_get(self.group_fields[gkind][key])
        try:
            getattr(self._project, GROUPS[gkind]["update"])(**{key: value})
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value

    def _commit_mesh(self, key: str) -> None:
        if self._kind != "mesh":
            return
        widget = self.mesh_fields[key]
        value = _widget_get(widget)
        if key in MESH_OPTIONAL and value == widget.minimum():
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
        self._layer_rows, self.layer_labels, self._layer_titles = [], [], []
        if report is None:
            return
        for cov in report.layers:
            label = QLabel(f"{cov.description()} ({cov.thickness_m:.4g} m)")
            label.setObjectName("checkValue")
            label.setFont(mono_font(QApplication.font(), 0.9))
            _wrap(label)
            self._set_warn(label, cov.below_threshold)
            row = QWidget()
            row.setObjectName("propRow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box = QHBoxLayout(row)
            box.setContentsMargins(*self._row_margins)
            title = ElidedLabel(f"Layers: {cov.patch}")
            title.setObjectName("muted")
            box.addWidget(title)
            box.addWidget(label, 1)
            self._layer_titles.append((row, title))
            row.setMinimumHeight(self._row_min_height)
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
        for key in ("dom_size", "dom_symmetry", "dom_computed"):
            self._sections[key].setVisible(show)
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
            " \u00d7 ".join(f"{v:.3g}" for v in box.size) + " m" if box.bounds else "\u2014"
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
