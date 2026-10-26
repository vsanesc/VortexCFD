"""Simulation tree data models."""

import math
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vortexcfd.core.reports import PROBE_NAME_RE, default_floor, is_criterion_quantity, is_report_id

CURRENT_SCHEMA_VERSION: int = 25


class StrictModel(BaseModel):
    """Base model that forbids unknown fields."""

    model_config = ConfigDict(extra="forbid")


# A patch name the user assigns to a region (later made OpenFOAM-safe by foam/mesh_case.py).
PATCH_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class SurfaceRegion(StrictModel):
    """A named group of a Part's triangles (schema v8, D-071).

    Every triangle of a part carries a base id (an STL solid, a CAD face or an angle-split
    patch: Part.region_ids); a region is the set of base ids in ``members``. ``patch`` is the
    mesh patch the region becomes; None puts it on the part's own patch (named after the part),
    so a part whose regions are all unassigned meshes exactly as before regions existed.
    ``color`` ("#rrggbb") comes from the CAD file when it has one.
    """

    name: str = Field(min_length=1)
    members: list[int] = Field(default_factory=list)
    patch: str | None = None
    color: str | None = None

    @field_validator("patch")
    @classmethod
    def _patch_name(cls, value: str | None) -> str | None:
        if value is not None and not PATCH_NAME_RE.match(value):
            raise ValueError("a patch name starts with a letter and has only letters, digits and _ "
                             "(at most 64 characters)")
        return value


class CadSource(StrictModel):
    """The CAD file a Part was tessellated from (schema v8, D-070).

    ``file`` is relative to the project folder (a copy in <project>/geometry/). The tessellation
    (the Part's ``source_file``) is regenerated whenever the deflections change:
    ``linear_deflection`` is the largest distance between a triangle and the CAD surface, in
    metres; ``angular_deflection`` the largest angle between neighbouring triangle normals, in
    degrees. ``bodies`` lists the file's bodies (solids, or shells of a surface model) in this
    part when the file was split into one part per body.
    """

    file: str
    linear_deflection: float = Field(gt=0)
    angular_deflection: float = Field(default=20.0, gt=0, le=90)
    bodies: list[int] | None = None  # the file's bodies in this part (None: all of them)


class AirfoilSource(StrictModel):
    """The airfoil coordinate file a 2D section Part was built from (schema v18, D-121): ``file`` relative to
    the project folder (a copy in <project>/geometry/), its ``format`` ("selig" or "lednicer"), the ``scale``
    applied to its coordinates (the chord of a file in chord units) and the trailing-edge closure ("blunt": an
    open trailing edge closed by a straight base; "sharp": the surfaces moved to meet). The Part's
    ``source_file`` is the section extruded into a slab (geometry/section.py)."""

    file: str
    format: Literal["selig", "lednicer"] = "selig"
    scale: float = Field(default=1.0, gt=0)
    te_closure: Literal["blunt", "sharp"] = "blunt"
    name: str | None = None  # the airfoil's name in the file


class Part(StrictModel):
    """A geometric part defined by a source mesh file.

    ``surface_level_min`` / ``surface_level_max`` override the mesh's surface refinement levels for
    this part only (None = the mesh's levels; setting only the max gives min = max - 1, as for the
    mesh). A part that is small relative to the background mesh is seeded with feature lines
    automatically so snappyHexMesh finds it (D-052).

    ``regions`` group the triangles by base id (``region_ids``: a .npy file of one int per
    triangle of the loaded surface, relative to the project folder; None = every triangle has id
    0); no regions = the whole part is one region. ``cad`` is set for a part imported from
    STEP/IGES/BREP: ``source_file`` is then its tessellation (D-070, D-071).
    """

    name: str
    source_file: str
    units: Literal["m", "cm", "mm", "in", "ft"] = "m"
    surface_level_min: int | None = Field(default=None, ge=0)
    surface_level_max: int | None = Field(default=None, ge=0)
    regions: list[SurfaceRegion] = Field(default_factory=list)
    region_ids: str | None = None
    cad: CadSource | None = None
    section: AirfoilSource | None = None  # a 2D section from an airfoil file (D-121)

    @model_validator(mode="after")
    def _levels_ordered(self) -> "Part":
        lo, hi = self.surface_level_min, self.surface_level_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("surface_level_max must be >= surface_level_min")
        return self

    @model_validator(mode="after")
    def _regions_consistent(self) -> "Part":
        names = [r.name for r in self.regions]
        if len(set(names)) != len(names):
            raise ValueError("region names must be unique within a part")
        members = [m for r in self.regions for m in r.members]
        if len(set(members)) != len(members):
            raise ValueError("a base id belongs to more than one region")
        return self

    def region_patch(self, region: SurfaceRegion) -> str:
        """The (unsanitised) patch name of a region: its assignment, else the part's name."""
        return region.patch if region.patch is not None else self.name

    def patch_names(self) -> list[str]:
        """The part's distinct patch names (unsanitised), in region order; [name] without regions.
        Base ids outside every region fall on the part's own patch, which is listed first when any
        region uses it."""
        out = [self.name] if not self.regions else []
        for region in self.regions:
            patch = self.region_patch(region)
            if patch not in out:
                out.append(patch)
        return out


class Geometry(StrictModel):
    """Geometry container holding simulation parts."""

    parts: list[Part] = Field(default_factory=list)


# Surface preparation strategies (schema v11, D-093): "intersection_features" keeps the components
# separate and adds their intersection curves as snapping features; "cad_union" sews each CAD
# component into a solid, fuses them and gives every Part its share of the outer skin.
SURFACE_PREP_STRATEGIES = ("intersection_features", "cad_union")


class PreparedPart(StrictModel):
    """One Part's result of the surface preparation. ``strategy`` is what was applied to it (a
    cad_union part that could not be sewn or fused falls back to intersection_features, ``note``
    says why). ``surface_file`` (metres, relative to the project folder) and ``region_ids`` replace
    the Part's own surface and region ids for meshing; None keeps them."""

    part: str
    strategy: Literal["intersection_features", "cad_union"]
    surface_file: str | None = None
    region_ids: str | None = None
    note: str | None = None


class SurfacePrep(StrictModel):
    """The surface preparation operation (schema v11, D-093): its result, applied as one undoable
    step and used by meshing while ``inputs_hash`` (the parts' geometry when it ran) still matches.
    ``features_file``: the components' intersection curves (featureEdgeMesh, metres, relative to the
    project folder), added to snappyHexMesh's features at the junction level. ``report``: the
    diagnostics and results as (label, value) rows. ``time_s``: the preparation's run time."""

    strategy: Literal["intersection_features", "cad_union"]
    inputs_hash: str
    parts: list[PreparedPart] = Field(default_factory=list)
    features_file: str | None = None
    report: list[tuple[str, str]] = Field(default_factory=list)
    time_s: float = Field(default=0.0, ge=0)

    def prepared(self, part_name: str) -> PreparedPart | None:
        return next((p for p in self.parts if p.part == part_name), None)


