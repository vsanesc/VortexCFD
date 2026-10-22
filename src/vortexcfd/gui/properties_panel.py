"""Properties panel: edits the node selected in the simulation tree through the Project."""

from pathlib import Path
from typing import get_args

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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

from vortexcfd.core.model import (
    DOMAIN_SHAPES,
    RESIDUAL_FIELDS,
    AsymptoticCriterion,
    MeanStableCriterion,
    Domain,
    Part,
    ResidualCriterion,
)
from vortexcfd.core.model import DIMENSION_LABELS, DIMENSIONS, MAX_CURVATURE_LEVELS, Probe, SurfaceRegion
from vortexcfd.core.reports import (PROBE_NAME_RE, criterion_quantities, default_floor, missing_reference,
                                    report_label)
from vortexcfd.foam.forces import MASS_WARNING
from vortexcfd.foam.parallel import CELLS_PER_CORE, EFFICIENT_CORES, physical_cores, recommended_cores
from vortexcfd.foam.wall_fields import case_yplus_histogram
from vortexcfd.foam.yplus import MAX_LAYERS
from vortexcfd.gui.charts import YPlusHistogramChart
from vortexcfd.gui.report_views import ForcesTable
from vortexcfd.foam.convergence import earliest_iteration, window_stats
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.run_record import RunRecord
from vortexcfd.foam.mesh_case import force_report_keys, part_patch_names, wall_patch_names
from vortexcfd.geometry.cad import CadImportError
from vortexcfd.geometry.loader import SurfaceLoadError
from vortexcfd.geometry.regions import RegionError
from vortexcfd.workflow import part_ops, surface_prep
from vortexcfd.foam.physics_case import (
    AREA_BASIS_LABELS,
    CENTRE_AUTO_LABEL,
    LENGTH_AUTO_LABEL,
    inlet_turbulence,
    reference_values,
)
from vortexcfd.workflow.refinement import OVERLAP_NOTE
from vortexcfd.workflow.meshing import (
    MeshingNotReady,
    estimate_with_volumes,
    fluid_location,
    mesh_cores,
    parts_layout,
    plan_layers_for,
    surface_length,
    surface_length_warning,
    thin_part_warnings,
)
from vortexcfd.geometry.domain import SHAPE_LABELS
from vortexcfd.gui.scene import ERROR, MISSING, NONE, OK, domain_box_for, part_file, part_status, report_for_part
from vortexcfd.gui.study_rows import StudyRowsMixin
from vortexcfd.gui.volume_rows import VolumeRowsMixin
from vortexcfd.gui.theme import DARK, Metrics, Theme, metrics, mono_font, section_title_font

# Allowed units are read from the model so the two never drift apart.
ALLOWED_UNITS: tuple[str, ...] = get_args(Part.model_fields["units"].annotation)


DOMAIN_SYMMETRY = get_args(Domain.model_fields["symmetry"].annotation)
# The domain fields each shape uses (D-078) and their labels.
DOMAIN_SHAPE_FIELDS = {
    "box": ("upstream", "downstream", "lateral", "vertical"),
    "bullet": ("radius", "downstream"),
    "c_type": ("radius", "downstream", "lateral"),
}
DOMAIN_FIELD_LABELS = {"upstream": "Upstream", "downstream": "Downstream", "lateral": "Lateral",
                       "vertical": "Vertical", "radius": "Radius"}
# The ground plane of a box domain (D-116): its options and the boundary conditions it gets.
GROUND_MOTIONS = {"stationary": "Stationary wall", "moving": "Moving (free-stream speed along +x)"}
GROUND_POSITIONS = {"parts_min": "Parts' lowest z", "value": "Value"}
GROUND_ROWS = ("dom_ground_enabled", "dom_ground_motion", "dom_ground_position", "dom_ground_z",
               "dom_ground_start", "dom_ground_layers", "dom_ground_bcs")
# The wall start spin box's minimum shows "inlet": no slip strip (D-118).
GROUND_START_INLET = -1e6


def ground_bc_text(motion: str, strip: bool = False) -> str:
    """The ground's boundary conditions as the solver files write them (physics_case.initial_fields)."""
    u = "fixedValue (U_inf, 0, 0)" if motion == "moving" else "noSlip"
    text = (f"U {u}; p zeroGradient; k kqRWallFunction; omega omegaWallFunction; "
            "nut nutUSpaldingWallFunction (the parts' wall functions)")
    if strip:
        text += "; ground_slip ahead of the wall start: slip (the far field's conditions)"
    return text

# The solver's cores are limited to the machine's physical cores (read at start-up, D-063).
PHYSICAL_CORES = physical_cores()


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
    ("target_surface_size", "Target surface size", lambda: _dspin(0.0001, 1.0, 4, " \u00d7 length")),
    ("surface_size_reference", "Surface size length", lambda: _combo(("l_ref", "largest_extent"))),
    ("base_size", "Base size override", lambda: _dspin(0.0, 1000.0, 5, " m", "auto")),
    ("surface_level_min", "Min surface level", lambda: _spin(-1, 30, "", "auto")),
    ("surface_level_max", "Max surface level", lambda: _spin(-1, 30, "", "auto")),
    ("curvature_levels", "Curvature refinement", lambda: _spin(0, MAX_CURVATURE_LEVELS, " levels", "off")),
    ("feature_angle", "Feature angle", lambda: _dspin(1.0, 180.0, 1, "\u00b0")),
    ("layers", "Layers", lambda: _spin(0, MAX_LAYERS)),
    ("expansion_ratio", "Expansion ratio", lambda: _dspin(1.0, 3.0, 3)),
    ("final_layer_thickness", "Final layer thickness", lambda: _dspin(0.001, 5.0, 3, " \u00d7 cell")),
    ("min_thickness", "Min layer thickness", lambda: _dspin(0.001, 5.0, 3, " \u00d7 cell")),
    ("layer_sizing", "Layer sizing", lambda: _combo(("relative", "absolute_yplus"))),
    ("target_yplus", "Target y+", lambda: _dspin(0.01, 1000.0, 3)),
    ("layer_controls", "Layer controls", lambda: _combo(("robust", "wall_resolved", "legacy"))),
    ("cores", "Mesh cores", lambda: _spin(0, PHYSICAL_CORES, "", "auto")),
)
MESH_OPTIONAL = frozenset({"base_size", "surface_level_min", "surface_level_max", "cores"})
# Tooltip of the Mesh cores field (D-111).
MESH_CORES_TIP = ("snappyHexMesh ranks. auto: the recommendation from the estimated background cells (12,500 per "
                  "core, at most 8). Meshing scales better than the solver; it can use more cores. 1 meshes in "
                  "serial; with more the mesh is reconstructed into one serial mesh afterwards.")
# Reference Values node (D-047): the note under the auto (bounding box) values.
REFERENCE_NOTE = "set the wing area and mean chord for aircraft"
AREA_BASES = ("planform", "frontal", "custom")
REFERENCE_ROWS = ("ref_rho", "ref_u", "ref_basis", "ref_area", "ref_length", "ref_cofr", "ref_area_used",
                  "ref_length_used", "ref_cofr_used")


def parse_vector(text: str) -> tuple[float, float, float] | None:
    """"x y z" (spaces, commas or semicolons; parentheses allowed) -> a vector; "" or "auto" -> None.

    Raises:
        ValueError: anything else.
    """
    clean = text.strip().strip("()").strip()
    if clean.lower() in ("", "auto"):
        return None
    parts = [x for x in clean.replace(",", " ").replace(";", " ").split() if x]
    if len(parts) != 3:
        raise ValueError(f"Centre of rotation: expected three numbers (x y z), got '{text}'")
    return tuple(float(x) for x in parts)  # type: ignore[return-value]


def format_vector(v) -> str:
    return " ".join(f"{x:.6g}" for x in v)


# Shown under Target y+ with absolute (y+) layer sizing (D-024).
YPLUS_NOTE = ("Flat-plate verification: Cf about 6% low at y+ 1, about 3.6% low at y+ 0.5 "
              "(docs/validation/flat_plate)")
# Tooltip of the disabled Layers field with absolute layer sizing (D-089).
LAYERS_ABSOLUTE_TIP = ("Absolute (y+) layer sizing: the layer count follows from the target y+ and the surface "
                       "cell size; it is shown here and cannot be set. Choose relative sizing to set it.")
# Added to the Target y+ tooltip with absolute layer sizing: the usual targets (owner review of 5.4b).
# The angle of attack rotates the parts (D-120).
ALPHA_TOOLTIP = ("Turns the parts nose up about the y axis through the centre of rotation (Reference Values > CofR); "
                 "the free stream stays along +x, lift is +z and drag +x. A change puts the mesh out of date; the "
                 "project's geometry itself is not changed.")
YPLUS_GUIDANCE = ("Wall-resolved (no wall functions): about 1 at the first cell centre. Wall functions: 30-300; "
                  "the default is 50.")
# Tooltip of the Target y+ field with absolute layer sizing, by Mesh.yplus_at (D-107), then YPLUS_GUIDANCE.
YPLUS_AT_TIPS = {
    "cell_centre": ("The target y+ is placed at the first cell centre, where OpenFOAM evaluates y+: the first "
                    "layer is twice the target wall distance."),
    "cell_height": ("This project was saved before the y+ convention changed: the target wall distance is used "
                    "as the first-layer height, so OpenFOAM reports about half the target y+ (at the first cell "
                    "centre)."),
}
# Tooltip of the disabled Target y+ field with relative layer sizing (D-086).
YPLUS_RELATIVE_TIP = ("Relative layer sizing: the layer thickness follows the surface cell size, so y+ is not "
                      "targeted. Choose absolute_yplus to size the layers for this y+.")

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
            ("cores", f"Cores ({PHYSICAL_CORES} physical)", lambda: _spin(1, PHYSICAL_CORES)),
            ("relaxation", "Relaxation preset", lambda: _combo(("robust",))),
        ),
    },
}

# Stopping Criteria node (D-058): static rows and their tooltips.
STOPPING_ROWS = ("stop_combine", "stop_min", "stop_max", "stop_osc_threshold", "stop_osc_window")
STOPPING_TOOLTIPS = {
    "combine": "all: the run stops when every criterion is met in the same iteration; any: when one is",
    "min": "No criterion may stop the run before this iteration",
    "max": "The iteration limit (endTime): always applies",
    "osc_threshold": "Warn when a monitored quantity's (max - min) / max(|mean|, floor) over the window "
                     "exceeds this while its mean is not drifting (a warning only, never a stop)",
    "osc_window": "Iterations over which the oscillation is measured",
    "residual": "Stop when the initial residual of the field (U: its largest component) falls below the "
                "threshold (runTimeControl equationInitialResidual)",
    "asymptotic": "Stop when (max - min) / max(|mean|, floor) over the last N iterations <= tolerance "
                  "(evaluated by the app, which then stops the solver cleanly)",
    "mean_stable": "Stop when the mean over the last N iterations differs from the mean over the N before by "
                   "at most the tolerance, relative to max(|mean|, floor): for a steady run that oscillates "
                   "about a stationary mean (evaluated by the app, which then stops the solver cleanly)",
}
CRITERION_TITLES = {"residual": "Residual", "asymptotic": "Asymptotic", "mean_stable": "Mean stable"}
NO_CRITERIA = "No criteria: the run stops at the iteration limit"

