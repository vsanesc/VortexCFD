"""Tests for core simulation data model and project I/O."""

import json
from pathlib import Path
from pydantic import ValidationError
import pytest

from vortexcfd.core.model import (
    CURRENT_SCHEMA_VERSION,
    Geometry,
    Mesh,
    Part,
    Physics,
    Reports,
    Simulation,
    Solvers,
)
from vortexcfd.core.project_io import (
    ProjectFileError,
    load_simulation,
    migrate,
    save_simulation,
)


def test_simulation_round_trip_with_two_parts(tmp_path: Path) -> None:
    """Verify save and load round-trip equality for a simulation with two parts."""
    sim = Simulation(
        name="AirfoilSim",
        geometry=Geometry(
            parts=[
                Part(name="main_wing", source_file="cad/wing.stl", units="m"),
                Part(name="flap", source_file="cad/flap.stl", units="mm"),
            ]
        ),
    )

    save_path = tmp_path / "projects" / "airfoil.json"
    save_simulation(sim, save_path)

    assert save_path.is_file()
    loaded = load_simulation(save_path)

    assert loaded == sim
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION
    assert loaded.name == "AirfoilSim"
    assert len(loaded.geometry.parts) == 2
    assert loaded.geometry.parts[0].name == "main_wing"
    assert loaded.geometry.parts[0].source_file == "cad/wing.stl"
    assert loaded.geometry.parts[0].units == "m"
    assert loaded.geometry.parts[1].name == "flap"
    assert loaded.geometry.parts[1].source_file == "cad/flap.stl"
    assert loaded.geometry.parts[1].units == "mm"
    assert isinstance(loaded.mesh, Mesh)
    assert isinstance(loaded.physics, Physics)
    assert isinstance(loaded.solvers, Solvers)
    assert isinstance(loaded.reports, Reports)


def test_simulation_round_trip_default(tmp_path: Path) -> None:
    """Verify minimal simulation round trip preserves defaults."""
    sim = Simulation(name="Minimal")
    save_path = tmp_path / "minimal.json"
    save_simulation(sim, save_path)

    loaded = load_simulation(save_path)
    assert loaded == sim
    assert loaded.geometry.parts == []


def test_unknown_field_rejected(tmp_path: Path) -> None:
    """Verify that unknown fields at root and nested models are rejected."""
    # Top-level unknown field
    data_top = {
        "schema_version": 1,
        "name": "SimWithExtra",
        "unexpected_field": "disallowed",
    }
    path_top = tmp_path / "unknown_top.json"
    path_top.write_text(json.dumps(data_top), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path_top)

    # Nested unknown field in Part
    data_nested = {
        "schema_version": 1,
        "name": "SimNestedExtra",
        "geometry": {
            "parts": [
                {
                    "name": "p1",
                    "source_file": "p1.stl",
                    "unknown_part_field": 123,
                }
            ]
        },
    }
    path_nested = tmp_path / "unknown_nested.json"
    path_nested.write_text(json.dumps(data_nested), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path_nested)

    # Direct Pydantic validation
    with pytest.raises(ValidationError):
        Part(name="p", source_file="s.stl", invalid_field=1)


def test_schema_version_999_rejected(tmp_path: Path) -> None:
    """Verify that a project file with future schema_version is rejected."""
    data = {
        "schema_version": 999,
        "name": "FutureSim",
    }
    path = tmp_path / "future_version.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProjectFileError, match="Unsupported schema_version 999"):
        load_simulation(path)


def test_invalid_json_rejected(tmp_path: Path) -> None:
    """Verify that malformed JSON is rejected with ProjectFileError."""
    path = tmp_path / "malformed.json"
    path.write_text("{ this is definitely not valid json :", encoding="utf-8")

    with pytest.raises(ProjectFileError, match="Invalid JSON"):
        load_simulation(path)

    # Non-dictionary JSON root
    path_array = tmp_path / "array.json"
    path_array.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Expected a JSON object"):
        load_simulation(path_array)


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    """Verify that missing required fields fail validation."""
    # Missing 'name' in root simulation
    data_no_name = {
        "schema_version": 1,
    }
    path_no_name = tmp_path / "no_name.json"
    path_no_name.write_text(json.dumps(data_no_name), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path_no_name)

    # Missing 'source_file' in Part
    data_no_source = {
        "schema_version": 1,
        "name": "MissingSourceSim",
        "geometry": {
            "parts": [
                {"name": "part_without_source"}
            ]
        },
    }
    path_no_source = tmp_path / "no_source.json"
    path_no_source.write_text(json.dumps(data_no_source), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path_no_source)

    # Direct model validation
    with pytest.raises(ValidationError):
        Simulation.model_validate({"schema_version": 1})

    with pytest.raises(ValidationError):
        Part.model_validate({"name": "part_without_source"})