# Curvature refinement goes at most this many levels above a part's maximum surface level: 2 in D-085, the owner's
# conservative cap; editable up to 4 since D-148 (the default stays 2). [NUMERICS-REVIEW]
MAX_CURVATURE_LEVELS = 4
# A target y+ below this lies in the viscous sublayer, where the robust controls cannot build the stack (D-122):
# with absolute (y+) sizing the robust controls then give way to the wall-resolved ones (D-123).
WALL_RESOLVED_AUTO_YPLUS = 5.0


class Mesh(StrictModel):
    """snappyHexMesh controls (mesher level M1).

    Sizing is derived from two targets unless overridden: the background mesh gets about
    ``background_cells_target`` cells (so ``base_size`` = (domain volume / target)^(1/3)), and
    the surface cells aim at ``target_surface_size`` times a length, which fixes the refinement
    levels: the reference length l_ref of the Reference Values (``surface_size_reference``
    "l_ref", the default since schema v10, D-085) or L, the largest extent of the parts
    ("largest_extent", every project made before v10). ``base_size`` (metres) and the two surface
    levels are optional explicit overrides (None = computed). ``curvature_levels``: surface
    curvature refinement up to this many levels above a part's maximum surface level (0 = off,
    D-085). ``final_layer_thickness`` and ``min_thickness`` are relative to the local cell size.
    """

    background_cells_target: int = Field(default=100_000, gt=0)
    target_surface_size: float = Field(default=0.01, gt=0)  # relative to surface_size_reference
    surface_size_reference: Literal["l_ref", "largest_extent"] = "l_ref"
    curvature_levels: int = Field(default=2, ge=0, le=MAX_CURVATURE_LEVELS)
    base_size: float | None = Field(default=None, gt=0)
    surface_level_min: int | None = Field(default=None, ge=0)
    surface_level_max: int | None = Field(default=None, ge=0)
    feature_angle: float = Field(default=30.0, gt=0, le=180)
    layers: int = Field(default=3, ge=0)
    expansion_ratio: float = Field(default=1.2, ge=1.0)
    final_layer_thickness: float = Field(default=0.5, gt=0)
    min_thickness: float = Field(default=0.1, gt=0)
    # "relative": layer sizes relative to the local cell (target_yplus unused); "absolute_yplus": the
    # first layer thickness follows from target_yplus (see foam/yplus.py), expansion_ratio is reused.
    # Default since schema v10: absolute sizing for y+ 50, the wall-function range (D-086).
    layer_sizing: Literal["relative", "absolute_yplus"] = "absolute_yplus"
    target_yplus: float = Field(default=50.0, gt=0)
    # The prism-layer controls of absolute (y+) sizing (schema v13, D-106): "robust", the default, caps
    # the layer count (the expansion ratio raised up to 1.3 to keep the planned stack thickness) and
    # writes the 5.4 layer controls; "legacy" keeps the controls and the uncapped count of every
    # project saved before v13. Relative sizing is the same in both. "wall_resolved" (schema v18, D-122) is for
    # targets in the viscous sublayer (y+ about 1): the stack is grown until it is one surface cell thick (at
    # expansion 1.2, up to 40 layers), the surface is refined until its cell is at most 220 first layers, and
    # the layer phase relaxes the determinant and non-orthogonality checks.
    layer_controls: Literal["legacy", "robust", "wall_resolved"] = "robust"
    # Where target_yplus is placed (schema v14, D-107): "cell_centre", the default, sizes the first layer
    # so that the target falls at the first cell centre, where OpenFOAM evaluates y+ (first layer = twice
    # the target wall distance); "cell_height" (every project saved before v14) uses the target distance
    # as the first-layer height (OpenFOAM then reports about half the target).
    yplus_at: Literal["cell_centre", "cell_height"] = "cell_centre"
    # snappyHexMesh ranks (schema v15, D-111): None, the default, is automatic: the Solvers cores capped by
    # the meshing recommendation from the estimated cells (workflow/meshing.mesh_cores); a number is the
    # user's choice, capped by the machine's physical cores at run time. 1 is the serial pipeline. Left
    # out of the mesh hash: a parallel run meshes the same inputs.
    cores: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _levels_ordered(self) -> "Mesh":
        lo, hi = self.surface_level_min, self.surface_level_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("surface_level_max must be >= surface_level_min")
        return self

    @property
    def wall_resolved_auto(self) -> bool:
        """The robust controls with absolute (y+) sizing and a target y+ below WALL_RESOLVED_AUTO_YPLUS: meshing
        uses the wall-resolved controls instead (D-123). The stored value is kept, so a target of 5 or more gives
        the robust controls back."""
        return (self.layer_controls == "robust" and self.layer_sizing == "absolute_yplus"
                and self.target_yplus < WALL_RESOLVED_AUTO_YPLUS)

    @property
    def effective_layer_controls(self) -> str:
        """The layer controls meshing uses: ``layer_controls``, or "wall_resolved" when ``wall_resolved_auto``."""
        return "wall_resolved" if self.wall_resolved_auto else self.layer_controls


class Physics(StrictModel):
    """Flow physics: incompressible, steady (simpleFoam, the default) or transient (pimpleFoam, schema v25, D-181);
    k-omega SST or laminar (no turbulence model, schema v25, D-182).

    ``nu`` is the kinematic viscosity (m2/s); ``rho_ref`` (kg/m3) is used only to scale forces
    (the solver is incompressible, pressure is kinematic); ``speed_of_sound`` (m/s) only gives the Mach number.
    """

    flow: Literal["incompressible_steady", "incompressible_transient"] = "incompressible_steady"
    nu: float = Field(default=1.5e-5, gt=0)
    rho_ref: float = Field(default=1.225, gt=0)
    turbulence_model: Literal["kOmegaSST", "laminar"] = "kOmegaSST"
    # The speed of sound of the Mach number shown (m/s, schema v24, D-168): a reference value only, never written to
    # the case (the solver is incompressible). Default 343 m/s: air at 20 °C.
    speed_of_sound: float = Field(default=343.0, gt=0)

    @property
    def transient(self) -> bool:
        return self.flow == "incompressible_transient"

    @property
    def laminar(self) -> bool:
        return self.turbulence_model == "laminar"


class Inflow(StrictModel):
    """Free-stream conditions at the inlet. The flow is always along +x (z up); the angle of attack
    turns the parts nose up about the y axis through the reference centre of rotation (schema v18,
    D-120: geometry/attitude.py); the turbulence comes from the intensity and the viscosity ratio."""

    speed: float = Field(default=20.0, gt=0)  # m/s
    alpha_deg: float = Field(default=0.0, ge=-90.0, le=90.0)  # angle of attack
    turbulence_intensity: float = Field(default=0.01, gt=0, le=1.0)  # fraction
    viscosity_ratio: float = Field(default=10.0, gt=0)  # nut / nu


