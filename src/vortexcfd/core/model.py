"""Simulation tree data models."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CURRENT_SCHEMA_VERSION: int = 1


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


class Simulation(StrictModel):
    """Root simulation tree data model."""

    schema_version: int = Field(
        default=CURRENT_SCHEMA_VERSION, ge=1, le=CURRENT_SCHEMA_VERSION
    )
    name: str
    geometry: Geometry = Field(default_factory=Geometry)
    mesh: Mesh = Field(default_factory=Mesh)
    physics: Physics = Field(default_factory=Physics)
    solvers: Solvers = Field(default_factory=Solvers)
    reports: Reports = Field(default_factory=Reports)
