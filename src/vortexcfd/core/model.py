"""Simulation tree data models."""

import math
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vortexcfd.core.reports import PROBE_NAME_RE, default_floor, is_criterion_quantity, is_report_id

CURRENT_SCHEMA_VERSION: int = 7


class StrictModel(BaseModel):
    """Base model that forbids unknown fields."""

    model_config = ConfigDict(extra="forbid")


class Part(StrictModel):
    """A geometric part defined by a source mesh file.

    ``surface_level_min`` / ``surface_level_max`` override the mesh's surface refinement levels for
    this part only (None = the mesh's levels; setting only the max gives min = max - 1, as for the
    mesh). A part that is small relative to the background mesh is seeded with feature lines
    automatically so snappyHexMesh finds it (D-052).
    """

    name: str
    source_file: str
    units: Literal["m", "cm", "mm", "in", "ft"] = "m"
    surface_level_min: int | None = Field(default=None, ge=0)
    surface_level_max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _levels_ordered(self) -> "Part":
        lo, hi = self.surface_level_min, self.surface_level_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("surface_level_max must be >= surface_level_min")
        return self


class Geometry(StrictModel):
    """Geometry container holding simulation parts."""

    parts: list[Part] = Field(default_factory=list)


class Mesh(StrictModel):
    """snappyHexMesh controls (mesher level M1).

    Sizing is derived from two targets unless overridden: the background mesh gets about
    ``background_cells_target`` cells (so ``base_size`` = (domain volume / target)^(1/3)), and
    the surface cells aim at ``target_surface_size`` times L (L = largest extent of the parts), which
    fixes the refinement levels. ``base_size`` (metres) and the two surface levels are optional
    explicit overrides (None = computed). ``final_layer_thickness`` and ``min_thickness`` are
    relative to the local cell size.
    """

    background_cells_target: int = Field(default=100_000, gt=0)
    target_surface_size: float = Field(default=0.01, gt=0)  # relative to L
    base_size: float | None = Field(default=None, gt=0)
    surface_level_min: int | None = Field(default=None, ge=0)
    surface_level_max: int | None = Field(default=None, ge=0)
    feature_angle: float = Field(default=30.0, gt=0, le=180)
    layers: int = Field(default=3, ge=0)
    expansion_ratio: float = Field(default=1.2, ge=1.0)
    final_layer_thickness: float = Field(default=0.5, gt=0)
    min_thickness: float = Field(default=0.1, gt=0)
    # "relative": layer sizes relative to the local cell; "absolute_yplus": the first layer
    # thickness follows from target_yplus (see foam/yplus.py), expansion_ratio is reused.
    layer_sizing: Literal["relative", "absolute_yplus"] = "relative"
    target_yplus: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _levels_ordered(self) -> "Mesh":
        lo, hi = self.surface_level_min, self.surface_level_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("surface_level_max must be >= surface_level_min")
        return self


class Physics(StrictModel):
    """Flow physics. Only steady incompressible kOmegaSST for now.

    ``nu`` is the kinematic viscosity (m2/s); ``rho_ref`` (kg/m3) is used only to scale forces
    (the solver is incompressible, pressure is kinematic).
    """

    flow: Literal["incompressible_steady"] = "incompressible_steady"
    nu: float = Field(default=1.5e-5, gt=0)
    rho_ref: float = Field(default=1.225, gt=0)
    turbulence_model: Literal["kOmegaSST"] = "kOmegaSST"


class Inflow(StrictModel):
    """Free-stream conditions at the inlet. The flow is along +x rotated by the angle of attack
    about +y (z up); the turbulence comes from the intensity and the viscosity ratio."""

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


Criterion = Annotated[Union[ResidualCriterion, AsymptoticCriterion], Field(discriminator="kind")]


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


class Domain(StrictModel):
    """Far-field domain around the parts, in multiples of the reference length L.

    L is the largest extent of the union of the parts' bounding boxes. The flow runs along +x.
    """

    enabled: bool = True
    upstream: float = Field(default=5.0, gt=0)
    downstream: float = Field(default=10.0, gt=0)
    lateral: float = Field(default=5.0, gt=0)
    vertical: float = Field(default=5.0, gt=0)
    symmetry: Literal["none", "y_min"] = "none"


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


class Studies(StrictModel):
    """Multi-run studies (schema v7)."""

    mesh: MeshStudySettings = Field(default_factory=MeshStudySettings)


class Simulation(StrictModel):
    """Root simulation tree data model."""

    schema_version: int = Field(
        default=CURRENT_SCHEMA_VERSION, ge=1, le=CURRENT_SCHEMA_VERSION
    )
    name: str
    geometry: Geometry = Field(default_factory=Geometry)
    domain: Domain = Field(default_factory=Domain)
    mesh: Mesh = Field(default_factory=Mesh)
    physics: Physics = Field(default_factory=Physics)
    inflow: Inflow = Field(default_factory=Inflow)
    solvers: Solvers = Field(default_factory=Solvers)
    reports: Reports = Field(default_factory=Reports)
    studies: Studies = Field(default_factory=Studies)