# Fields a residual criterion can watch (the solved equations; U is the largest component residual).
RESIDUAL_FIELDS = ("p", "U", "k", "omega")
# Quantities an asymptotic criterion can watch: core/reports.criterion_quantities (D-060).


class ResidualCriterion(StrictModel):
    """Stop when the initial residual of ``field`` (its first solve in the iteration; for U the
    largest of Ux, Uy, Uz) falls below ``threshold``: OpenFOAM's runTimeControl condition
    ``equationInitialResidual`` with mode minimum (D-058)."""

    kind: Literal["residual"] = "residual"
    field: Literal["p", "U", "k", "omega"]
    threshold: float = Field(gt=0)


class AsymptoticCriterion(StrictModel):
    """Stop when a monitored quantity has settled: over the last ``window`` iterations,
    (max - min) / max(|mean|, floor) <= ``tolerance`` (relative). ``floor`` keeps the test
    meaningful for a quantity whose mean is near zero: None takes the quantity's default
    (core/reports.default_floor: 0.01 for force and moment coefficients); a probe has no default
    and needs it set, in the probe's units (m2/s2 for kinematic p, m/s for U). OpenFOAM has no such
    condition: the app evaluates it from the live data and stops the solver cleanly (D-058).
    ``quantity`` is a force coefficient of all walls or of one part, or a probe's p or U
    (core/reports.py, D-060)."""

    kind: Literal["asymptotic"] = "asymptotic"
    quantity: str
    window: int = Field(default=50, ge=2)
    tolerance: float = Field(default=1e-3, gt=0)  # relative
    floor: float | None = Field(default=None, gt=0)

    @field_validator("quantity")
    @classmethod
    def _known_quantity(cls, value: str) -> str:
        if not is_criterion_quantity(value):
            raise ValueError(f"not a quantity an asymptotic criterion can watch: {value!r}")
        return value

    @model_validator(mode="after")
    def _floor_known(self) -> "AsymptoticCriterion":
        if self.effective_floor is None:
            raise ValueError(f"{self.quantity} has no default scale floor: set floor")
        return self

    @property
    def effective_floor(self) -> float | None:
        return self.floor if self.floor is not None else default_floor(self.quantity)


class MeanStableCriterion(AsymptoticCriterion):
    """Stop when the windowed mean of a monitored quantity has settled (schema v17, D-118): over two
    consecutive windows of ``window`` iterations (the last W and the W before them),
    |mean_last - mean_previous| / max(|mean_last|, floor) <= ``tolerance``. For a steady run that
    oscillates about a stationary mean (D-059), where the range-based asymptotic criterion is never
    met. Evaluated by the app like the asymptotic criterion (same quantities and floor, same clean
    stop, D-058), once 2 W values exist. [NUMERICS-REVIEW]"""

    kind: Literal["mean_stable"] = "mean_stable"  # type: ignore[assignment]
    window: int = Field(default=500, ge=2)
    tolerance: float = Field(default=0.005, gt=0)  # relative


Criterion = Annotated[Union[ResidualCriterion, AsymptoticCriterion, MeanStableCriterion],
                      Field(discriminator="kind")]


def default_criteria() -> list:
    """The residual targets the app used before stopping criteria existed (D-027), combined with "all"."""
    return [ResidualCriterion(field="p", threshold=1e-4), ResidualCriterion(field="U", threshold=1e-5),
            ResidualCriterion(field="k", threshold=1e-5), ResidualCriterion(field="omega", threshold=1e-5)]


class StoppingCriteria(StrictModel):
    """When the solver stops before the iteration limit (Solvers.iterations, always present).

    ``combine`` "all": the run stops when every criterion is met in the same iteration; "any": when
    one is. No criterion may stop the run before ``min_iterations``. The oscillation check (a
    warning, never a stop) flags a monitored quantity whose relative amplitude over the last
    ``oscillation_window`` iterations exceeds ``oscillation_threshold`` while its mean is not
    drifting (foam/convergence.py, D-059).
    """

    criteria: list[Criterion] = Field(default_factory=default_criteria)
    combine: Literal["all", "any"] = "all"
    min_iterations: int = Field(default=0, ge=0)
    oscillation_threshold: float = Field(default=0.01, gt=0)  # fraction of |mean|
    oscillation_window: int = Field(default=100, ge=4)


class Transient(StrictModel):
    """The time stepping, statistics and end of a transient run (schema v25, D-181) [NUMERICS-REVIEW].

    Times (``end_time``, ``write_interval``, ``sampling_start``, ``window``) are in ``time_unit``: "flow_through",
    the time the free stream takes to pass the reference length, t_c = l_ref / U (the convective time unit), or "s".

    Time step: "adaptive" (pimpleFoam's adjustTimeStep: the step follows the maximum Courant number ``max_courant``,
    never above ``max_delta_t``, starting from ``delta_t``) or "fixed" (``delta_t``). ``delta_t`` None: 1/1000 of t_c
    (adaptive: the first step, cut at once to the Courant limit by pimpleFoam) or 1/200 of t_c (fixed);
    ``max_delta_t`` None: 1/50 of t_c (at least 250 steps per period at a Strouhal number of 0.2). PIMPLE:
    ``outer_correctors`` (1: the PISO mode, enough at a Courant number up to about 1) and ``correctors`` (pressure
    corrections per outer corrector).

    Statistics: from ``sampling_start`` (None: detected from the force history once the start-up transient has
    passed, foam/transient.detect_start) to the end, the time-averaged fields (fieldAverage: mean and prime2Mean of U
    and p), the mean and RMS of every force coefficient and the Strouhal number of the lift. End: ``end_time``; with
    ``statistics_stop`` also once the running mean of ``stop_quantity`` is stable within ``tolerance`` over the last
    ``window`` (foam/transient.running_mean_stable). ``start_from`` "steady": the initial fields are the latest time
    of the project's steady solution on the same mesh (D-181)."""

    time_step: Literal["adaptive", "fixed"] = "adaptive"
    max_courant: float = Field(default=1.0, gt=0, le=50)
    delta_t: float | None = Field(default=None, gt=0)  # s
    max_delta_t: float | None = Field(default=None, gt=0)  # s
    outer_correctors: int = Field(default=1, ge=1, le=100)
    correctors: int = Field(default=2, ge=1, le=20)
    time_unit: Literal["flow_through", "s"] = "flow_through"
    end_time: float = Field(default=200.0, gt=0)
    write_interval: float = Field(default=20.0, gt=0)
    sampling_start: float | None = Field(default=None, ge=0)
    start_from: Literal["free_stream", "steady"] = "free_stream"
    statistics_stop: bool = False
    stop_quantity: str = "Cd"
    window: float = Field(default=20.0, gt=0)
    tolerance: float = Field(default=0.005, gt=0)  # relative

    @field_validator("stop_quantity")
    @classmethod
    def _known_stop_quantity(cls, value: str) -> str:
        if not is_criterion_quantity(value) or default_floor(value) is None:
            raise ValueError(f"not a force or moment coefficient: {value!r}")
        return value


