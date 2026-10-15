"""Tests for core simulation data model and project I/O."""

import json
from pathlib import Path
from pydantic import ValidationError
import pytest

from cfdgui.core.model import (
    CURRENT_SCHEMA_VERSION,
    Geometry,
    Mesh,
    Part,
    Physics,
    Reports,
    Simulation,
    Solvers,
)
from cfdgui.core.project_io import (
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


def test_migrate_placeholder() -> None:
    """Verify migrate placeholder returns input unchanged."""
    test_dict = {"schema_version": 1, "custom": "data"}
    assert migrate(test_dict) == test_dict