# Rows of the read-only mesh report on the Mesh node: (key, label).
MESH_ROWS = (
    ("cells", "Cells"),
    ("faces", "Faces"),
    ("points", "Points"),
    ("non_ortho", "Max non-orthogonality"),
    ("skewness", "Max skewness"),
    ("failed", "Failed checks"),
    ("ok", "Mesh OK"),
    ("lost", "Lost parts"),
    ("extruded", "Surface faces with layers"),
    ("first_cell", "First cell at the wall"),
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
    ("intersections", "Self-intersections"),
    ("crossings", "Other parts crossed"),
    ("normals", "Normals"),
    ("watertight", "Watertight"),
)


def layer_plan_text(plan) -> str:
    """The Planned / achievable row of a y+ layer plan: both stack thicknesses, the share reached and
    the expansion ratio written (raised by the layer cap, D-106)."""
    ratio = f"ratio {plan.expansion:.3g}" + (f" (set {plan.planned_expansion:.3g})" if plan.expansion != plan.planned_expansion else "")
    return (f"{plan.planned_total:.4g} m / {plan.total:.4g} m ({plan.thickness_percent:.0f} %), {ratio}")


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

    def set_full_text(self, text: str) -> None:
        """Change the label (the column layout elides it again on the next pass)."""
        self._full = text
        self.setText(text)

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
    "cores": "Parallel",
}