class Solvers(StrictModel):
    """Solver run settings. ``iterations`` is the iteration limit (the always-present stopping
    criterion); the other criteria are in ``stopping``. ``cores``: MPI ranks of the solver (1 =
    serial); the machine's physical cores are its upper limit, checked when the solver is run
    (foam/parallel.physical_cores, D-063)."""

    iterations: int = Field(default=1000, gt=0)
    cores: int = Field(default=1, ge=1)
    write_interval: int = Field(default=200, gt=0)
    relaxation: Literal["robust"] = "robust"  # the motorBike tutorial values
    stopping: StoppingCriteria = Field(default_factory=StoppingCriteria)
    # The live view of a run started from the app (schema v24, D-172): the walls and the Results Scene's planes
    # sampled every ``live_view_interval`` iterations; never written for the benchmark and validation drivers.
    live_view: bool = True
    live_view_interval: int = Field(default=50, gt=0)
    # A transient project's time stepping, statistics and end (schema v25, D-181); a steady run ignores it.
    transient: Transient = Field(default_factory=Transient)


# Number of report slots in the monitors panel (the one place to change it).
REPORT_SLOTS = 3


class Probe(StrictModel):
    """A point probe of p and U (the probes function object, D-060). The name is part of the
    report ids (``probe:<name>:p``) and of the function object name."""

    name: str
    location: tuple[float, float, float]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not PROBE_NAME_RE.match(value):
            raise ValueError("a probe name starts with a letter and has only letters, digits and _ "
                             "(at most 32 characters)")
        return value


# -- internal flow (schema v19, D-129) ------------------------------------------------------------

# The role of a surface patch in an internal-flow analysis: the fluid is the inside of the imported closed
# geometry and every patch of it is an inlet, an outlet or a wall (the default).
PATCH_ROLES = ("inlet", "outlet", "wall")
PATCH_ROLE_LABELS = {"inlet": "Inlet", "outlet": "Outlet", "wall": "Wall"}
# Inlet kinds (D-129): a velocity normal to the patch, a mass flow rate (converted to a volumetric flow rate with
# the reference density: the solver is incompressible) or a total pressure (gauge, with an inlet velocity
# derived from the flux, inflow normal to the patch); the outlet is a static pressure (gauge).
INLET_KINDS = ("velocity", "mass_flow", "total_pressure")
INLET_KIND_LABELS = {"velocity": "Velocity inlet", "mass_flow": "Mass-flow inlet", "total_pressure": "Total-pressure inlet"}
OUTLET_KINDS = ("static_pressure",)
OUTLET_KIND_LABELS = {"static_pressure": "Static-pressure outlet"}
# The default inlet length scale is this fraction of the inlet patch's hydraulic diameter (the mixing length of
# fully developed duct flow; owner decision I2). [NUMERICS-REVIEW]
LENGTH_SCALE_OF_DH = 0.07


class InletSpec(StrictModel):
    """An internal-flow inlet (D-129). ``kind`` selects which value is used: ``speed`` (m/s, normal to the patch,
    into the domain), ``mass_flow`` (kg/s, into the domain) or ``total_pressure`` (Pa, gauge: relative to the
    outlet's reference level 0). The inlet turbulence comes from ``turbulence_intensity`` (a fraction of the
    patch velocity) and ``length_scale`` (m; None: LENGTH_SCALE_OF_DH times the patch's hydraulic diameter).
    [NUMERICS-REVIEW]"""

    kind: Literal["velocity", "mass_flow", "total_pressure"] = "velocity"
    speed: float = Field(default=1.0, gt=0)
    mass_flow: float = Field(default=1.0, gt=0)
    total_pressure: float = 0.0
    turbulence_intensity: float = Field(default=0.05, gt=0, le=1.0)
    length_scale: float | None = Field(default=None, gt=0)


class OutletSpec(StrictModel):
    """An internal-flow outlet (D-129): the static pressure ``pressure`` (Pa, gauge), backflow-safe velocity and
    turbulence. [NUMERICS-REVIEW]"""

    kind: Literal["static_pressure"] = "static_pressure"
    pressure: float = 0.0


class PatchBoundary(StrictModel):
    """The role of one surface patch in an internal-flow analysis (D-129), keyed by the patch name of the model
    (Part.patch_names(): a region's patch, or a part's own name). A patch without an entry is a wall. The inlet
    and outlet settings are kept when the role changes (switching back restores them)."""

    patch: str = Field(min_length=1)
    role: Literal["inlet", "outlet", "wall"] = "wall"
    inlet: InletSpec = Field(default_factory=InletSpec)
    outlet: OutletSpec = Field(default_factory=OutletSpec)


# A cutting plane of the internal-flow reports (D-129): mass flow and averaged pressures across the plane.
PLANE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


