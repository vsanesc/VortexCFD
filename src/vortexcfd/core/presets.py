"""Analysis presets: the starting set-up of a new simulation (D-077).

A preset holds ONLY the analysis type, the domain shape, sizes and symmetry, the default boundary
type of every boundary role and the mesh settings. It never carries physics, turbulence, inflow or
solver settings (owner decision): those always start from the model defaults.

Built-in presets are defined here and are read-only. User presets are versioned JSON files in a
folder the caller passes (the GUI uses the user config directory); a file that does not validate
is listed as broken and never raises. A preset carries the project schema version it was written with
and is migrated like a project: a preset written before schema v10 keeps the v9 mesh behaviour
(``migrate_preset``, D-090).
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_serializer, field_validator

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Mesh, Simulation, StrictModel
from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR, V13_MESH_FIELDS, V14_MESH_FIELDS

# 1: no schema_version (every such file was written before schema v10); 2: schema_version (D-090).
PRESET_FORMAT_VERSION = 2
PRESET_SUFFIX = ".json"

# Boundary roles of the domain shapes (geometry/domain.py) and the one boundary type each role has
# today (foam/physics_case.py writes them; there is no per-role choice in the model yet).
BOUNDARY_ROLES = ("inlet", "outlet", "farfield", "sides", "top", "bottom", "symmetry")
DEFAULT_BOUNDARY_TYPES: dict[str, str] = {
    "inlet": "velocity_inlet",
    "outlet": "pressure_outlet",
    "farfield": "slip",
    "sides": "slip",
    "top": "slip",
    "bottom": "slip",
    "symmetry": "symmetry",
}
ALLOWED_BOUNDARY_TYPES: dict[str, tuple[str, ...]] = {role: (t,) for role, t in DEFAULT_BOUNDARY_TYPES.items()}

# The domain fields a preset carries (Domain minus "enabled", which follows the analysis type, and
# "parts", which belongs to a project's geometry).
DOMAIN_FIELDS = ("shape", "upstream", "downstream", "lateral", "vertical", "radius", "symmetry")


class PresetError(ValueError):
    """A preset operation was refused; the message says why."""


class PresetDomain(StrictModel):
    shape: Literal["box", "bullet", "c_type"] = "box"
    upstream: float = Field(default=5.0, gt=0)
    downstream: float = Field(default=10.0, gt=0)
    lateral: float = Field(default=5.0, gt=0)
    vertical: float = Field(default=5.0, gt=0)
    radius: float = Field(default=5.0, gt=0)
    symmetry: Literal["none", "y_min"] = "none"


class Preset(StrictModel):
    """One preset (file format version PRESET_FORMAT_VERSION)."""

    format_version: int = Field(default=PRESET_FORMAT_VERSION, ge=1, le=PRESET_FORMAT_VERSION)
    # The project schema version the preset's settings follow (D-090).
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=1, le=CURRENT_SCHEMA_VERSION)
    name: str
    analysis_type: Literal["external", "empty"] = "external"
    domain: PresetDomain = Field(default_factory=PresetDomain)
    boundary_types: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_BOUNDARY_TYPES))
    mesh: Mesh = Field(default_factory=Mesh)

    @field_serializer("mesh")
    def _mesh_without_cores(self, mesh: Mesh) -> dict:
        """The meshing cores belong to the machine, like the solver's: a preset never carries them and a
        project made from one meshes with automatic cores (D-111)."""
        return mesh.model_dump(exclude={"cores"})

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return validate_preset_name(value)

    @field_validator("boundary_types")
    @classmethod
    def _known_types(cls, value: dict[str, str]) -> dict[str, str]:
        for role, kind in value.items():
            if role not in ALLOWED_BOUNDARY_TYPES:
                raise ValueError(f"unknown boundary role {role!r}")
            if kind not in ALLOWED_BOUNDARY_TYPES[role]:
                raise ValueError(f"boundary type {kind!r} is not available for {role} "
                                 f"(available: {', '.join(ALLOWED_BOUNDARY_TYPES[role])})")
        return {**DEFAULT_BOUNDARY_TYPES, **value}


def migrate_preset(data: dict) -> dict:
    """Preset file data migrated to the current schema, as projects are (core/project_io.migrate): a
    file without ``schema_version`` (format 1) was written before schema v10 and is read as v9; below
    v10 its mesh keeps the v9 behaviour where it does not set the keys (V9_MESH_BEHAVIOUR: relative
    layers with target y+ 1, surface size from the largest extent, no curvature refinement)."""
    data = dict(data)
    version = data.get("schema_version", 9)
    if isinstance(version, int) and version > CURRENT_SCHEMA_VERSION:
        raise ValueError(f"schema version {version} is newer than this app ({CURRENT_SCHEMA_VERSION})")
    if isinstance(version, int) and version < 10:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V9_MESH_BEHAVIOUR.items():
            mesh.setdefault(key, value)
        data["mesh"] = mesh
        version = 10
    if isinstance(version, int) and version < 13:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V13_MESH_FIELDS.items():  # the layer controls the preset had (D-106)
            mesh.setdefault(key, value)
        data["mesh"] = mesh
    if isinstance(version, int) and version < 14:
        mesh = data.get("mesh")
        mesh = dict(mesh) if isinstance(mesh, dict) else {}
        for key, value in V14_MESH_FIELDS.items():  # the first-layer convention the preset had (D-107)
            mesh.setdefault(key, value)
        data["mesh"] = mesh
    if isinstance(version, int) and version < CURRENT_SCHEMA_VERSION:
        version = CURRENT_SCHEMA_VERSION  # v11 and v12 added nothing a preset holds (the surface preparation, D-093; refinement volumes, D-103)
    data["schema_version"] = version
    data["format_version"] = PRESET_FORMAT_VERSION
    return data


def validate_preset_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("a preset name must be text")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Enter a preset name.")
    if len(cleaned) > 64:
        raise ValueError("A preset name has at most 64 characters.")
    if any(ord(c) < 32 for c in cleaned):
        raise ValueError("A preset name cannot contain control characters.")
    return cleaned


BUILTIN_PRESETS: tuple[Preset, ...] = (
    Preset(name="External flow", analysis_type="external"),
    Preset(name="Empty", analysis_type="empty"),
)


def is_builtin_name(name: str) -> bool:
    return name.strip().casefold() in {p.name.casefold() for p in BUILTIN_PRESETS}


def apply_preset(sim: Simulation, preset: Preset) -> Simulation:
    """``sim`` set up from ``preset``: analysis type, provenance, domain and mesh. Physics, inflow,
    solvers, reports and geometry are kept. The domain is generated automatically (enabled) only
    for the external analysis; the "empty" analysis waits for "Generate domain"."""
    data = sim.model_dump()
    data["analysis_type"] = preset.analysis_type
    data["preset_name"] = preset.name
    data["domain"] = {**data["domain"], **preset.domain.model_dump(),
                      "enabled": preset.analysis_type == "external", "parts": None}
    data["mesh"] = preset.mesh.model_dump()
    return Simulation.model_validate(data)


def preset_from_simulation(sim: Simulation, name: str) -> Preset:
    """A user preset from an open project: its analysis type, domain set-up and mesh settings."""
    domain = {key: getattr(sim.domain, key) for key in DOMAIN_FIELDS}
    return Preset(name=name, analysis_type=sim.analysis_type, domain=PresetDomain(**domain),
                  mesh=sim.mesh.model_copy(deep=True, update={"cores": None}))


@dataclass(frozen=True)
class BrokenPreset:
    """A preset file that could not be read or validated."""

    path: Path
    error: str


@dataclass(frozen=True)
class StoredPreset:
    path: Path
    preset: Preset


def _file_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower()
    return stem or "preset"


class PresetStore:
    """User presets as JSON files in ``folder`` (created on the first save)."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def scan(self) -> tuple[list[StoredPreset], list[BrokenPreset]]:
        """(valid presets sorted by name, broken files). Never raises for a bad file."""
        good: list[StoredPreset] = []
        broken: list[BrokenPreset] = []
        if not self.folder.is_dir():
            return good, broken
        seen: set[str] = set()
        for path in sorted(self.folder.glob(f"*{PRESET_SUFFIX}")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("not a JSON object")
                version = data.get("format_version")
                if isinstance(version, int) and version > PRESET_FORMAT_VERSION:
                    raise ValueError(f"format version {version} is newer than this app ({PRESET_FORMAT_VERSION})")
                preset = Preset.model_validate(migrate_preset(data))
                key = preset.name.casefold()
                if is_builtin_name(preset.name):
                    raise ValueError(f"the name {preset.name!r} belongs to a built-in preset")
                if key in seen:
                    raise ValueError(f"another file already holds the preset {preset.name!r}")
            except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
                broken.append(BrokenPreset(path, _short_error(exc)))
                continue
            seen.add(key)
            good.append(StoredPreset(path, preset))
        good.sort(key=lambda s: s.preset.name.casefold())
        return good, broken

    def presets(self) -> list[Preset]:
        return [s.preset for s in self.scan()[0]]

    def find(self, name: str) -> StoredPreset | None:
        key = name.strip().casefold()
        return next((s for s in self.scan()[0] if s.preset.name.casefold() == key), None)

    def save(self, preset: Preset, overwrite: bool = False) -> Path:
        """Write ``preset``; PresetError for a built-in name, or an existing one unless ``overwrite``."""
        if is_builtin_name(preset.name):
            raise PresetError(f"'{preset.name}' is a built-in preset: choose another name.")
        existing = self.find(preset.name)
        if existing is not None and not overwrite:
            raise PresetError(f"A preset named '{preset.name}' already exists.")
        path = existing.path if existing is not None else self._free_path(preset.name)
        self._write(path, preset)
        return path

    def rename(self, old: str, new: str) -> Path:
        stored = self.find(old)
        if stored is None:
            raise PresetError(f"No user preset named '{old}'.")
        new = validate_preset_name(new)
        if is_builtin_name(new):
            raise PresetError(f"'{new}' is a built-in preset: choose another name.")
        other = self.find(new)
        if other is not None and other.path != stored.path:
            raise PresetError(f"A preset named '{new}' already exists.")
        renamed = stored.preset.model_copy(update={"name": new})
        path = self._free_path(new, keep=stored.path)
        self._write(path, renamed)
        if path != stored.path:
            stored.path.unlink(missing_ok=True)
        return path

    def delete(self, name: str) -> None:
        stored = self.find(name)
        if stored is None:
            raise PresetError(f"No user preset named '{name}'.")
        stored.path.unlink(missing_ok=True)

    def delete_file(self, path: Path) -> None:
        """Delete a (broken) preset file of this folder."""
        path = Path(path)
        if path.parent.resolve() == self.folder.resolve() and path.suffix == PRESET_SUFFIX:
            path.unlink(missing_ok=True)

    def _free_path(self, name: str, keep: Path | None = None) -> Path:
        stem, n = _file_stem(name), 1
        path = self.folder / f"{stem}{PRESET_SUFFIX}"
        while path.exists() and path != keep:
            n += 1
            path = self.folder / f"{stem}_{n}{PRESET_SUFFIX}"
        return path

    def _write(self, path: Path, preset: Preset) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        text = preset.model_dump_json(indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else type(exc).__name__