class PropertiesPanel(StudyRowsMixin, VolumeRowsMixin, QWidget):
    """Form for the selected node. Never mutates the model: all edits use the Project API.

    The panel does not subscribe to the project; its owner calls ``refresh()`` on changes.
    """

    message = Signal(str)  # short text for the status bar
    pending_changed = Signal()  # an uncommitted name edit appeared or was resolved
    study_run_requested = Signal(str)  # "mesh" or "polar": Run / Stop on a study node (D-066, D-067)
    study_results_requested = Signal(str)
    regions_selected = Signal(int, list)  # part index, selected region names (viewer highlight, D-071)
    generate_domain_requested = Signal()  # the Generate domain button (D-078)
    prepare_surfaces_requested = Signal()  # the Surface Preparation node's buttons (D-093)
    remove_surface_prep_requested = Signal()
    volume_action = Signal(str)  # refinement volumes (D-103): "add:<shape>", "wake", "duplicate", "delete"
    volume_preview = Signal(object)  # a RefinementVolume being edited (drawn uncommitted), None: back to the project
    # part index, linear (m) or None, angular (deg) or None: re-tessellate on the worker (D-073)
    retessellate_requested = Signal(int, object, object)

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
        self.dimension_combo = QComboBox()  # the analysis dimension of the Simulation node (D-121)
        for key in DIMENSIONS:
            self.dimension_combo.addItem(DIMENSION_LABELS[key], key)
        self.dimension_combo.setToolTip("2D section: the parts' section in the x-z plane meshed as one cell across the "
                                        "span (y) with empty front and back; forces per unit span, A_ref = chord x "
                                        "span. A change puts the mesh out of date.")
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
            ("dimension", "Analysis", self.dimension_combo),
        ):
            self._layout.addWidget(self._make_row(key, text, field))
        # Per-part surface refinement levels (D-052): -1 is the "auto" special value (None).
        self.part_level_fields: dict[str, QSpinBox] = {}
        for key, text in (("surface_level_min", "Surface level min"), ("surface_level_max", "Surface level max")):
            spin = _spin(-1, 30, "", "auto")
            spin.setToolTip("This part's surface refinement level (auto: the Mesh levels). A part that is small "
                            "compared with the background cells is seeded automatically at these levels.")
            self.part_level_fields[key] = spin
            self._layout.addWidget(self._make_row(f"part_{key}", text, spin))
            spin.editingFinished.connect(lambda k=key: self._commit_part_level(k))
        # 2D section source (D-121): the airfoil file the part was built from (read-only).
        self.section_label = QLineEdit()
        self.section_label.setReadOnly(True)
        self.section_label.setToolTip("The airfoil coordinate file, its format, scale and trailing-edge closure; the "
                                      "2D mode meshes the part's section (its cut at mid y)")
        self._layout.addWidget(self._make_row("part_section", "2D section", self.section_label))
        # CAD source (Task 3.2, D-070): the file and the tessellation deflections; editing a
        # deflection re-tessellates the part as one undoable step.
        self.cad_file_label = QLineEdit()
        self.cad_file_label.setReadOnly(True)
        self._layout.addWidget(self._make_row("cad_file", "CAD file", self.cad_file_label))
        self.cad_linear = _sci()
        self.cad_linear.setToolTip("Largest distance between a triangle and the CAD surface (m)")
        self._layout.addWidget(self._make_row("cad_linear", "Linear deflection (m)", self.cad_linear))
        self.cad_angular = _dspin(0.1, 90.0, 1, " deg")
        self.cad_angular.setToolTip("Largest angle between the normals of neighbouring triangles")
        self._layout.addWidget(self._make_row("cad_angular", "Angular deflection", self.cad_angular))
        self.cad_linear.editingFinished.connect(lambda: self._commit_cad("linear"))
        self.cad_angular.editingFinished.connect(lambda: self._commit_cad("angular"))
        # Regions of a Part (Task 3.5, D-071): list (multi-select; also selected by picking in the
        # viewer), rename, merge, split by feature angle, patch assignment.
        self._section("regions", "Regions")
        self.region_list = QListWidget()
        self.region_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.region_list.setObjectName("regionList")
        self.region_list.setMinimumHeight(96)
        self.region_list.itemSelectionChanged.connect(self._on_region_selection)
        self._regions_host = QWidget()
        box = QVBoxLayout(self._regions_host)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.region_list)
        self._layout.addWidget(self._regions_host)
        self.region_name = QLineEdit()
        self.region_name.setToolTip("Name of the selected region")
        self.region_name.editingFinished.connect(self._commit_region_name)
        self._layout.addWidget(self._make_row("region_name", "Region name", self.region_name))
        self.region_patch = QLineEdit()
        self.region_patch.setPlaceholderText("part patch")
        self.region_patch.setToolTip("Mesh patch of the selected regions (empty: the part's own patch)")
        self.region_patch.editingFinished.connect(self._commit_region_patch)
        self._layout.addWidget(self._make_row("region_patch", "Patch", self.region_patch))
        self.region_angle = _dspin(1.0, 179.0, 1, " deg")
        self.region_angle.setValue(30.0)
        self.region_angle.setToolTip("Split along edges sharper than this angle")
        self._layout.addWidget(self._make_row("region_angle", "Feature angle", self.region_angle))
        self.region_split = QPushButton("Split")
        self.region_split.setToolTip("Split the selected region (or the whole part) by the feature angle")
        self.region_merge = QPushButton("Merge")
        self.region_merge.setToolTip("Merge the selected regions into the first one")
        self.region_own_patches = QPushButton("Patch per region")
        self.region_own_patches.setToolTip("Put every region on its own patch, named after it")
        self._region_buttons = QWidget()
        buttons = QHBoxLayout(self._region_buttons)
        for button in (self.region_split, self.region_merge, self.region_own_patches):
            button.setObjectName("tbBtn")
            buttons.addWidget(button, 1)
        self._layout.addWidget(self._region_buttons)
        self.geometry_busy = False
        self.request_intersections = None  # callable(path, units): background check (D-073)
        self.request_overlaps = None  # callable(): background check of the parts crossing each other (D-099)
        self.region_split.clicked.connect(self._split_region)
        self.region_merge.clicked.connect(self._merge_regions)
        self.region_own_patches.clicked.connect(self._patch_per_region)
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
        # Far-field domain rows (Fluid Domain node): edited through Project.update_domain. The Domain
        # node of a project whose domain was not generated yet shows the Generate domain button (D-078).
        self.domain_generate = QPushButton("Generate domain\u2026")
        self.domain_generate.setToolTip("Create the far-field domain around the selected parts (shape and sizes)")
        self.domain_generate.clicked.connect(self.generate_domain_requested.emit)
        self._layout.addWidget(self._make_row("dom_generate", "Domain", self.domain_generate))
        self.domain_enabled = QCheckBox()
        self.domain_fields: dict[str, QDoubleSpinBox] = {}
        self._domain_keys = ["enabled"]
        self._layout.addWidget(self._make_row("dom_enabled", "Enabled", self.domain_enabled))
        self.domain_shape = QComboBox()
        for shape in DOMAIN_SHAPES:
            self.domain_shape.addItem(SHAPE_LABELS[shape], shape)
        self.domain_shape.setToolTip("Box; bullet: hemisphere and cylinder along +x; C-type: front half-cylinder "
                                     "with a spanwise axis, flat top, bottom and sides")
        self._layout.addWidget(self._make_row("dom_shape", "Shape", self.domain_shape))
        self.domain_shape.currentIndexChanged.connect(lambda _: self._commit_domain("shape"))
        self._section("dom_size", "Size")
        for key in ("upstream", "downstream", "lateral", "vertical", "radius"):
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.5)
            spin.setSuffix(" L")
            self.domain_fields[key] = spin
            self._domain_keys.append(key)
            self._layout.addWidget(self._make_row(f"dom_{key}", DOMAIN_FIELD_LABELS[key], spin))
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
        self._layout.addWidget(self._make_row("dom_size", "Bounding box", self.domain_size))
        self.domain_volume = self._ro_row("dom_volume", "Volume")
        self.domain_parts = self._ro_row("dom_parts", "Sized around")
        self.domain_warning = QLabel()
        self.domain_warning.setObjectName("checkValue")
        _wrap(self.domain_warning)
        self._layout.addWidget(self.domain_warning)
        self._section("dom_ground", "Ground plane")
        self.ground_enabled = QCheckBox()
        self.ground_enabled.setToolTip("The bottom face (z-min) of the box is a no-slip wall, the patch \"ground\", "
                                       "instead of the slip far field")
        self._layout.addWidget(self._make_row("dom_ground_enabled", "Ground plane", self.ground_enabled))
        self.ground_motion = QComboBox()
        for key, text in GROUND_MOTIONS.items():
            self.ground_motion.addItem(text, key)
        self._layout.addWidget(self._make_row("dom_ground_motion", "Motion", self.ground_motion))
        self.ground_position = QComboBox()
        for key, text in GROUND_POSITIONS.items():
            self.ground_position.addItem(text, key)
        self.ground_position.setToolTip("Where the ground plane lies: at the lowest z of the parts, or at a value "
                                        "(e.g. below the lowest point when supports cross the plane)")
        self._layout.addWidget(self._make_row("dom_ground_position", "Position", self.ground_position))
        self.ground_z = QDoubleSpinBox()
        self.ground_z.setRange(-1e6, 1e6)
        self.ground_z.setDecimals(4)
        self.ground_z.setSingleStep(0.01)
        self.ground_z.setSuffix(" m")
        self._layout.addWidget(self._make_row("dom_ground_z", "z", self.ground_z))
        self.ground_start = QDoubleSpinBox()
        self.ground_start.setRange(GROUND_START_INLET, 1e6)
        self.ground_start.setDecimals(4)
        self.ground_start.setSingleStep(0.01)
        self.ground_start.setSuffix(" m")
        self.ground_start.setSpecialValueText("inlet")
        self.ground_start.setToolTip("x where the ground wall starts. Upstream of it the bottom face is the slip patch "
                                     "\"ground_slip\" (no boundary layer grows there), e.g. where a wind tunnel's "
                                     "ground board starts. Placed on the nearest background cell face. \"inlet\" "
                                     "(the minimum): the wall starts at the inlet")
        self._layout.addWidget(self._make_row("dom_ground_start", "Wall starts at x", self.ground_start))
        self.ground_layers = QCheckBox()
        self.ground_layers.setToolTip("Prism layers on the ground (the parts' stack). Off by default: the ground "
                                      "uses the same wall functions on the castellated cells")
        self._layout.addWidget(self._make_row("dom_ground_layers", "Prism layers", self.ground_layers))
        self.ground_bcs = self._ro_row("dom_ground_bcs", "Boundary conditions")
        self.ground_enabled.toggled.connect(lambda _: self._commit_ground("enabled"))
        self.ground_motion.currentIndexChanged.connect(lambda _: self._commit_ground("motion"))
        self.ground_position.currentIndexChanged.connect(lambda _: self._commit_ground("position"))
        self.ground_z.editingFinished.connect(lambda: self._commit_ground("z"))
        self.ground_start.editingFinished.connect(lambda: self._commit_ground("wall_start_x"))
        self.ground_layers.toggled.connect(lambda _: self._commit_ground("layers"))
        self.domain_enabled.toggled.connect(lambda _: self._commit_domain("enabled"))
        self.domain_symmetry.currentTextChanged.connect(lambda _: self._commit_domain("symmetry"))
        # Surface Preparation node (D-093): its result and report; run / remove.
        self._section("sp_title", "Surface preparation")
        self.sp_strategy = self._ro_row("sp_strategy", "Strategy")
        self.sp_state = self._ro_row("sp_state", "State")
        self.sp_parts = self._ro_row("sp_parts", "Parts")
        self.sp_features = self._ro_row("sp_features", "Intersection curves")
        self.sp_report = self._ro_row("sp_report", "Report")
        sp_buttons = QWidget()
        sp_box = QHBoxLayout(sp_buttons)
        sp_box.setContentsMargins(0, 0, 0, 0)
        self.sp_run = QPushButton("Prepare surfaces\u2026")
        self.sp_run.setToolTip("Diagnose the parts and prepare them for meshing (intersection features or CAD union)")
        self.sp_run.clicked.connect(self.prepare_surfaces_requested.emit)
        self.sp_remove = QPushButton("Remove")
        self.sp_remove.setToolTip("Remove the preparation: the parts mesh as imported (undoable)")
        self.sp_remove.clicked.connect(self.remove_surface_prep_requested.emit)
        sp_box.addWidget(self.sp_run)
        sp_box.addWidget(self.sp_remove)
        self._layout.addWidget(self._make_row("sp_buttons", "Operation", sp_buttons))
        # Fluid Region node: what is meshed, the domain minus the parts (D-078).
        self._section("fr_title", "Fluid region")
        self.fluid_definition = self._ro_row("fr_definition", "Definition")
        self.fluid_domain = self._ro_row("fr_domain", "Domain")
        self.fluid_parts = self._ro_row("fr_parts", "Minus parts")
        self.fluid_location = self._ro_row("fr_location", "Kept side")
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
            if key == "cores":
                widget.setToolTip(MESH_CORES_TIP)
                self.mesh_cores_used = self._ro_row("mset_cores_used", "Cores used")
            if key == "target_yplus":
                self.mesh_yplus_note = QLabel(YPLUS_NOTE)
                self.mesh_yplus_note.setObjectName("muted")
                _wrap(self.mesh_yplus_note)
                self._layout.addWidget(self.mesh_yplus_note)
        self._section("mesh_estimate", "Estimate")
        self.mesh_bg_cells = self._ro_row("mset_bg_cells", "Background cells")
        self.mesh_volume_cells = self._ro_row("mset_volume_cells", "Refinement volumes")
        self.mesh_surface_length = self._ro_row("mset_surface_length", "Surface size from")
        self.mesh_surface_cells = self._ro_row("mset_surface_cells", "Surface cell size")
        self.mesh_curvature = self._ro_row("mset_curvature", "Curvature up to")
        self.mesh_length_warning = QLabel()
        self.mesh_length_warning.setObjectName("checkValue")
        _wrap(self.mesh_length_warning)
        self._layout.addWidget(self.mesh_length_warning)
        self.mesh_first_layer = self._ro_row("mset_first_layer", "First layer thickness")
        self.mesh_layer_count = self._ro_row("mset_layer_count", "Layers (computed)")
        self.mesh_layer_stack = self._ro_row("mset_layer_stack", "Stack / final layer")
        # planned vs achievable stack thickness and the expansion ratio written (layer cap, D-106)
        self.mesh_layer_plan = self._ro_row("mset_layer_plan", "Planned / achievable")
        self.mesh_layer_thickness_warning = QLabel()
        self.mesh_layer_thickness_warning.setObjectName("checkValue")
        _wrap(self.mesh_layer_thickness_warning)
        self._layout.addWidget(self.mesh_layer_thickness_warning)
        self.mesh_thin_warning = QLabel()
        self.mesh_thin_warning.setObjectName("checkValue")
        _wrap(self.mesh_thin_warning)
        self._layout.addWidget(self.mesh_thin_warning)
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
        self.group_fields["inflow"]["alpha_deg"].setToolTip(ALPHA_TOOLTIP)
        self._section("inflow_computed", "Computed")
        self.inflow_k = self._ro_row("inflow_k", "Turbulence k")
        self.inflow_omega = self._ro_row("inflow_omega", "Turbulence omega")
        # Solvers node: the recommended core count for the current mesh (D-064).
        self.solvers_recommended = self._ro_row("solvers_recommended", "Recommended cores")
        self.solvers_recommended.setToolTip(
            f"min(physical cores, cells / {CELLS_PER_CORE:,}, {EFFICIENT_CORES}), at least 1: the measured speedup "
            f"saturates beyond {EFFICIENT_CORES} cores on this machine (docs/validation/parallel/README.md)")
        # Solvers node: the last run (case/vortexcfd_run.json), or "No solver run yet".
        self._run_record: RunRecord | None = None
        self._results_stale = False
        self._section("run_last", "Last run")
        self.run_state = self._ro_row("run_state", "State")
        self.run_iterations = self._ro_row("run_iterations", "Iterations")
        self.run_residuals = self._ro_row("run_residuals", "Final residuals")
        self.run_status = self._ro_row("run_status", "Status")
        # Reference Values node (under Reports & Monitors): forceCoeffs reference values.
        self.ref_rho = _dspin(0.001, 100000.0, 4, " kg/m\u00b3")
        self._layout.addWidget(self._make_row("ref_rho", "Reference density", self.ref_rho))
        self.ref_rho.editingFinished.connect(self._commit_rho)
        self.ref_u = self._ro_row("ref_u", "Reference speed U_ref")
        self.ref_basis = _combo(AREA_BASES)
        self.ref_basis.setToolTip("A_ref: bounding-box planform (x * y), bounding-box frontal (y * z) "
                                  "or a custom value")
        self._layout.addWidget(self._make_row("ref_basis", "A_ref basis", self.ref_basis))
        self.ref_basis.currentTextChanged.connect(lambda _t: self._commit_basis())
        self.ref_area = _dspin(0.0, 1e6, 6, " m\u00b2", "auto")
        self._layout.addWidget(self._make_row("ref_area", "Reference area A_ref", self.ref_area))
        self.ref_area.editingFinished.connect(lambda: self._commit_reference("reference_area"))
        self.ref_length = _dspin(0.0, 1e4, 6, " m", "auto")
        self._layout.addWidget(self._make_row("ref_length", "Reference length l_ref", self.ref_length))
        self.ref_length.editingFinished.connect(lambda: self._commit_reference("reference_length"))
        self.ref_cofr = QLineEdit()
        self.ref_cofr.setPlaceholderText("auto")
        self.ref_cofr.setToolTip("Centre of rotation for the moment coefficient: x y z in metres, "
                                 "empty for auto (centre of the parts' bounding box)")
        self._layout.addWidget(self._make_row("ref_cofr", "Centre of rotation", self.ref_cofr))
        self.ref_cofr.editingFinished.connect(lambda: self._commit_reference("center_of_rotation"))
        self._section("ref_used", "Used")
        self.ref_area_used = self._ro_row("ref_area_used", "A_ref")
        self.ref_length_used = self._ro_row("ref_length_used", "l_ref")
        self.ref_cofr_used = self._ro_row("ref_cofr_used", "CofR")
        self.ref_note = QLabel(REFERENCE_NOTE)
        self.ref_note.setObjectName("muted")
        _wrap(self.ref_note)
        self._layout.addWidget(self.ref_note)
        # Reports & Monitors node (D-060, D-061): latest force breakdown, mass balance, y+ bins.
        self._report_monitor = None  # foam.postprocessing.ReportMonitor of the shown run
        self._report_case: Path | None = None
        self._yplus_cache: tuple | None = None
        self._section("rep_forces", "Forces (latest iteration)")
        self.forces_table = ForcesTable()
        self._forces_host = QWidget()
        self._forces_box = QVBoxLayout(self._forces_host)
        self._forces_box.addWidget(self.forces_table)
        self._layout.addWidget(self._forces_host)
        self._section("rep_mass", "Mass balance")
        self.mass_inlet = self._ro_row("rep_mass_inlet", "Inlet flux sum(phi)")
        self.mass_outlet = self._ro_row("rep_mass_outlet", "Outlet flux sum(phi)")
        self.mass_imbalance = self._ro_row("rep_mass_imbalance", "Imbalance")
        self._section("rep_yplus", "y+ on the walls")
        self.yplus_chart = YPlusHistogramChart()
        self._yplus_host = QWidget()
        self._yplus_box = QVBoxLayout(self._yplus_host)
        self._yplus_box.addWidget(self.yplus_chart)
        self._layout.addWidget(self._yplus_host)
        self.yplus_faces = self._ro_row("rep_yplus_faces", "Wall faces")
        self.reports_empty = QLabel("No solver run yet")
        self.reports_empty.setObjectName("muted")
        _wrap(self.reports_empty)
        self._layout.addWidget(self.reports_empty)
        # Probes node (under Reports & Monitors): one block per probe, Add probe.
        self.probe_add = QPushButton("Add probe")
        self.probe_add.setObjectName("tbBtn")
        self.probe_add.setToolTip("A point probe of p and U, written every iteration (probes function object)")
        self.probe_add.clicked.connect(self._add_probe)
        self._probe_add_host = QWidget()
        self._probe_add_row = QHBoxLayout(self._probe_add_host)
        self._probe_add_row.addWidget(self.probe_add, 1)
        self._layout.addWidget(self._probe_add_host)
        self._probe_box = QVBoxLayout()
        self._probe_box.setContentsMargins(0, 0, 0, 0)
        self._probe_box.setSpacing(0)
        self._layout.addLayout(self._probe_box)
        self._probe_rows: list[QWidget] = []
        self._probe_titles: list[tuple[QWidget, ElidedLabel]] = []
        self._probe_count: int | None = None
        self.probe_widgets: list[dict[str, QWidget]] = []
        self.probes_empty = QLabel("No probes")
        self.probes_empty.setObjectName("muted")
        _wrap(self.probes_empty)
        self._layout.addWidget(self.probes_empty)
        # Stopping Criteria node (under Solvers): combination, limits, oscillation check, criteria.
        self.stop_combine = _combo(("all", "any"))
        self.stop_min = _spin(0, 10_000_000)
        self.stop_max = _spin(1, 10_000_000)
        self.stop_osc_threshold = _dspin(0.01, 1000.0, 2, " %")
        self.stop_osc_window = _spin(4, 10_000_000)
        for key, text, widget in (("combine", "Combine criteria", self.stop_combine),
                                  ("min", "Minimum iterations", self.stop_min),
                                  ("max", "Maximum iterations", self.stop_max),
                                  ("osc_threshold", "Oscillation threshold", self.stop_osc_threshold),
                                  ("osc_window", "Oscillation window", self.stop_osc_window)):
            widget.setToolTip(STOPPING_TOOLTIPS[key])
            self._layout.addWidget(self._make_row(f"stop_{key}", text, widget))
            _connect_commit(widget, lambda k=key: self._commit_stopping_setting(k))
        self._section("stop_criteria", "Criteria")
        self.stop_add = QWidget()  # full width: two buttons sharing the row
        self._stop_add_row = QHBoxLayout(self.stop_add)
        self.stop_add_residual = QPushButton("Add residual")
        self.stop_add_asymptotic = QPushButton("Add asymptotic")
        self.stop_add_mean_stable = QPushButton("Add mean stable")
        for button, kind in ((self.stop_add_residual, "residual"), (self.stop_add_asymptotic, "asymptotic"),
                             (self.stop_add_mean_stable, "mean_stable")):
            button.setObjectName("tbBtn")
            button.setToolTip(STOPPING_TOOLTIPS[kind])
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, k=kind: self._add_criterion(k))
            self._stop_add_row.addWidget(button, 1)
        self._layout.addWidget(self.stop_add)
        self._criteria_box = QVBoxLayout()
        self._criteria_box.setContentsMargins(0, 0, 0, 0)
        self._criteria_box.setSpacing(0)
        self._layout.addLayout(self._criteria_box)
        self._criteria_rows: list[QWidget] = []
        self._criteria_titles: list[tuple[QWidget, ElidedLabel]] = []
        self._criteria_kinds: list[str] = []
        # Per criterion: {"field"/"quantity"/"window"/"threshold"/"tolerance": widget, "remove": button}
        self.criterion_widgets: list[dict[str, QWidget]] = []
        self.stop_empty = QLabel(NO_CRITERIA)
        self.stop_empty.setObjectName("muted")
        _wrap(self.stop_empty)
        self._layout.addWidget(self.stop_empty)
        self.run_empty = QLabel("No solver run yet")
        self.run_empty.setObjectName("muted")
        _wrap(self.run_empty)
        self._layout.addWidget(self.run_empty)
        # Mesh Study and Polar Sweep nodes (under Reports & Monitors; gui/study_rows.py).
        self._build_study_rows(_dspin, _spin, _combo)
        # Refinement volumes node and each volume (under Mesh; gui/volume_rows.py, D-103).
        self._build_volume_rows()
        self._layout.addWidget(self.info_label)
        self._layout.addStretch(1)
        self.apply_metrics(metrics(), DARK)

        self.name_edit.editingFinished.connect(self._commit_name)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.units_combo.currentTextChanged.connect(self._commit_units)
        self.dimension_combo.currentIndexChanged.connect(self._commit_dimension)
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
        pairs += [(row, lab) for row, lab in self._dynamic_titles() if not row.isHidden()]
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
        every = [*self._rows.items(), *((None, r) for r, _ in self._dynamic_titles())]
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
        for lab in (*self._row_labels.values(), *(l for _, l in self._dynamic_titles())):
            if self.stacked:
                lab.set_column_width(max(panel_w - 2 * m.s3, 1))  # the row's whole width
            else:
                lab.set_column_width(column)
        self._fit_content_height()

    def _dynamic_titles(self) -> list[tuple[QWidget, "ElidedLabel"]]:
        """Rows built at refresh time (layer coverage, stopping criteria) with their labels."""
        return [*self._layer_titles, *getattr(self, "_criteria_titles", []), *getattr(self, "_probe_titles", [])]

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
                       self.cad_file_label, self.cad_linear, self.cad_angular, *self.mesh_fields.values()):
            widget.setFont(mono)
        self.mesh_title.setFont(section_title_font(QApplication.font()))
        self.mesh_title.setContentsMargins(m.s3, m.s3, m.s3, m.s2)
        for label in (self.mesh_base_used, self.mesh_levels_used, self.mesh_bg_cells, self.mesh_volume_cells,
                      self.mesh_surface_cells,
                      self.mesh_first_layer, self.mesh_layer_count, self.mesh_layer_stack, self.inflow_k, self.inflow_omega):
            label.setFont(mono)
        self.info_label.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.mesh_empty.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self.stop_empty.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        self._stop_add_row.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        for _host, box in (self._ms_buttons, self._ps_buttons):
            box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
            box.setSpacing(m.s2)
        for button in (self.ms_run, self.ms_results, self.ps_run, self.ps_results, self.ms_quantities):
            button.setMinimumHeight(m.field)
        self._probe_add_row.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self.probe_add.setMinimumHeight(m.field)
        self._forces_box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self._yplus_box.setContentsMargins(m.s3, m.s2, m.s3, m.s2)
        self.forces_table.configure(m.s3)
        self.yplus_chart.configure(theme, 8 * m.u)
        for label in (self.reports_empty, self.probes_empty):
            label.setContentsMargins(m.s3, m.s3, m.s3, m.s3)
        if getattr(self, "_probe_count", None) is not None:
            self._probe_count = None  # rebuilt at the next refresh with the new metrics
        self._stop_add_row.setSpacing(m.s2)
        for button in (self.stop_add_residual, self.stop_add_asymptotic, self.stop_add_mean_stable):
            button.setMinimumHeight(m.field)
        if getattr(self, "_criteria_kinds", None):
            self._criteria_kinds = None  # rebuilt at the next refresh with the new metrics
            self.refresh()
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
        for key in ("source", "units", "patch", "part_surface_level_min", "part_surface_level_max"):
            self._rows[key].setVisible(part is not None)
        sec = part.section if part is not None else None
        self._rows["part_section"].setVisible(sec is not None)
        if sec is not None:
            self.section_label.setText(f"{sec.file} ({sec.name or 'airfoil'}; {sec.format}, scale {sec.scale:g}, "
                                       f"trailing edge {sec.te_closure})")
        self._rows["dimension"].setVisible(self._kind == "root")
        self.dimension_combo.blockSignals(True)
        self.dimension_combo.setCurrentIndex(DIMENSIONS.index(sim.dimension))
        self.dimension_combo.blockSignals(False)
        if part is not None:
            for key, spin in self.part_level_fields.items():
                spin.blockSignals(True)
                value = getattr(part, key)
                spin.setValue(spin.minimum() if value is None else value)
                spin.blockSignals(False)
        if part is not None:
            patches = part_patch_names(sim.geometry.parts)
            self.patch_label.setText(", ".join(patches[self._index]))
        self._refresh_cad(part)
        self._refresh_regions(part)
        self._refresh_file_info(part)
        self._rows["name"].setVisible(show_name)
        is_domain = self._kind in ("fluid_domain", "fluid_region", "boundary_ground")
        self._refresh_domain(self._kind == "fluid_domain")
        self._refresh_ground(self._kind in ("fluid_domain", "boundary_ground"))
        self._refresh_groups()
        self._refresh_run(self._kind == "solvers")
        self._refresh_stopping(self._kind == "stopping")
        self._refresh_reports(self._kind == "reports")
        self._refresh_probes(self._kind == "probes")
        self._refresh_reference(self._kind == "reference_values")
        study_patches, study_probes = self._patches_and_probes() if self._kind == "mesh_study" else ([], [])
        self._refresh_mesh_study(self._kind == "mesh_study", study_patches, study_probes)
        self._refresh_polar(self._kind == "polar_sweep")
        self._refresh_mesh_settings(self._kind == "mesh")
        self._refresh_mesh(self._kind == "mesh")
        self._refresh_volumes()
        self.info_label.setVisible(
            not show_name and not is_domain
            and self._kind not in ("mesh", "reference_values", "stopping", "reports", "probes", "surface_prep",
                                   "prepare_surfaces", "refinement_volumes", "refinement_volume")
            and self._kind not in GROUPS
        )
        self._apply_label_column()

    def _mesh_setting_rows(self) -> list[str]:
        keys = [f"mset_{k}" for k, _, _ in MESH_SETTINGS]
        return keys + ["mset_base_used", "mset_levels_used", "mset_bg_cells", "mset_volume_cells", "mset_surface_length",
                       "mset_surface_cells", "mset_curvature", "mset_first_layer", "mset_layer_count",
                       "mset_layer_stack", "mset_cores_used"]

    def _refresh_mesh_settings(self, show: bool) -> None:
        for key in self._mesh_setting_rows():
            self._rows[key].setVisible(show)
        for key in ("mesh_sizing", "mesh_refinement", "mesh_layers", "mesh_parallel", "mesh_estimate"):
            self._sections[key].setVisible(show)
        self.mesh_title.setVisible(show and self._mesh_report is not None)
        if not show:
            self.mesh_yplus_note.setVisible(False)
            self.mesh_thin_warning.setVisible(False)
            self.mesh_length_warning.setVisible(False)
            return
        thin = thin_part_warnings(self._project)
        self.mesh_thin_warning.setText("\n".join(thin))
        self._set_warn(self.mesh_thin_warning, True)
        self.mesh_thin_warning.setVisible(bool(thin))
        mesh = self._project.sim.mesh
        self.mesh_yplus_note.setVisible(mesh.layer_sizing == "absolute_yplus")
        yplus_used = mesh.layer_sizing == "absolute_yplus"
        self.mesh_fields["target_yplus"].setEnabled(yplus_used)
        self.mesh_fields["target_yplus"].setToolTip(f"{YPLUS_AT_TIPS[mesh.yplus_at]}\n{YPLUS_GUIDANCE}" if yplus_used
                                                    else YPLUS_RELATIVE_TIP)
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
        layers_field = self.mesh_fields["layers"]
        layers_field.setEnabled(not absolute)  # the count follows from y+ and the surface cell (D-089)
        layers_field.setToolTip(LAYERS_ABSOLUTE_TIP if absolute else "")
        if plan is not None:
            layers_field.blockSignals(True)
            layers_field.setValue(plan.count)  # shown only: the stored Mesh.layers is not changed
            layers_field.blockSignals(False)
        if plan is not None:
            self.mesh_first_layer.setText(f"{plan.first:.4g} m (for y+ {mesh.target_yplus:g})")
            notes = [f"cap; planned {plan.planned_count}"] if plan.capped else []
            notes += ["limit 30"] if plan.warning else []
            self.mesh_layer_count.setText(f"{plan.count}" + (f" ({', '.join(notes)})" if notes else ""))
            self.mesh_layer_stack.setText(f"{plan.total:.4g} m / {plan.final:.4g} m")
            self.mesh_layer_plan.setText(layer_plan_text(plan))
        else:
            blank = "relative sizing" if not absolute else "\u2014"
            self.mesh_first_layer.setText(blank)
            self.mesh_layer_count.setText(f"{mesh.layers} (set)" if not absolute else "\u2014")
            self.mesh_layer_stack.setText("\u2014")
            self.mesh_layer_plan.setText("\u2014")
        thin = plan.thickness_warning if plan is not None else None
        self.mesh_layer_thickness_warning.setText(thin or "")
        self._set_warn(self.mesh_layer_thickness_warning, True)
        self.mesh_layer_thickness_warning.setVisible(thin is not None)
        self._set_warn(self.mesh_layer_plan, thin is not None)
        self.mesh_layer_plan.setToolTip(thin or "")
        warn = plan is not None and plan.warning is not None
        for label in (self.mesh_first_layer, self.mesh_layer_count, self.mesh_layer_stack):
            self._set_warn(label, warn)
        for label in (self.mesh_layer_count, self.mesh_layer_stack):
            label.setToolTip(plan.warning if warn else "")
        if box.bounds is None:
            for label in (self.mesh_base_used, self.mesh_levels_used, self.mesh_bg_cells, self.mesh_volume_cells,
                          self.mesh_surface_length, self.mesh_surface_cells, self.mesh_curvature,
                          self.mesh_cores_used):
                label.setText("\u2014")
            self._set_warn(self.mesh_bg_cells, False)
            self.mesh_length_warning.setVisible(False)
            return
        length = surface_length(self._project, box)
        est = estimate_with_volumes(self._project, box)
        self.mesh_surface_length.setText(length.describe())
        warning = surface_length_warning(length)
        self.mesh_length_warning.setText(warning or "")
        self._set_warn(self.mesh_length_warning, True)
        self.mesh_length_warning.setVisible(warning is not None)
        self.mesh_curvature.setText(
            f"level {est.curvature_level} ({est.curvature_size:.4g} m)" if mesh.curvature_levels else "off")
        auto = "" if est.base_size_overridden else " (computed)"
        self.mesh_base_used.setText(f"{est.base_size:.4g} m{auto}")
        self.mesh_levels_used.setText(
            f"{est.level_min} \u2013 {est.level_max}" + ("" if est.levels_overridden else " (computed)")
        )
        nx, ny, nz = est.cells
        self.mesh_bg_cells.setText(f"{nx} \u00d7 {ny} \u00d7 {nz} = {est.total_cells:,}")
        self._set_warn(self.mesh_bg_cells, est.too_many_cells)
        count = len(self._project.sim.refinement_volumes)
        self.mesh_volume_cells.setText(
            f"+{est.volume_cells:,} cells ({count} volume{'s' if count != 1 else ''}; total {est.budget_cells:,})"
            if count else "none")
        self.mesh_volume_cells.setToolTip(OVERLAP_NOTE if count else "")
        self._set_warn(self.mesh_volume_cells, est.too_many_cells and est.volume_cells > 0)
        self.mesh_surface_cells.setText(f"{est.surface_size:.4g} m")
        self.mesh_cores_used.setText(mesh_cores(self._project, box, PHYSICAL_CORES).describe())

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
        solvers = self._kind == "solvers"
        self._rows["solvers_recommended"].setVisible(solvers)
        if solvers:
            cells = self._mesh_report.cells if self._mesh_report is not None else None
            if cells:
                n = recommended_cores(cells, PHYSICAL_CORES)
                self.solvers_recommended.setText(f"{n} ({cells:,} cells, {CELLS_PER_CORE:,} per core)")
            else:
                self.solvers_recommended.setText("\u2014 (generate the mesh first)")
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
            "failed": (str(report.failed_checks)
                       + "".join(f"\nhard: {line}" for line in report.hard_failures)
                       + "".join(f"\nwarning: {line}" for line in report.soft_warnings)
                       + ("\nRun Solver is blocked: the mesh has hard checkMesh failures" if report.hard_failures
                          else "\nWarnings only: the solver can run" if report.soft_warnings else ""),
                       bool(report.hard_failures or report.soft_warnings)),
            "ok": ("yes" if report.mesh_ok else "no", not report.mesh_ok),
            "lost": (", ".join(report.lost_parts), False),
            "extruded": (num(report.extruded_percent, "{:g} %"), False),
            "first_cell": ((report.first_cell.description() if report.first_cell is not None else "")
                           + (f"\n{report.first_cell_warning()}" if report.first_cell_warning() else ""),
                           bool(report.first_cell_warning())),  # the achieved first cell (D-109)
            "status": (("Mesh out of date", True) if self._mesh_stale else ("Up to date", False)),
        }
        for key, (text, warn) in values.items():
            self.mesh_values[key].setText(text)
            self._set_warn(self.mesh_values[key], warn)
        self._rows["mesh_extruded"].setVisible(show and report.extruded_percent is not None)
        self._rows["mesh_first_cell"].setVisible(show and report.first_cell is not None)
        self._rows["mesh_lost"].setVisible(show and bool(report.lost_parts))
        self._set_error(self.mesh_values["lost"], bool(report.lost_parts))
        self._set_error(self.mesh_values["failed"], bool(report.hard_failures))
        self.mesh_values["lost"].setToolTip("\n".join(report.lost_messages()))
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

    def _refresh_reference(self, show: bool) -> None:
        for key in REFERENCE_ROWS:
            self._rows[key].setVisible(show)
        self._sections["ref_used"].setVisible(show)
        self.ref_note.setVisible(False)
        if not show:
            return
        sim = self._project.sim
        rep = sim.reports
        widgets = (self.ref_rho, self.ref_basis, self.ref_area, self.ref_length, self.ref_cofr)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.ref_rho.setValue(sim.physics.rho_ref)
            self.ref_basis.setCurrentText(rep.reference_area_basis)
            self.ref_area.setValue(rep.reference_area if rep.reference_area is not None else self.ref_area.minimum())
            self.ref_length.setValue(
                rep.reference_length if rep.reference_length is not None else self.ref_length.minimum())
            self.ref_cofr.setText(format_vector(rep.center_of_rotation) if rep.center_of_rotation else "")
        finally:
            for w in widgets:
                w.blockSignals(False)
        self.ref_area.setEnabled(rep.reference_area_basis == "custom")
        self.ref_u.setText(f"{sim.inflow.speed:.4g} m/s (inflow speed)")
        try:
            _box, _names, bounds = parts_layout(self._project)
        except MeshingNotReady:
            bounds = None
        if bounds is None:
            for label in (self.ref_area_used, self.ref_length_used, self.ref_cofr_used):
                label.setText("\u2014")
            return
        ref = reference_values(bounds, rep)

        def tag(auto: bool, label: str) -> str:
            return f" \u2014 {label}" if auto else " (set)"

        self.ref_area_used.setText(f"{ref.a_ref:.4g} m\u00b2" + tag(ref.a_auto, AREA_BASIS_LABELS.get(ref.a_basis, "")))
        self.ref_length_used.setText(f"{ref.l_ref:.4g} m" + tag(ref.l_auto, LENGTH_AUTO_LABEL))
        self.ref_cofr_used.setText(f"({format_vector(ref.cofr)}) m" + tag(ref.cofr_auto, CENTRE_AUTO_LABEL))
        self.ref_note.setVisible(ref.a_auto or ref.l_auto)

    def _commit_rho(self) -> None:
        if self._kind != "reference_values":
            return
        try:
            self._project.update_physics(rho_ref=self.ref_rho.value())
        except (ValueError, TypeError) as exc:
            self.message.emit(str(exc))
        self.refresh()

    def _commit_basis(self) -> None:
        """A_ref basis: "custom" starts from the area in use, the others clear the custom value."""
        if self._kind != "reference_values":
            return
        basis = self.ref_basis.currentText()
        area = None
        if basis == "custom":
            try:
                _box, _names, bounds = parts_layout(self._project)
            except MeshingNotReady:
                bounds = None
            area = reference_values(bounds, self._project.sim.reports).a_ref if bounds is not None else 1.0
            area = area if area > 0 else 1.0
        try:
            self._project.update_reports(reference_area_basis=basis, reference_area=area)
        except (ValueError, TypeError) as exc:
            self.message.emit(str(exc))
        self.refresh()

    def _commit_reference(self, key: str) -> None:
        if self._kind != "reference_values":
            return
        try:
            if key == "center_of_rotation":
                value = parse_vector(self.ref_cofr.text())
            else:
                widget = self.ref_area if key == "reference_area" else self.ref_length
                value = None if widget.value() == widget.minimum() else widget.value()  # "auto"
            self._project.update_reports(**{key: value})
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value

    # -- stopping criteria ---------------------------------------------------------------------

    def _refresh_stopping(self, show: bool) -> None:
        for key in STOPPING_ROWS:
            self._rows[key].setVisible(show)
        self._sections["stop_criteria"].setVisible(show)
        self.stop_add.setVisible(show)
        stop = self._project.sim.solvers.stopping
        kinds = [c.kind for c in stop.criteria] if show else []
        options = self._quantity_options() if show else []
        if (kinds, options) != self._criteria_kinds:
            self._build_criteria_rows(kinds, options)
        self.stop_empty.setVisible(show and not kinds)
        if not show:
            return
        widgets = [self.stop_combine, self.stop_min, self.stop_max, self.stop_osc_threshold, self.stop_osc_window]
        widgets += [w for row in self.criterion_widgets for w in row.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.stop_combine.setCurrentText(stop.combine)
            self.stop_min.setValue(stop.min_iterations)
            self.stop_max.setValue(self._project.sim.solvers.iterations)
            self.stop_osc_threshold.setValue(100 * stop.oscillation_threshold)
            self.stop_osc_window.setValue(stop.oscillation_window)
            for c, row in zip(stop.criteria, self.criterion_widgets):
                if isinstance(c, ResidualCriterion):
                    row["field"].setCurrentText(c.field)
                    row["threshold"].setValue(c.threshold)
                else:
                    combo = row["quantity"]
                    if combo.findData(c.quantity) < 0:  # a removed part or probe: kept, flagged
                        names, probes = self._patches_and_probes()
                        why = missing_reference(c.quantity, names, probes) or "not available"
                        combo.addItem(f"{report_label(c.quantity)} ({why})", c.quantity)
                    combo.setCurrentIndex(combo.findData(c.quantity))
                    row["window"].setValue(c.window)
                    row["tolerance"].setValue(c.tolerance)
                    row["floor"].setValue(c.effective_floor)
                row["earliest"].setText(f"iteration {earliest_iteration(c, stop.min_iterations)}")
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _criterion_row(self, text: str, field: QWidget) -> None:
        row = QWidget()
        row.setObjectName("propRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QHBoxLayout(row)
        box.setContentsMargins(*self._row_margins)
        title = ElidedLabel(text)
        title.setObjectName("muted")
        box.addWidget(title)
        box.addWidget(field, 1)
        if isinstance(field, (QLineEdit, QComboBox, QAbstractSpinBox)):
            field.setMinimumHeight(metrics().field)
            field.setMinimumWidth(1)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            field.setFont(mono_font(QApplication.font(), 0.9))
        row.setMinimumHeight(self._row_min_height)
        self._criteria_titles.append((row, title))
        self._criteria_box.addWidget(row)
        row.show()  # now, not at the next event loop pass: the content height must count it
        self._criteria_rows.append(row)

    def _patches_and_probes(self) -> tuple[list[str], list[str]]:
        sim = self._project.sim
        return (list(force_report_keys(sim.geometry.parts)), [p.name for p in sim.reports.probes])

    def _quantity_options(self) -> list[str]:
        """Quantities an asymptotic criterion can watch in this project (D-060)."""
        return criterion_quantities(*self._patches_and_probes())

    def _build_criteria_rows(self, kinds: list[str], options: list[str] | None = None) -> None:
        """One block of rows per criterion: a title row (type and Remove), then its settings."""
        for row in self._criteria_rows:
            self._criteria_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._criteria_rows, self._criteria_titles, self.criterion_widgets = [], [], []
        options = list(options or [])
        self._criteria_kinds = (list(kinds), options)
        for i, kind in enumerate(kinds):
            remove = QPushButton("Remove")
            remove.setObjectName("tbBtn")
            remove.setToolTip(f"Remove criterion {i + 1}: {STOPPING_TOOLTIPS[kind]}")
            remove.clicked.connect(lambda _=False, n=i: self._remove_criterion(n))
            self._criterion_row(f"{i + 1} \u00b7 {CRITERION_TITLES[kind]}", remove)
            earliest = QLabel()
            earliest.setObjectName("checkValue")
            earliest.setToolTip("The first iteration at which this criterion may be met: the minimum iterations "
                                "and the full window (residuals: never before iteration 3)")
            widgets: dict[str, QWidget] = {"remove": remove, "earliest": earliest}
            if kind == "residual":
                field = _combo(RESIDUAL_FIELDS)
                field.setToolTip("Solved field; U is the largest of the Ux, Uy, Uz residuals")
                threshold = _sci()
                self._criterion_row("Field", field)
                self._criterion_row("Threshold", threshold)
                field.currentTextChanged.connect(lambda _t, n=i: self._commit_criterion(n, "field"))
                threshold.editingFinished.connect(lambda n=i: self._commit_criterion(n, "threshold"))
                widgets.update(field=field, threshold=threshold)
            else:
                quantity = QComboBox()
                for q in options:
                    quantity.addItem(report_label(q), q)
                window = _spin(2, 10_000_000, " it.")
                tolerance = _sci()
                tolerance.setToolTip("Relative: (max - min) / max(|mean|, floor) over the window <= tolerance"
                                     if kind == "asymptotic" else
                                     "Relative: |mean of the last window - mean of the window before| / "
                                     "max(|mean|, floor) <= tolerance")
                floor = _sci()
                floor.setToolTip("Scale floor of the relative range, in the quantity's units: |mean| is replaced by "
                                 "it when smaller (default 0.01 for force and moment coefficients; probes: set it, "
                                 "suggested 1% of the free-stream dynamic pressure or speed)")
                self._criterion_row("Quantity", quantity)
                self._criterion_row("Window", window)
                self._criterion_row("Tolerance", tolerance)
                self._criterion_row("Scale floor", floor)
                quantity.currentIndexChanged.connect(lambda _i, n=i: self._commit_criterion(n, "quantity"))
                window.editingFinished.connect(lambda n=i: self._commit_criterion(n, "window"))
                tolerance.editingFinished.connect(lambda n=i: self._commit_criterion(n, "tolerance"))
                floor.editingFinished.connect(lambda n=i: self._commit_criterion(n, "floor"))
                widgets.update(quantity=quantity, window=window, tolerance=tolerance, floor=floor)
            _wrap(earliest)
            self._criterion_row("Earliest stop", earliest)
            self.criterion_widgets.append(widgets)
        self._apply_label_column()

    def _edit_stopping(self, mutate) -> None:
        """Apply ``mutate`` to a dump of the stopping criteria and commit it (one undo step);
        a rejected value is reported and reverted."""
        data = self._project.sim.solvers.stopping.model_dump()
        try:
            mutate(data)
            self._project.update_solver(stopping=data)
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    def _commit_stopping_setting(self, key: str) -> None:
        if self._kind != "stopping":
            return
        if key == "max":
            try:
                self._project.update_solver(iterations=self.stop_max.value())
            except (ValueError, TypeError) as exc:
                self.message.emit(str(exc))
            self.refresh()
            return
        values = {"combine": lambda: self.stop_combine.currentText(),
                  "min": lambda: self.stop_min.value(),
                  "osc_threshold": lambda: self.stop_osc_threshold.value() / 100,
                  "osc_window": lambda: self.stop_osc_window.value()}
        field = {"combine": "combine", "min": "min_iterations", "osc_threshold": "oscillation_threshold",
                 "osc_window": "oscillation_window"}[key]
        value = values[key]()
        self._edit_stopping(lambda d: d.update({field: value}))

    def _commit_criterion(self, index: int, key: str) -> None:
        if self._kind != "stopping" or index >= len(self.criterion_widgets):
            return
        widget = self.criterion_widgets[index][key]
        if key == "quantity":
            value = widget.currentData()
        elif isinstance(widget, QComboBox):
            value = widget.currentText()
        else:
            value = widget.value()

        def mutate(d: dict) -> None:
            d["criteria"][index][key] = value
            if key == "quantity":  # the floor is in the quantity's units: start from its default
                d["criteria"][index]["floor"] = None if default_floor(value) is not None else self._probe_floor(value)

        self._edit_stopping(mutate)

    def _probe_floor(self, quantity: str) -> float:
        """Suggested scale floor of a probe criterion: 1% of the free-stream dynamic pressure
        (kinematic, 0.5 U^2) for p, 1% of the free-stream speed for U."""
        speed = self._project.sim.inflow.speed
        return 0.01 * (0.5 * speed ** 2 if quantity.endswith(":p") else speed)

    def _add_criterion(self, kind: str) -> None:
        """Add a criterion with defaults: a p residual of 1e-4, or an asymptotic or mean-stable Cd
        criterion."""
        if self._kind != "stopping":
            return
        if kind == "residual":
            new = ResidualCriterion(field="p", threshold=1e-4)
        elif kind == "mean_stable":
            new = MeanStableCriterion(quantity="Cd")
        else:
            new = AsymptoticCriterion(quantity="Cd")
        self._edit_stopping(lambda d: d["criteria"].append(new.model_dump()))

    def _remove_criterion(self, index: int) -> None:
        if self._kind != "stopping":
            return
        self._edit_stopping(lambda d: d["criteria"].pop(index))

    # -- reports: forces, mass balance, y+ -------------------------------------------------------

    def set_report_monitor(self, monitor, case_dir: Path | None) -> None:
        """The postProcessing reader of the shown run (None: no run) and its case directory; called
        after every monitors refresh, so the Reports & Monitors node follows a live run."""
        if monitor is not self._report_monitor or case_dir != self._report_case:
            self._report_monitor, self._report_case = monitor, case_dir
            self._yplus_cache = None
        if self._kind == "reports":
            self._refresh_reports(True)

    def refresh_reports(self) -> None:
        """New postProcessing data arrived (the monitors refreshed)."""
        if self._kind == "reports":
            self._refresh_reports(True)

    def _yplus_histogram(self):
        case = self._report_case
        if case is None:
            return None
        from vortexcfd.foam.results import latest_result_time

        time = latest_result_time(case)
        key = (str(case), time)
        if self._yplus_cache is None or self._yplus_cache[0] != key:
            patches = wall_patch_names(self._project.sim.geometry.parts)
            try:
                result = case_yplus_histogram(case, patches)
            except Exception:  # unreadable field file: shown as missing
                result = None
            self._yplus_cache = (key, result)
        return self._yplus_cache[1]

    def _windowed_force(self, base: str, column: str):
        """The windowed mean of a force coefficient column (D-118): over the window of a mean-stable
        criterion on it, else the oscillation window."""
        monitor = self._report_monitor
        if monitor is None:
            return None
        quantity = base if column == "All walls" else f"{base}@{column}"
        stop = self._project.sim.solvers.stopping
        window = next((c.window for c in stop.criteria if isinstance(c, MeanStableCriterion) and c.quantity == quantity),
                      stop.oscillation_window)
        return window_stats(monitor.series(quantity), window, quantity=quantity)

    def _refresh_reports(self, show: bool) -> None:
        monitor = self._report_monitor
        rows = monitor.breakdown_rows() if (show and monitor is not None) else []
        balance = monitor.mass_balance() if (show and monitor is not None) else None
        yplus = self._yplus_histogram() if show else None
        has_any = bool(rows) or balance is not None or yplus is not None
        self._sections["rep_forces"].setVisible(show and bool(rows))
        self._sections["rep_mass"].setVisible(show and balance is not None)
        self._sections["rep_yplus"].setVisible(show and has_any)
        self._forces_host.setVisible(show and bool(rows))
        for key in ("rep_mass_inlet", "rep_mass_outlet", "rep_mass_imbalance"):
            self._rows[key].setVisible(show and balance is not None)
        self._yplus_host.setVisible(show and has_any)
        self._rows["rep_yplus_faces"].setVisible(show and yplus is not None)
        self.reports_empty.setVisible(show and not has_any)
        if not show:
            return
        self.forces_table.set_rows(rows, self._windowed_force)
        if balance is not None:
            inlet, outlet, pct = balance
            self.mass_inlet.setText(f"{inlet:.6g} m\u00b3/s")
            self.mass_outlet.setText(f"{outlet:.6g} m\u00b3/s")
            if pct is None:
                self.mass_imbalance.setText("\u2014 (no inflow)")
                self._set_warn(self.mass_imbalance, False)
            else:
                warn = abs(pct) > MASS_WARNING
                self.mass_imbalance.setText(f"{pct:.3g} % of the inlet flux" + (f" (above {MASS_WARNING:g} %)" if warn else ""))
                self._set_warn(self.mass_imbalance, warn)
        self.yplus_chart.set_histogram(yplus[1] if yplus is not None else None)
        if yplus is not None:
            self.yplus_faces.setText(f"{yplus[1].faces:,} at time {yplus[0]}")
        self._fit_content_height()

    # -- probes --------------------------------------------------------------------------------

    def _refresh_probes(self, show: bool) -> None:
        probes = self._project.sim.reports.probes if show else []
        self._probe_add_host.setVisible(show)
        self.probes_empty.setVisible(show and not probes)
        if len(probes) != self._probe_count or not show:
            self._build_probe_rows(len(probes) if show else 0)
        for probe, row in zip(probes, self.probe_widgets):
            for w in row.values():
                w.blockSignals(True)
            row["name"].setText(probe.name)
            row["location"].setText(format_vector(probe.location))
            for w in row.values():
                w.blockSignals(False)

    def _probe_row(self, text: str, field: QWidget) -> None:
        row = QWidget()
        row.setObjectName("propRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QHBoxLayout(row)
        box.setContentsMargins(*self._row_margins)
        title = ElidedLabel(text)
        title.setObjectName("muted")
        box.addWidget(title)
        box.addWidget(field, 1)
        if isinstance(field, QLineEdit):
            field.setMinimumHeight(metrics().field)
            field.setMinimumWidth(1)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            field.setFont(mono_font(QApplication.font(), 0.9))
        row.setMinimumHeight(self._row_min_height)
        self._probe_titles.append((row, title))
        self._probe_box.addWidget(row)
        row.show()
        self._probe_rows.append(row)

    def _build_probe_rows(self, count: int) -> None:
        for row in self._probe_rows:
            self._probe_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._probe_rows, self._probe_titles, self.probe_widgets = [], [], []
        self._probe_count = count
        for i in range(count):
            remove = QPushButton("Remove")
            remove.setObjectName("tbBtn")
            remove.clicked.connect(lambda _=False, n=i: self._remove_probe(n))
            self._probe_row(f"Probe {i + 1}", remove)
            name = QLineEdit()
            name.setToolTip("Letters, digits and _, starting with a letter; used in the report names")
            location = QLineEdit()
            location.setToolTip("x y z in metres (a point in the fluid)")
            self._probe_row("Name", name)
            self._probe_row("Location", location)
            name.editingFinished.connect(lambda n=i: self._commit_probe(n, "name"))
            location.editingFinished.connect(lambda n=i: self._commit_probe(n, "location"))
            self.probe_widgets.append({"name": name, "location": location, "remove": remove})
        self._apply_label_column()

    def _edit_probes(self, mutate) -> None:
        probes = [p.model_dump() for p in self._project.sim.reports.probes]
        try:
            mutate(probes)
            self._project.update_reports(probes=probes)
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    def _commit_probe(self, index: int, key: str) -> None:
        if self._kind != "probes" or index >= len(self.probe_widgets):
            return
        text = self.probe_widgets[index][key].text()

        def mutate(probes: list[dict]) -> None:
            if key == "name":
                probes[index]["name"] = text.strip()
            else:
                vector = parse_vector(text)
                if vector is None:
                    raise ValueError("Probe location: expected three numbers (x y z)")
                probes[index]["location"] = vector

        self._edit_probes(mutate)

    def _add_probe(self) -> None:
        """A probe downstream of the parts (one parts length behind them, on their centre line)."""
        if self._kind != "probes":
            return
        taken = {p.name for p in self._project.sim.reports.probes}
        n = 1
        while f"probe{n}" in taken:
            n += 1
        try:
            _box, _names, b = parts_layout(self._project)
        except MeshingNotReady:
            b = None
        location = ((b[1] + (b[1] - b[0]), (b[2] + b[3]) / 2, (b[4] + b[5]) / 2) if b is not None
                    else (1.0, 0.0, 0.0))
        new = Probe(name=f"probe{n}", location=location)
        self._edit_probes(lambda probes: probes.append(new.model_dump()))

    def _remove_probe(self, index: int) -> None:
        if self._kind != "probes":
            return
        self._edit_probes(lambda probes: probes.pop(index))

    def set_run_record(self, record: RunRecord | None, stale: bool = False) -> None:
        """The last solver run shown on the Solvers node (None: no run yet)."""
        self._run_record, self._results_stale = record, stale
        self.refresh()

    def _refresh_run(self, show: bool) -> None:
        record = self._run_record
        self._sections["run_last"].setVisible(show)
        for key in ("run_state", "run_iterations", "run_residuals", "run_status"):
            self._rows[key].setVisible(show and record is not None)
        self.run_empty.setVisible(show and record is None)
        if not show or record is None:
            return
        self.run_state.setText(record.label)
        self._set_warn(self.run_state, record.state != "criteria_met")
        self.run_iterations.setText(str(record.iterations))
        residuals = ", ".join(f"{k} {v:.3g}" for k, v in record.final_residuals.items())
        self.run_residuals.setText(residuals or "\u2014")
        self.run_status.setText("Results out of date" if self._results_stale else "Up to date")
        self._set_warn(self.run_status, self._results_stale)

    def set_mesh_stale(self, stale: bool) -> None:
        """The shown mesh no longer matches the project's meshing inputs."""
        self._mesh_stale = stale
        self.refresh()

    def _refresh_domain(self, show: bool) -> None:
        """Populate the domain rows from the project (no commits) and show them if ``show``."""
        domain = self._project.sim.domain
        generated = domain.enabled or self._project.sim.analysis_type != "empty"
        keys = [f"dom_{k}" for k in self._domain_keys] + ["dom_shape", "dom_symmetry", "dom_length", "dom_size",
                                                         "dom_volume", "dom_parts"]
        used = DOMAIN_SHAPE_FIELDS[domain.shape]
        for key in keys:
            field = key.removeprefix("dom_")
            visible = show and generated and (field not in self.domain_fields or field in used)
            self._rows[key].setVisible(visible)
        self._rows["dom_generate"].setVisible(show and not generated)
        for key in ("dom_size", "dom_symmetry", "dom_computed"):
            self._sections[key].setVisible(show and generated)
        self.domain_warning.setVisible(show and generated)
        self._refresh_fluid_region(self._kind == "fluid_region")
        self._refresh_surface_prep(self._kind in ("surface_prep", "prepare_surfaces"))
        if not show or not generated:
            return
        widgets = [self.domain_enabled, self.domain_symmetry, self.domain_shape, *self.domain_fields.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.domain_enabled.setChecked(domain.enabled)
            self.domain_symmetry.setCurrentText(domain.symmetry)
            self.domain_shape.setCurrentIndex(DOMAIN_SHAPES.index(domain.shape))
            for key, spin in self.domain_fields.items():
                spin.setValue(getattr(domain, key))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._row_labels["dom_lateral"].set_full_text("Half-width" if domain.shape == "c_type" else "Lateral")
        box = domain_box_for(self._project)
        self.domain_length.setText(f"{box.reference_length:.4g} m" if box.bounds else "\u2014")
        self.domain_size.setText(
            " \u00d7 ".join(f"{v:.3g}" for v in box.size) + " m" if box.bounds else "\u2014"
        )
        self.domain_volume.setText(f"{box.volume:.4g} m\u00b3" if box.bounds else "\u2014")
        self.domain_parts.setText(", ".join(domain.parts) if domain.parts else "all parts")
        self.domain_warning.setText("\n".join(box.warnings))
        self._set_warn(self.domain_warning, bool(box.warnings))

    def _refresh_surface_prep(self, show: bool) -> None:
        keys = ("sp_strategy", "sp_state", "sp_parts", "sp_features", "sp_report", "sp_buttons")
        for key in keys:
            self._rows[key].setVisible(show)
        self._sections["sp_title"].setVisible(show)
        if not show:
            return
        prep = self._project.sim.surface_prep
        state = surface_prep.state(self._project)
        self.sp_remove.setEnabled(prep is not None and not self.geometry_busy)
        self.sp_run.setEnabled(bool(self._project.sim.geometry.parts) and not self.geometry_busy)
        for key in ("sp_parts", "sp_features", "sp_report"):
            self._rows[key].setVisible(prep is not None)
        if prep is None:
            self.sp_strategy.setText("not run (the parts mesh as imported)")
            self.sp_state.setText("\u2014")
            self._set_warn(self.sp_state, False)
            return
        self.sp_strategy.setText(surface_prep.STRATEGY_LABELS[prep.strategy])
        self.sp_state.setText({"current": "up to date: meshing uses it",
                               "stale": surface_prep.STALE_MESSAGE}.get(state, state))
        self._set_warn(self.sp_state, state == "stale")
        self.sp_parts.setText("\n".join(f"{p.part}: {surface_prep.STRATEGY_LABELS[p.strategy]}"
                                         + (f" ({p.note})" if p.note else "") for p in prep.parts))
        self.sp_features.setText(prep.features_file or "none")
        self.sp_report.setText("\n".join(f"{label}: {value}" for label, value in prep.report))

    def _refresh_fluid_region(self, show: bool) -> None:
        for key in ("fr_definition", "fr_domain", "fr_parts", "fr_location"):
            self._rows[key].setVisible(show)
        self._sections["fr_title"].setVisible(show)
        if not show:
            return
        sim = self._project.sim
        self.fluid_definition.setText("domain minus parts")
        box = domain_box_for(self._project)
        if not sim.domain.enabled or box.bounds is None:
            self.fluid_domain.setText("not generated" if not sim.domain.enabled else "\u2014 (no parts)")
        else:
            self.fluid_domain.setText(f"{SHAPE_LABELS[box.shape]}, {box.volume:.4g} m\u00b3")
        names = [p.name for p in sim.geometry.parts]
        self.fluid_parts.setText(", ".join(names) if names else "none")
        location = fluid_location(self._project) if sim.domain.enabled else None
        self.fluid_location.setText(
            "the cells connected to locationInMesh " + format_vector(location)
            + " (snappyHexMesh removes the cells inside the parts and outside the domain)"
            if location is not None else "\u2014")

    def _refresh_ground(self, show: bool) -> None:
        """The ground plane rows (D-116): on the Fluid Domain node of a box domain and on its ground node."""
        domain = self._project.sim.domain
        show = show and domain.enabled and domain.shape == "box"
        ground = domain.ground
        self._sections["dom_ground"].setVisible(show)
        for key in GROUND_ROWS:
            on = key == "dom_ground_enabled" or ground.enabled
            self._rows[key].setVisible(show and on and (key != "dom_ground_z" or ground.position == "value"))
        if not show:
            return
        widgets = (self.ground_enabled, self.ground_motion, self.ground_position, self.ground_z, self.ground_layers,
                   self.ground_start)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.ground_enabled.setChecked(ground.enabled)
            self.ground_motion.setCurrentIndex(list(GROUND_MOTIONS).index(ground.motion))
            self.ground_position.setCurrentIndex(list(GROUND_POSITIONS).index(ground.position))
            self.ground_z.setValue(ground.z)
            self.ground_layers.setChecked(ground.layers)
            self.ground_start.setValue(GROUND_START_INLET if ground.wall_start_x is None else ground.wall_start_x)
        finally:
            for w in widgets:
                w.blockSignals(False)
        self.ground_bcs.setText(ground_bc_text(ground.motion, ground.wall_start_x is not None))

    def _commit_ground(self, key: str) -> None:
        if self._kind not in ("fluid_domain", "boundary_ground"):
            return
        value = {"enabled": self.ground_enabled.isChecked, "motion": self.ground_motion.currentData,
                 "position": self.ground_position.currentData, "z": self.ground_z.value,
                 "layers": self.ground_layers.isChecked,
                 "wall_start_x": lambda: (None if self.ground_start.value() <= GROUND_START_INLET
                                          else self.ground_start.value())}[key]()
        ground = self._project.sim.domain.ground.model_dump()
        if ground.get(key) == value:
            return
        if key == "position" and value == "value":
            box = domain_box_for(self._project)
            if box.parts_bounds is not None and ground["position"] == "parts_min":
                ground["z"] = box.parts_bounds[4]  # start from the plane in use
        ground[key] = value
        try:
            self._project.update_domain(label=f"Edit ground plane ({key})", ground=ground)
        except (ValueError, TypeError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()  # reverts a rejected value

    def _commit_domain(self, key: str) -> None:
        if self._kind != "fluid_domain":
            return
        if key == "enabled":
            value = self.domain_enabled.isChecked()
        elif key == "symmetry":
            value = self.domain_symmetry.currentText()
        elif key == "shape":
            value = self.domain_shape.currentData()
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
        if report.intersections_pending and self.request_intersections is not None:
            self.request_intersections(part_file(self._project, part), part.units)
        # Overlaps between parts (D-099): the self-intersection check looks within one part only.
        known = surface_prep.crossings_known(self._project)
        if not known and self.request_overlaps is not None:
            self.request_overlaps()
        crossings = surface_prep.crossing_parts(self._project, compute=False) if known else None
        crossing = (surface_prep.crossing_text(self._project, part.name, crossings) if known
                    else ("checking\u2026", False))
        crosses_others = bool(crossings and crossings.get(part.name))
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
            "intersections": ((str(report.self_intersections)
                               + (" within the part; it crosses other parts (below)" if crosses_others else ""),
                               report.self_intersections > 0 or crosses_others)
                              if report.self_intersections is not None
                              else ("checking\u2026", False) if report.intersections_pending
                              else (report.intersections_note, True)),
            "crossings": crossing,
            "watertight": ("yes" if report.watertight else "no", not report.watertight),
            "normals": (("point inward", True) if report.normals_inward
                        else ("outward", False) if report.watertight else ("\u2014 (open surface)", False)),
        }
        for key, (text, warn) in values.items():
            self.check_values[key].setText(text)
            self._set_warn(self.check_values[key], warn)

    @staticmethod
    def _set_error(label: QLabel, error: bool) -> None:
        label.setProperty("error", "true" if error else "false")
        label.style().unpolish(label)
        label.style().polish(label)

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

    def _commit_dimension(self, *_args) -> None:
        if self._kind != "root":
            return
        try:
            self._project.set_dimension(self.dimension_combo.currentData())
        except (ValueError, TypeError) as exc:
            self.message.emit(str(exc))
        self.refresh()

    def _commit_part_level(self, key: str) -> None:
        if self._kind != "part" or self._index is None:
            return
        spin = self.part_level_fields[key]
        value = None if spin.value() == spin.minimum() else spin.value()
        try:
            self._project.update_part(self._index, **{key: value})
        except (ValueError, TypeError, IndexError) as exc:  # includes pydantic errors
            self.message.emit(str(exc))
        self.refresh()

    # -- regions (Task 3.5) ------------------------------------------------------------------

    def _region_part(self) -> tuple[int, Part] | None:
        if self._kind != "part" or self._index is None:
            return None
        parts = self._project.sim.geometry.parts
        return (self._index, parts[self._index]) if 0 <= self._index < len(parts) else None

    def _refresh_regions(self, part: Part | None) -> None:
        loaded = part is not None and part_status(self._project, part) == OK
        if self._index != getattr(self, "_regions_part_index", None) or not loaded:
            self.region_list.clearSelection()  # a selection belongs to one part
        self._regions_part_index = self._index if loaded else None
        self._sections["regions"].setVisible(loaded)
        for key in ("region_name", "region_patch", "region_angle"):
            self._rows[key].setVisible(loaded)
        self._regions_host.setVisible(loaded)
        self._region_buttons.setVisible(loaded)
        if not loaded:
            if self._regions_part_index is None and self._index is not None:
                self.regions_selected.emit(self._index, [])
            return
        selected = set(self.selected_regions())
        self.region_list.blockSignals(True)
        self.region_list.clear()
        regions_ = part.regions or [SurfaceRegion(name=part.name)]
        for region in regions_:
            item = QListWidgetItem(f"{region.name}  \u2192  {part.region_patch(region)}")
            item.setData(Qt.ItemDataRole.UserRole, region.name)
            self.region_list.addItem(item)
            item.setSelected(region.name in selected)
        self.region_list.blockSignals(False)
        self._update_region_fields()
        self.regions_selected.emit(self._index, self.selected_regions())

    def selected_regions(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.region_list.selectedItems()]

    def select_regions(self, names: list[str]) -> None:
        """Select regions by name (e.g. picked in the viewer)."""
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in names)

    def _update_region_fields(self) -> None:
        names = self.selected_regions()
        current = self._region_part()
        part = current[1] if current else None
        by_name = {r.name: r for r in (part.regions if part else [])}
        self.region_name.blockSignals(True)
        self.region_patch.blockSignals(True)
        self.region_name.setText(names[0] if len(names) == 1 else "")
        self.region_name.setEnabled(len(names) == 1 and bool(part and part.regions))
        patches = {by_name[n].patch if n in by_name else None for n in names}
        self.region_patch.setText(next(iter(patches)) or "" if len(patches) == 1 else "")
        self.region_patch.setEnabled(bool(names))
        self.region_merge.setEnabled(len(names) >= 2)
        self.region_split.setEnabled(len(names) <= 1)
        if self.geometry_busy:  # a geometry job is running (D-073)
            for widget in (self.region_name, self.region_patch, self.region_split, self.region_merge):
                widget.setEnabled(False)
        self.region_name.blockSignals(False)
        self.region_patch.blockSignals(False)

    def _on_region_selection(self) -> None:
        self._update_region_fields()
        current = self._region_part()
        if current is not None:
            self.regions_selected.emit(current[0], self.selected_regions())

    def _apply_region_edit(self, make_fields, keep: list[str] | None = None) -> None:
        current = self._region_part()
        if current is None:
            return
        try:
            fields = make_fields(current[0])
            if fields:
                self._project.update_part(current[0], **fields)
        except (ValueError, TypeError, IndexError, OSError, RegionError, SurfaceLoadError) as exc:
            self.message.emit(str(exc))
        self.refresh()
        if keep is not None:
            self.select_regions(keep)

    def _commit_region_name(self) -> None:
        names = self.selected_regions()
        new = self.region_name.text().strip()
        if len(names) != 1 or not new or new == names[0]:
            return
        self._apply_region_edit(lambda i: part_ops.rename_region(self._project, i, names[0], new), [new])

    def _commit_region_patch(self) -> None:
        names = self.selected_regions()
        if not names:
            return
        patch = self.region_patch.text().strip() or None
        self._apply_region_edit(lambda i: part_ops.assign_patch(self._project, i, names, patch), names)

    def _merge_regions(self) -> None:
        names = self.selected_regions()
        self._apply_region_edit(lambda i: part_ops.merge_regions(self._project, i, names), names[:1])

    def _split_region(self) -> None:
        names = self.selected_regions()
        angle = self.region_angle.value()
        self._apply_region_edit(lambda i: part_ops.split_region(self._project, i, names[0] if names else None, angle))

    def _patch_per_region(self) -> None:
        self._apply_region_edit(lambda i: part_ops.patch_per_region(self._project, i), self.selected_regions())

    def _refresh_cad(self, part: Part | None) -> None:
        cad = part.cad if part is not None else None
        for key in ("cad_file", "cad_linear", "cad_angular"):
            self._rows[key].setVisible(cad is not None)
        if cad is None:
            return
        for widget in (self.cad_linear, self.cad_angular):
            widget.blockSignals(True)
        self.cad_file_label.setText(cad.file)
        self.cad_linear.setValue(cad.linear_deflection)
        self.cad_angular.setValue(cad.angular_deflection)
        for widget in (self.cad_linear, self.cad_angular):
            widget.blockSignals(False)

    def _commit_cad(self, which: str) -> None:
        """Ask for a re-tessellation with the edited deflection (run on the geometry worker and
        applied as one undoable step, D-073)."""
        if self._kind != "part" or self._index is None or self.geometry_busy:
            return
        part = self._project.sim.geometry.parts[self._index]
        if part.cad is None:
            return
        if which == "linear":
            value = self.cad_linear.value()
            if value == part.cad.linear_deflection:
                return
            if not value > 0:
                self.message.emit("The linear deflection must be a positive length")
                self.refresh()
                return
            self.retessellate_requested.emit(self._index, value, None)
        else:
            value = round(self.cad_angular.value(), 1)
            if value == part.cad.angular_deflection:
                return
            self.retessellate_requested.emit(self._index, None, value)

    def set_geometry_busy(self, busy: bool) -> None:
        """Disable the part geometry edits while a geometry job runs (D-073)."""
        self.geometry_busy = busy
        for widget in (self.cad_linear, self.cad_angular, self.region_name, self.region_patch,
                       self.region_split, self.region_merge, self.region_own_patches, self.units_combo):
            widget.setEnabled(not busy)
        if not busy:
            self._update_region_fields()
        self.sp_run.setEnabled(not busy and bool(self._project.sim.geometry.parts))
        self.sp_remove.setEnabled(not busy and self._project.sim.surface_prep is not None)

    def _commit_units(self, units: str) -> None:
        try:
            if self._kind == "part" and self._index is not None:
                self._project.update_part(self._index, units=units)
        except (ValueError, TypeError, IndexError) as exc:
            self.message.emit(str(exc))
        self.refresh()