class CutPlane(StrictModel):
    """A plane through ``point`` with normal ``normal`` (metres) for the internal-flow reports (D-129): the
    volumetric flow through it and its area- and mass-averaged static and total pressure."""

    name: str
    point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (1.0, 0.0, 0.0)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not PLANE_NAME_RE.match(value):
            raise ValueError("a plane name starts with a letter and has only letters, digits and _ "
                             "(at most 32 characters)")
        return value

    @field_validator("normal")
    @classmethod
    def _non_zero(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if math.sqrt(sum(c * c for c in value)) == 0:
            raise ValueError("the plane normal must not be zero")
        return value


class PressureDrop(StrictModel):
    """A pressure drop between two locations (D-129): ``upstream`` minus ``downstream`` of the mass-averaged static
    and total pressure. A location is ``patch:<patch>`` (an inlet or outlet) or ``plane:<plane>``."""

    name: str
    upstream: str
    downstream: str

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not PLANE_NAME_RE.match(value):
            raise ValueError("a pressure-drop name starts with a letter and has only letters, digits and _ "
                             "(at most 32 characters)")
        return value

    @field_validator("upstream", "downstream")
    @classmethod
    def _location(cls, value: str) -> str:
        kind, sep, name = value.partition(":")
        if not sep or kind not in ("patch", "plane") or not name:
            raise ValueError("a location is 'patch:<name>' or 'plane:<name>'")
        return value


class Reports(StrictModel):
    """Reference values for the force coefficients and the report slot assignment.

    ``reference_area_basis`` picks A_ref: "planform" (bounding box x * y, the default), "frontal"
    (bounding box y * z) or "custom" (``reference_area``, m2, which is set exactly for "custom").
    The reference length (m) and centre of rotation (m) are optional overrides: None means "auto"
    from the parts' bounding box (see foam/physics_case.reference_values). The reference density is
    Physics.rho_ref and the reference speed is the inflow speed. ``slots`` holds one report id
    (core/reports.py) or None ("Not assigned") per monitor slot; ``probes`` are the point probes.
    """

    reference_area_basis: Literal["planform", "frontal", "custom"] = "planform"
    reference_area: float | None = Field(default=None, gt=0)
    reference_length: float | None = Field(default=None, gt=0)
    center_of_rotation: tuple[float, float, float] | None = None
    slots: list[str | None] = Field(
        default_factory=lambda: [None] * REPORT_SLOTS, min_length=REPORT_SLOTS, max_length=REPORT_SLOTS,
    )
    probes: list[Probe] = Field(default_factory=list)
    # Internal flow (schema v19, D-129): cutting planes and pressure drops between two locations.
    planes: list[CutPlane] = Field(default_factory=list)
    pressure_drops: list[PressureDrop] = Field(default_factory=list)

    @field_validator("planes")
    @classmethod
    def _unique_planes(cls, planes: list[CutPlane]) -> list[CutPlane]:
        names = [p.name for p in planes]
        if len(set(names)) != len(names):
            raise ValueError("plane names must be unique")
        return planes

    @field_validator("pressure_drops")
    @classmethod
    def _unique_drops(cls, drops: list[PressureDrop]) -> list[PressureDrop]:
        names = [d.name for d in drops]
        if len(set(names)) != len(names):
            raise ValueError("pressure-drop names must be unique")
        return drops

    @field_validator("slots")
    @classmethod
    def _known_reports(cls, slots: list[str | None]) -> list[str | None]:
        for report_id in slots:
            if report_id is not None and not is_report_id(report_id):
                raise ValueError(f"unknown report {report_id!r}")
        return slots

    @field_validator("probes")
    @classmethod
    def _unique_probes(cls, probes: list[Probe]) -> list[Probe]:
        names = [p.name for p in probes]
        if len(set(names)) != len(names):
            raise ValueError("probe names must be unique")
        return probes

    @model_validator(mode="before")
    @classmethod
    def _area_without_basis_is_custom(cls, data):
        # v4 files written before the basis existed (unpublished) carried only reference_area.
        if isinstance(data, dict) and data.get("reference_area") is not None and "reference_area_basis" not in data:
            data = {**data, "reference_area_basis": "custom"}
        return data

    @model_validator(mode="after")
    def _custom_area(self) -> "Reports":
        if self.reference_area_basis == "custom" and self.reference_area is None:
            raise ValueError("reference_area_basis 'custom' needs reference_area")
        if self.reference_area_basis != "custom" and self.reference_area is not None:
            raise ValueError("reference_area is set only with reference_area_basis 'custom'")
        return self


# Domain shapes (D-019, D-078): "box" (upstream / downstream / lateral / vertical), "bullet" (a
# hemisphere of radius R at the front and a cylinder behind it, axis along +x) and "c_type" (a front
# half-cylinder of radius R whose axis is spanwise, flat top and bottom, flat spanwise sides).
DOMAIN_SHAPES = ("box", "bullet", "c_type")


class Ground(StrictModel):
    """The ground plane of a box domain (schema v16, D-116): its bottom face (z-min) becomes the no-slip
    wall patch "ground" instead of the slip far field "bottom". [NUMERICS-REVIEW]

    ``motion``: "stationary" (noSlip) or "moving" (fixed tangential velocity: the free-stream speed along
    +x, the flow direction projected on the ground). ``position``: "parts_min" puts the plane at the
    lowest z of the parts the domain is sized around; "value" at ``z`` (metres), e.g. below the parts'
    lowest point when supports cross the plane. ``layers``: prism layers on the ground (off by default).
    The same wall functions as the parts in every case. ``wall_start_x`` (schema v17, D-118): the x
    (metres) where the wall starts; upstream of it the bottom face is the slip patch "ground_slip" (a
    slip strip, so the ground boundary layer starts there). None: the wall starts at the inlet.
    """

    enabled: bool = False
    motion: Literal["stationary", "moving"] = "stationary"
    position: Literal["parts_min", "value"] = "parts_min"
    z: float = 0.0
    layers: bool = False
    wall_start_x: float | None = None


# The boundary type of each domain face (schema v22, D-147) [NUMERICS-REVIEW]. The defaults are the conditions every
# domain had before (D-019, D-078): a velocity inlet, a pressure outlet and slip far-field faces.
BOUNDARY_KINDS = ("velocity_inlet", "pressure_outlet", "slip", "symmetry", "wall", "moving_wall")
BOUNDARY_KIND_LABELS = {  # short: the face's conditions are shown beside the choice (D-148)
    "velocity_inlet": "Velocity inlet",
    "pressure_outlet": "Pressure outlet",
    "slip": "Slip (far field)",
    "symmetry": "Symmetry",
    "wall": "Wall",
    "moving_wall": "Moving wall",
}
DEFAULT_FACE_KINDS = {"inlet": "velocity_inlet", "outlet": "pressure_outlet", "sides": "slip", "top": "slip",
                      "bottom": "slip", "farfield": "slip"}
EDITABLE_FACES = tuple(DEFAULT_FACE_KINDS)


DOMAIN_EXTENTS = ("upstream", "downstream", "lateral", "vertical", "radius")
ABSOLUTE_UNITS = {"m": 1.0, "mm": 1e-3}  # an extent given in metres or millimetres (schema v23, D-157)


class Domain(StrictModel):
    """Far-field domain around the parts, in multiples of the reference length L.

    L is the largest extent of the union of the bounding boxes of the parts the domain is sized
    around (``parts``: their names; None = every part). The flow runs along +x. ``enabled`` False:
    no domain has been generated yet (the "Empty" analysis starts so, D-078).

    The fields a shape uses: box: upstream, downstream, lateral, vertical; bullet: radius,
    downstream; c_type: radius, downstream, lateral (the spanwise half-width). ``downstream`` is
    measured from the parts' rear (largest x) for every shape; the rounded shapes are centred on the
    parts' centre (D-078).
    """

    enabled: bool = True
    shape: Literal["box", "bullet", "c_type"] = "box"
    upstream: float = Field(default=5.0, gt=0)
    downstream: float = Field(default=10.0, gt=0)
    lateral: float = Field(default=5.0, gt=0)
    vertical: float = Field(default=5.0, gt=0)
    radius: float = Field(default=5.0, gt=0)
    symmetry: Literal["none", "y_min"] = "none"
    parts: list[str] | None = None
    ground: Ground = Field(default_factory=Ground)
    # A face's boundary type when it is not its default (DEFAULT_FACE_KINDS; schema v22, D-147). Defaults are dropped,
    # so a domain left as it was has none and writes the dictionaries it always wrote.
    boundary_types: dict[str, str] = Field(default_factory=dict)
    # The unit of an extent entered in metres or millimetres (schema v23, D-157): its value is then in that unit and
    # stays that length when L changes. An extent without an entry is in multiples of L ("L" entries are dropped).
    units: dict[str, Literal["L", "m", "mm"]] = Field(default_factory=dict)
    # The wall faces given the parts' prism layers (schema v23, D-161; off by default): only a face whose boundary
    # type is a wall or a moving wall gets them. [NUMERICS-REVIEW]
    wall_layers: list[str] = Field(default_factory=list)

    @field_validator("wall_layers")
    @classmethod
    def _known_layer_faces(cls, value: list[str]) -> list[str]:
        for face in value:
            if face not in DEFAULT_FACE_KINDS:
                raise ValueError(f"unknown domain face {face!r} (one of {', '.join(EDITABLE_FACES)})")
        return sorted(set(value))

    @field_validator("units")
    @classmethod
    def _known_extents(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if name not in DOMAIN_EXTENTS:
                raise ValueError(f"unknown domain extent {name!r} (one of {', '.join(DOMAIN_EXTENTS)})")
        return {name: unit for name, unit in value.items() if unit != "L"}

    def extent_unit(self, name: str) -> str:
        """"L", "m" or "mm": the unit the extent ``name`` is stored in."""
        return self.units.get(name, "L")

    def extent_m(self, name: str, length: float) -> float:
        """The extent ``name`` in metres, with the reference length ``length`` (m) for an extent in L."""
        value = getattr(self, name)
        unit = self.units.get(name)
        return value * length if unit is None else value * ABSOLUTE_UNITS[unit]

    @field_validator("boundary_types")
    @classmethod
    def _known_face_kinds(cls, value: dict[str, str]) -> dict[str, str]:
        out = {}
        for face, kind in value.items():
            if face not in DEFAULT_FACE_KINDS:
                raise ValueError(f"unknown domain face {face!r} (one of {', '.join(EDITABLE_FACES)})")
            if kind not in BOUNDARY_KINDS:
                raise ValueError(f"unknown boundary type {kind!r} (one of {', '.join(BOUNDARY_KINDS)})")
            if kind != DEFAULT_FACE_KINDS[face]:
                out[face] = kind
        return out

    def face_kind(self, face: str) -> str:
        """The boundary type of a domain face (its default unless changed, D-147)."""
        return self.boundary_types.get(face, DEFAULT_FACE_KINDS.get(face, "slip"))

    @model_validator(mode="after")
    def _ground_on_a_box(self) -> "Domain":
        if self.ground.enabled and self.shape != "box":
            raise ValueError("the ground plane needs the box domain shape")
        return self

    @field_validator("parts")
    @classmethod
    def _parts_listed_once(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("a part is listed twice in the domain")
        return value


class MeshStudySettings(StrictModel):
    """Mesh independence study (D-066): three meshes with a constant refinement ratio ``ratio`` in
    linear cell size; the current mesh settings are the ``current_as`` level ("fine": the study
    adds two coarser levels; "medium": one coarser and one finer); ``quantities`` are report ids
    (core/reports.py) judged with the Celik GCI; ``cores``: MPI ranks of each level's run."""

    ratio: float = Field(default=math.sqrt(2.0), ge=1.3, le=4.0)
    current_as: Literal["fine", "medium"] = "fine"
    quantities: list[str] = Field(default_factory=lambda: ["Cd"])
    cores: int = Field(default=1, ge=1)

    @field_validator("quantities")
    @classmethod
    def _known_quantities(cls, values: list[str]) -> list[str]:
        for q in values:
            if not is_report_id(q):
                raise ValueError(f"unknown report {q!r}")
        if len(set(values)) != len(values):
            raise ValueError("a quantity is listed twice")
        return values


class PolarSweepSettings(StrictModel):
    """Angle-of-attack sweep (D-067, D-120): ``mode`` "range" runs start, start + step, ... up to end
    (inclusive within 1e-9), "list" runs ``values`` in their order; every angle gets its own mesh (the
    parts rotated, meshed on the project's meshing cores) and a run from the uniform free stream, one
    angle at a time (schema v18 dropped ``init_from_previous``: the meshes differ)."""

    # Opt-in (schema v22, D-148): off for new projects, the sweep's rows and Run appear once it is enabled; projects
    # saved before v22 keep it on (it was always offered).
    enabled: bool = False
    mode: Literal["range", "list"] = "range"
    start: float = Field(default=0.0, ge=-90.0, le=90.0)
    end: float = Field(default=10.0, ge=-90.0, le=90.0)
    step: float = Field(default=2.0, gt=0.0)
    values: list[float] = Field(default_factory=list)
    cores: int = Field(default=1, ge=1)

    @field_validator("values")
    @classmethod
    def _angles(cls, values: list[float]) -> list[float]:
        for v in values:
            if not -90.0 <= v <= 90.0:
                raise ValueError("an angle of attack must be within -90 and 90 degrees")
        return values

    def alphas(self) -> list[float]:
        """The angles of attack of the sweep, in run order."""
        if self.mode == "list":
            return list(self.values)
        out, n = [], 0
        direction = 1.0 if self.end >= self.start else -1.0
        while True:
            a = self.start + direction * n * self.step
            if direction * (a - self.end) > 1e-9:
                break
            out.append(round(a, 9))
            n += 1
            if n > 1000:
                break
        return out


class Studies(StrictModel):
    """Multi-run studies (schema v7)."""

    mesh: MeshStudySettings = Field(default_factory=MeshStudySettings)
    polar: PolarSweepSettings = Field(default_factory=PolarSweepSettings)


# -- user refinement volumes (schema v12, D-103) -------------------------------------------------

Vector = tuple[float, float, float]
# A volume name is part of the snappyHexMesh geometry and refinementRegions entries.
VOLUME_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
VOLUME_SHAPES = ("box", "cylinder", "sphere", "cone")


class BoxShape(StrictModel):
    """A box: its centre, its edge lengths along its own axes (e1, e2, e3) and its orientation: ``pitch_deg``
    tilts e1 from +x towards +z (nose-up positive, as the angle of attack), then ``yaw_deg`` turns it
    about z (counter-clockwise seen from +z). Both 0: the box is aligned with x, y, z."""

    kind: Literal["box"] = "box"
    centre: Vector = (0.0, 0.0, 0.0)
    size: Vector = (1.0, 1.0, 1.0)
    pitch_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    yaw_deg: float = Field(default=0.0, ge=-360.0, le=360.0)

    @property
    def rotated(self) -> bool:
        return self.pitch_deg != 0.0 or self.yaw_deg % 360.0 != 0.0

    def axes(self) -> tuple[Vector, Vector, Vector]:
        """The box's unit axes: e1 = (cos p cos y, cos p sin y, sin p), e2 = (-sin y, cos y, 0),
        e3 = e1 x e2 = (-sin p cos y, -sin p sin y, cos p)."""
        p, y = math.radians(self.pitch_deg), math.radians(self.yaw_deg)
        cp, sp, cy, sy = math.cos(p), math.sin(p), math.cos(y), math.sin(y)
        return (cp * cy, cp * sy, sp), (-sy, cy, 0.0), (-sp * cy, -sp * sy, cp)

    @field_validator("size")
    @classmethod
    def _positive(cls, value: Vector) -> Vector:
        if any(v <= 0 for v in value):
            raise ValueError("every box edge must be longer than zero")
        return value


class CylinderShape(StrictModel):
    """A cylinder between two end points."""

    kind: Literal["cylinder"] = "cylinder"
    point1: Vector = (0.0, 0.0, 0.0)
    point2: Vector = (1.0, 0.0, 0.0)
    radius: float = Field(default=0.5, gt=0)

    @model_validator(mode="after")
    def _distinct(self) -> "CylinderShape":
        if self.point1 == self.point2:
            raise ValueError("the two end points of a cylinder must differ")
        return self


class SphereShape(StrictModel):
    kind: Literal["sphere"] = "sphere"
    centre: Vector = (0.0, 0.0, 0.0)
    radius: float = Field(default=0.5, gt=0)


class ConeShape(StrictModel):
    """A cone (or truncated cone) between two end points with a radius at each: wake regions."""

    kind: Literal["cone"] = "cone"
    point1: Vector = (0.0, 0.0, 0.0)
    point2: Vector = (1.0, 0.0, 0.0)
    radius1: float = Field(default=0.25, ge=0)
    radius2: float = Field(default=0.5, ge=0)

    @model_validator(mode="after")
    def _valid(self) -> "ConeShape":
        if self.point1 == self.point2:
            raise ValueError("the two end points of a cone must differ")
        if self.radius1 <= 0 and self.radius2 <= 0:
            raise ValueError("at least one cone radius must be larger than zero")
        return self


class OrientedBoxShape(BoxShape):
    """A box with explicit unit axes e1 and e3 (e2 = e3 x e1): a body-frame box turned by the angle of
    attack (geometry/attitude.rotate_shape, D-120), which pitch and yaw alone cannot always express. Made
    for the meshing case only; never stored in a project (pitch_deg and yaw_deg are unused)."""

    e1: Vector = (1.0, 0.0, 0.0)
    e3: Vector = (0.0, 0.0, 1.0)

    @property
    def rotated(self) -> bool:
        return True

    def axes(self) -> tuple[Vector, Vector, Vector]:
        e1, e3 = self.e1, self.e3
        e2 = (e3[1] * e1[2] - e3[2] * e1[1], e3[2] * e1[0] - e3[0] * e1[2], e3[0] * e1[1] - e3[1] * e1[0])
        return e1, e2, e3


class SurfaceShape(StrictModel):
    """An imported closed surface as a refinement region (schema v22, D-145): ``file`` (relative to the project
    folder, in geometry/) in ``units``; "inside" refines every cell inside the surface, "distance" every cell
    within ``distance`` metres of it (either side). The surface is never meshed as a wall."""

    kind: Literal["surface"] = "surface"
    file: str = Field(min_length=1)
    units: Literal["m", "cm", "mm", "in", "ft"] = "m"
    mode: Literal["inside", "distance"] = "inside"
    distance: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _distance_set(self) -> "SurfaceShape":
        if self.mode == "distance" and self.distance <= 0:
            raise ValueError("a distance-mode refinement region needs a distance larger than zero")
        return self


VolumeShape = Annotated[Union[BoxShape, CylinderShape, SphereShape, ConeShape, SurfaceShape],
                        Field(discriminator="kind")]


class RefinementVolume(StrictModel):
    """A user refinement volume (D-103): every cell inside it is refined to the level whose cell size is
    the first at or below ``target_size`` (metres). ``id`` is stable across renames; ``name`` is unique
    and file-safe (it names the snappyHexMesh entries). Volumes belong to the project's geometry and are
    not part of presets. ``frame`` (schema v18, D-120): "body" volumes turn with the parts at an angle of
    attack (the default: they were placed on the parts as imported); "wind" volumes stay where they are
    (the wake helper's: along the free stream, +x)."""

    id: str = Field(min_length=1, max_length=32)
    name: str
    shape: VolumeShape
    target_size: float = Field(gt=0)
    enabled: bool = True
    frame: Literal["body", "wind"] = "body"

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not VOLUME_NAME_RE.match(value):
            raise ValueError("a volume name starts with a letter and has only letters, digits and _ "
                             "(at most 64 characters)")
        return value


# -- results scene objects (schema v20, D-132) -----------------------------------------------------

SCENE_OBJECT_KINDS = ("clip", "isosurface", "streamlines", "line_plot")
SCENE_OBJECT_LABELS = {"clip": "Clip", "isosurface": "Isosurface", "streamlines": "Streamlines",
                       "line_plot": "Line plot"}
# The colour range modes of the scene and of the streamlines' own colour field (schema v21).
COLOR_RANGE_MODES = ("auto", "fixed", "symmetric")
SCENE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ .-]{0,63}$")


class _SceneObject(StrictModel):
    """A results scene object (D-132): an item under Results with an id that survives renames, a name and a
    visibility. Its geometry is computed from the latest results (workflow/results_objects.py)."""

    id: str = Field(min_length=1, max_length=32)
    name: str
    visible: bool = True

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not SCENE_NAME_RE.match(value):
            raise ValueError("a name has letters, digits, spaces and _ . - (at most 64 characters)")
        return value


class ClipObject(_SceneObject):
    """The fluid volume clipped by the plane through ``origin`` with ``normal``; ``keep`` "behind" keeps the side the
    normal points away from, "front" the side it points to. Coloured by the scene's field."""

    kind: Literal["clip"] = "clip"
    origin: Vector = (0.0, 0.0, 0.0)
    normal: Vector = (1.0, 0.0, 0.0)
    keep: Literal["behind", "front"] = "behind"

    @field_validator("normal")
    @classmethod
    def _non_zero(cls, value: Vector) -> Vector:
        if math.sqrt(sum(c * c for c in value)) == 0:
            raise ValueError("the normal must not be zero")
        return value


class IsoObject(_SceneObject):
    """The surface where ``field`` (a scalar field key of foam/results.FIELD_SPECS) equals ``value``. Coloured by the
    scene's field."""

    kind: Literal["isosurface"] = "isosurface"
    field: str = "U_mag"
    value: float = 0.0


class StreamlinesObject(_SceneObject):
    """Streamlines of U from ``n_seeds`` seeds on a line (``point1`` to ``point2``) or on a square plane (centre
    ``point1``, normal ``normal``, side ``size``), integrated ``direction`` (both ways by default) up to
    ``max_length`` metres, coloured by ``color_field``."""

    kind: Literal["streamlines"] = "streamlines"
    seed: Literal["line", "plane"] = "line"
    point1: Vector = (0.0, 0.0, 0.0)
    point2: Vector = (0.0, 0.0, 1.0)
    normal: Vector = (1.0, 0.0, 0.0)
    size: float = Field(default=1.0, gt=0)
    n_seeds: int = Field(default=20, ge=1, le=10_000)
    max_length: float = Field(default=10.0, gt=0)
    direction: Literal["both", "forward", "backward"] = "both"
    color_field: str = "U_mag"
    # Their own scalar bar (schema v21): the colormap (None: the scene's), the range mode and the fixed limits, as
    # the scene's controls; ``scalar_bar`` False hides the bar.
    colormap: str | None = None
    range_mode: Literal["auto", "fixed", "symmetric"] = "auto"
    range_min: float = 0.0
    range_max: float = 1.0
    scalar_bar: bool = True


class LinePlotObject(_SceneObject):
    """Fields sampled at ``n_samples`` evenly spaced points from ``point1`` to ``point2`` (schema v21): a chart of
    each field against the distance from ``point1``, exported as PNG and CSV; the viewer draws the line."""

    kind: Literal["line_plot"] = "line_plot"
    point1: Vector = (0.0, 0.0, 0.0)
    point2: Vector = (1.0, 0.0, 0.0)
    n_samples: int = Field(default=100, ge=2, le=10_000)
    fields: list[str] = Field(default_factory=lambda: ["U_mag"], min_length=1, max_length=8)

    @model_validator(mode="after")
    def _distinct_points(self) -> "LinePlotObject":
        if tuple(self.point1) == tuple(self.point2):
            raise ValueError("the line's two points must differ")
        return self


SceneObject = Annotated[Union[ClipObject, IsoObject, StreamlinesObject, LinePlotObject], Field(discriminator="kind")]

# The HTML report's sections (schema v21, D-136): id -> title, in report order.
REPORT_SECTIONS = {
    "setup": "Project and set-up",
    "geometry": "Geometry",
    "mesh": "Mesh report",
    "convergence": "Convergence",
    "reports": "Forces / internal-flow reports",
    "study": "Mesh independence study",
    "sweep": "Polar sweep",
    "line_plots": "Line plots",
    "comparison": "Comparison (the snapshots chosen in the Compare tab)",
    "views": "Saved views",
}


class SavedView(StrictModel):
    """A camera of the viewer saved by name (D-132): the report renders each one."""

    name: str = Field(min_length=1, max_length=64)
    position: Vector
    focal_point: Vector
    view_up: Vector
    parallel: bool = False
    parallel_scale: float = 1.0


class ResultsScene(StrictModel):
    """The results scene objects and the saved views (schema v20, D-132)."""

    objects: list[SceneObject] = Field(default_factory=list)
    views: list[SavedView] = Field(default_factory=list)
    # The report sections left out (schema v21, D-136): ids of REPORT_SECTIONS; a section added later is included.
    report_omit: list[str] = Field(default_factory=list)

    @field_validator("report_omit")
    @classmethod
    def _known_sections(cls, values: list[str]) -> list[str]:
        unknown = [v for v in values if v not in REPORT_SECTIONS]
        if unknown:
            raise ValueError(f"unknown report sections: {', '.join(unknown)}")
        return list(dict.fromkeys(values))

    @field_validator("objects")
    @classmethod
    def _unique_ids(cls, values: list) -> list:
        ids = [v.id for v in values]
        if len(set(ids)) != len(ids):
            raise ValueError("two scene objects have the same id")
        return values

    @field_validator("views")
    @classmethod
    def _unique_views(cls, values: list[SavedView]) -> list[SavedView]:
        names = [v.name for v in values]
        if len(set(names)) != len(names):
            raise ValueError("two saved views have the same name")
        return values


# Analysis types (schema v9, D-077): "external" (a far-field domain generated around the parts on the
# first import), "empty" (nothing created automatically: the domain is a "Generate domain"
# operation) and "internal" (schema v19, D-129: the fluid is the inside of the closed geometry; no domain,
# every surface patch is an inlet, an outlet or a wall).
ANALYSIS_TYPES = ("external", "empty", "internal")
RESERVED_ANALYSIS_TYPES: tuple[str, ...] = ()
ANALYSIS_TYPE_LABELS = {"external": "External flow", "empty": "Empty", "internal": "Internal flow"}
# The analysis dimension (schema v18, D-121): "3d", or "2d", a section in the x-z plane meshed as one cell
# across the span (y) with empty front and back patches.
DIMENSIONS = ("3d", "2d")
DIMENSION_LABELS = {"3d": "3D", "2d": "2D section (x-z plane)"}


class Simulation(StrictModel):
    """Root simulation tree data model.

    ``analysis_type``: see ANALYSIS_TYPES. ``preset_name``: the preset the project was created from
    (provenance only: nothing reads it back, D-077).
    """

    schema_version: int = Field(
        default=CURRENT_SCHEMA_VERSION, ge=1, le=CURRENT_SCHEMA_VERSION
    )
    name: str
    analysis_type: Literal["external", "empty", "internal"] = "external"
    dimension: Literal["3d", "2d"] = "3d"
    preset_name: str | None = None
    geometry: Geometry = Field(default_factory=Geometry)
    domain: Domain = Field(default_factory=Domain)
    mesh: Mesh = Field(default_factory=Mesh)
    physics: Physics = Field(default_factory=Physics)
    inflow: Inflow = Field(default_factory=Inflow)
    solvers: Solvers = Field(default_factory=Solvers)
    reports: Reports = Field(default_factory=Reports)
    studies: Studies = Field(default_factory=Studies)
    surface_prep: SurfacePrep | None = None
    refinement_volumes: list[RefinementVolume] = Field(default_factory=list)
    # Internal flow (schema v19, D-129): the role of each patch (a patch not listed is a wall).
    boundaries: list[PatchBoundary] = Field(default_factory=list)
    # The results scene objects and saved views (schema v20, D-132).
    results: ResultsScene = Field(default_factory=ResultsScene)

    @property
    def internal(self) -> bool:
        return self.analysis_type == "internal"

    def boundary(self, patch: str) -> PatchBoundary:
        """The patch's boundary (a wall when it has no entry)."""
        return next((b for b in self.boundaries if b.patch == patch), PatchBoundary(patch=patch))

    @field_validator("boundaries")
    @classmethod
    def _unique_boundaries(cls, values: list[PatchBoundary]) -> list[PatchBoundary]:
        names = [b.patch for b in values]
        if len(set(names)) != len(names):
            raise ValueError("a patch has two boundary entries")
        return values

    @model_validator(mode="after")
    def _two_d_domain(self) -> "Simulation":
        if self.dimension == "2d":
            if self.domain.shape == "bullet":
                raise ValueError("a 2D section needs the box or C-type domain shape")
            if self.domain.symmetry != "none":
                raise ValueError("a 2D section has no symmetry plane")
        return self

    @field_validator("refinement_volumes")
    @classmethod
    def _unique_volumes(cls, values: list[RefinementVolume]) -> list[RefinementVolume]:
        ids = [v.id for v in values]
        names = [v.name.casefold() for v in values]
        if len(set(ids)) != len(ids):
            raise ValueError("two refinement volumes have the same id")
        if len(set(names)) != len(names):
            raise ValueError("two refinement volumes have the same name (names are compared ignoring case)")
        return values
