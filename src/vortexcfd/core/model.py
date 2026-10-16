"""Simulation tree data models."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

CURRENT_SCHEMA_VERSION: int = 2


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

    @model_validator(mode="after")
    def _levels_ordered(self) -> "Mesh":
        lo, hi = self.surface_level_min, self.surface_level_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("surface_level_max must be >= surface_level_min")
        return self


class Physics(StrictModel):
    """Placeholder model for physics continuum; fields will be added by later tasks."""


class Solvers(StrictModel):
    """Placeholder model for solver settings; fields will be added by later tasks."""


class Reports(StrictModel):
    """Placeholder model for monitors and reports; fields will be added by later tasks."""


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
    solvers: Solvers = Field(default_factory=Solvers)
    reports: Reports = Field(default_factory=Reports)
