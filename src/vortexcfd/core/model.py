"""Simulation tree data models."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_SCHEMA_VERSION: int = 4


class StrictModel(BaseModel):
    """Base model that forbids unknown fields."""

    model_config = ConfigDict(extra="forbid")


class Part(StrictModel):
    """A geometric part defined by a source mesh file."""

    name: str
    source_file: str
    units: Literal["m", "cm", "mm", "in", "ft"] = "m"


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


class Solvers(StrictModel):
    """Solver run settings."""

    iterations: int = Field(default=1000, gt=0)
    write_interval: int = Field(default=200, gt=0)
    relaxation: Literal["robust"] = "robust"  # the motorBike tutorial values
    # SIMPLE residualControl: the run stops when the initial residuals fall below these targets.
    residual_p: float = Field(default=1e-4, gt=0)
    residual_u: float = Field(default=1e-5, gt=0)
    residual_k: float = Field(default=1e-5, gt=0)
    residual_omega: float = Field(default=1e-5, gt=0)


# Number of report slots in the monitors panel (the one place to change it).
REPORT_SLOTS = 3
# Reports a slot can show: forceCoeffs coefficients and the yPlus function object's wall values.
REPORT_IDS = ("Cd", "Cl", "CmPitch", "yplus_min", "yplus_avg", "yplus_max")


class Reports(StrictModel):
    """Reference values for the force coefficients and the report slot assignment.

    The reference area (m2), length (m) and centre of rotation (m) are optional overrides:
    None means "auto" from the parts' bounding box (see foam/physics_case.reference_values).
    The reference density is Physics.rho_ref and the reference speed is the inflow speed.
    ``slots`` holds one report id (REPORT_IDS) or None ("Not assigned") per monitor slot.
    """

    reference_area: float | None = Field(default=None, gt=0)
    reference_length: float | None = Field(default=None, gt=0)
    center_of_rotation: tuple[float, float, float] | None = None
    slots: list[Literal["Cd", "Cl", "CmPitch", "yplus_min", "yplus_avg", "yplus_max"] | None] = Field(
        default_factory=lambda: [None] * REPORT_SLOTS, min_length=REPORT_SLOTS, max_length=REPORT_SLOTS,
    )


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