def test_missing_schema_version_rejected(tmp_path: Path) -> None:
    """Verify that a project file without schema_version key is rejected."""
    data = {"name": "NoSchemaSim"}
    path = tmp_path / "no_schema.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Missing required 'schema_version' key"):
        load_simulation(path)


def test_string_schema_version_999_rejected(tmp_path: Path) -> None:
    """Verify that a string schema_version '999' is rejected."""
    data = {"schema_version": "999", "name": "StringSchemaSim"}
    path = tmp_path / "string_schema.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path)


def test_units_validation(tmp_path: Path) -> None:
    """Verify units Literal restricts values to accepted set."""
    part_valid = Part(name="p_valid", source_file="p.stl", units="mm")
    assert part_valid.units == "mm"

    with pytest.raises(ValidationError):
        Part(name="p_invalid", source_file="p.stl", units="banana")  # type: ignore[arg-type]

    data_bad_units = {
        "schema_version": 1,
        "name": "BadUnitsSim",
        "geometry": {
            "parts": [
                {"name": "p", "source_file": "p.stl", "units": "banana"}
            ]
        },
    }
    path = tmp_path / "bad_units.json"
    path.write_text(json.dumps(data_bad_units), encoding="utf-8")
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path)


def test_save_simulation_atomic_cleanup(tmp_path: Path) -> None:
    """Verify save_simulation writes atomically and leaves no temporary files."""
    sim = Simulation(name="AtomicTest")
    target_dir = tmp_path / "atomic_target"
    project_path = target_dir / "project.json"

    save_simulation(sim, project_path)

    assert project_path.is_file()
    directory_files = list(target_dir.iterdir())
    assert directory_files == [project_path]


def test_migrate_v1_to_v2_and_current_unchanged() -> None:
    """v1 gains the default domain and version 2; current data is returned unchanged."""
    assert migrate({"schema_version": 1, "custom": "data"}) == {
        "schema_version": 2, "custom": "data", "domain": {},
    }
    current = {"schema_version": 2, "custom": "data"}
    assert migrate(current) == current


# -- domain and schema v2 ---------------------------------------------------------------

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Domain, Simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import ProjectFileError, load_simulation, save_simulation

V1_FIXTURE = Path(__file__).parent / "data" / "project_v1.json"


def test_domain_defaults() -> None:
    d = Domain()
    assert (d.enabled, d.upstream, d.downstream, d.lateral, d.vertical, d.symmetry) == (
        True, 5.0, 10.0, 5.0, 5.0, "none",
    )
    assert Simulation(name="x").domain == d
    assert CURRENT_SCHEMA_VERSION == 2


@pytest.mark.parametrize("field", ["upstream", "downstream", "lateral", "vertical"])
@pytest.mark.parametrize("value", [0, -1.0])
def test_domain_multipliers_must_be_positive(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Domain(**{field: value})


def test_domain_rejects_unknown_symmetry_and_fields() -> None:
    with pytest.raises(ValidationError):
        Domain(symmetry="z_min")
    with pytest.raises(ValidationError):
        Domain(bogus=1)


def test_v1_fixture_opens_as_v2_with_default_domain() -> None:
    sim = load_simulation(V1_FIXTURE)
    assert sim.schema_version == 2
    assert sim.domain == Domain()
    assert [p.name for p in sim.geometry.parts] == ["Wing"]


def test_v2_round_trip(tmp_path: Path) -> None:
    sim = Simulation(name="rt", domain=Domain(upstream=3, symmetry="y_min", enabled=False))
    path = tmp_path / "p.json"
    save_simulation(sim, path)
    assert json.loads(path.read_text())["schema_version"] == 2
    assert load_simulation(path) == sim


def test_future_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema_version": 3, "name": "x"}))
    with pytest.raises(ProjectFileError, match="Unsupported schema_version"):
        load_simulation(path)


def test_invalid_domain_in_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema_version": 2, "name": "x", "domain": {"upstream": -2}}))
    with pytest.raises(ProjectFileError, match="Validation failed"):
        load_simulation(path)


def test_update_domain_is_one_undoable_step() -> None:
    p = Project.new("d")
    p.update_domain(upstream=7.0, symmetry="y_min")
    assert p.sim.domain.upstream == 7.0 and p.sim.domain.symmetry == "y_min"
    assert len(p._undo) == 1 and p.undo_label == "Edit domain (upstream, symmetry)"
    p.undo()
    assert p.sim.domain == Domain()
    p.redo()
    assert p.sim.domain.upstream == 7.0


def test_update_domain_validates_and_noop_leaves_no_trace() -> None:
    p = Project.new("d")
    with pytest.raises(ValidationError):
        p.update_domain(upstream=0)
    with pytest.raises(ValidationError):
        p.update_domain(nonsense=1)
    p.update_domain(upstream=5.0)  # same value: no-op
    assert not p.can_undo and p.sim.domain == Domain()
    seen = []
    p.subscribe(lambda proj: seen.append(1))
    p.update_domain(enabled=False)
    assert seen == [1] and p.sim.domain.enabled is False
