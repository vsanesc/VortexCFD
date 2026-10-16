"""Simulation tree data models."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

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
    """Placeholder model for mesh controls; fields will be added by later tasks."""


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
