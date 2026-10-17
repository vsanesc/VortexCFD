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
        "schema_version": 4, "custom": "data", "domain": {}, "mesh": {},
        "physics": {}, "inflow": {}, "solvers": {}, "reports": {},
    }
    assert migrate({"schema_version": 2, "x": 1}) == {
        "schema_version": 4, "x": 1, "physics": {}, "inflow": {}, "solvers": {}, "reports": {},
    }
    assert migrate({"schema_version": 3, "reports": {}}) == {"schema_version": 4, "reports": {}}
    current = {"schema_version": 4, "custom": "data"}
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
V2_FIXTURE = Path(__file__).parent / "data" / "project_v2.json"


def test_domain_defaults() -> None:
    d = Domain()
    assert (d.enabled, d.upstream, d.downstream, d.lateral, d.vertical, d.symmetry) == (
        True, 5.0, 10.0, 5.0, 5.0, "none",
    )
    assert Simulation(name="x").domain == d
    assert CURRENT_SCHEMA_VERSION == 4


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


def test_v1_fixture_opens_as_current_with_default_domain() -> None:
    sim = load_simulation(V1_FIXTURE)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
    assert sim.domain == Domain()
    assert [p.name for p in sim.geometry.parts] == ["Wing"]


def test_current_version_round_trip(tmp_path: Path) -> None:
    sim = Simulation(name="rt", domain=Domain(upstream=3, symmetry="y_min", enabled=False))
    path = tmp_path / "p.json"
    save_simulation(sim, path)
    assert json.loads(path.read_text())["schema_version"] == CURRENT_SCHEMA_VERSION
    assert load_simulation(path) == sim


def test_future_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema_version": CURRENT_SCHEMA_VERSION + 1, "name": "x"}))
    with pytest.raises(ProjectFileError, match="Unsupported schema_version"):
        load_simulation(path)


def test_invalid_domain_in_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema_version": 3, "name": "x", "domain": {"upstream": -2}}))
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


# -- mesh controls (schema v2) ------------------------------------------------------------

from vortexcfd.core.model import Mesh


def test_mesh_defaults() -> None:
    m = Mesh()
    assert (m.base_size, m.surface_level_min, m.surface_level_max) == (None, None, None)
    assert (m.background_cells_target, m.target_surface_size) == (100_000, 0.01)
    assert (m.feature_angle, m.layers, m.expansion_ratio) == (30.0, 3, 1.2)
    assert (m.final_layer_thickness, m.min_thickness) == (0.5, 0.1)
    assert Simulation(name="x").mesh == m


@pytest.mark.parametrize("fields", [
    {"base_size": 0}, {"base_size": -1.0}, {"surface_level_min": -1}, {"background_cells_target": 0},
    {"target_surface_size": 0}, {"feature_angle": 0},
    {"feature_angle": 181}, {"layers": -1}, {"expansion_ratio": 0.9}, {"final_layer_thickness": 0},
    {"min_thickness": -0.1}, {"surface_level_min": 4, "surface_level_max": 2}, {"bogus": 1},
])
def test_mesh_rejects_invalid_values(fields: dict) -> None:
    with pytest.raises(ValidationError):
        Mesh(**fields)


def test_v1_fixture_gets_default_mesh_and_round_trips(tmp_path: Path) -> None:
    sim = load_simulation(V1_FIXTURE)
    assert sim.mesh == Mesh()
    sim = sim.model_copy(update={"mesh": Mesh(base_size=0.25, layers=0)})
    path = tmp_path / "m.json"
    save_simulation(sim, path)
    assert load_simulation(path).mesh == Mesh(base_size=0.25, layers=0)


def test_update_mesh_is_one_undoable_step_and_validates() -> None:
    p = Project.new("m")
    p.update_mesh(layers=5, base_size=0.1)
    assert p.sim.mesh.layers == 5 and p.sim.mesh.base_size == 0.1
    assert len(p._undo) == 1 and p.undo_label == "Edit mesh (layers, base_size)"
    p.undo()
    assert p.sim.mesh == Mesh()
    with pytest.raises(ValidationError):
        p.update_mesh(layers=-1)
    p.update_mesh(surface_level_max=2)
    with pytest.raises(ValidationError):
        p.update_mesh(surface_level_min=9)  # above the explicit max of 2
    p.undo()
    p.update_mesh(layers=3)  # unchanged: no trace
    assert not p.can_undo


# -- physics, inflow, solvers (schema v3) ----------------------------------------------------------

from vortexcfd.core.model import Inflow, Physics, Solvers


def test_v2_fixture_opens_with_default_physics_and_keeps_its_data() -> None:
    sim = load_simulation(V2_FIXTURE)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
    assert sim.physics == Physics() and sim.inflow == Inflow() and sim.solvers == Solvers()
    assert sim.domain.symmetry == "y_min" and sim.domain.upstream == 4
    assert sim.mesh.layers == 2 and sim.mesh.base_size == 0.1
    assert [p.name for p in sim.geometry.parts] == ["Wing"]


def test_physics_inflow_solver_defaults() -> None:
    assert (Physics().flow, Physics().nu, Physics().rho_ref, Physics().turbulence_model) == (
        "incompressible_steady", 1.5e-5, 1.225, "kOmegaSST")
    i = Inflow()
    assert (i.speed, i.alpha_deg, i.turbulence_intensity, i.viscosity_ratio) == (20.0, 0.0, 0.01, 10.0)
    sv = Solvers()
    assert (sv.iterations, sv.write_interval, sv.relaxation) == (1000, 200, "robust")
    m = Mesh()
    assert (m.layer_sizing, m.target_yplus) == ("relative", 1.0)


@pytest.mark.parametrize("model, fields", [
    (Physics, {"nu": 0}), (Physics, {"rho_ref": -1}), (Physics, {"flow": "transient"}),
    (Physics, {"turbulence_model": "kEpsilon"}), (Inflow, {"speed": 0}), (Inflow, {"alpha_deg": 91}),
    (Inflow, {"turbulence_intensity": 0}), (Inflow, {"turbulence_intensity": 1.5}),
    (Inflow, {"viscosity_ratio": 0}), (Solvers, {"iterations": 0}), (Solvers, {"write_interval": 0}),
    (Solvers, {"relaxation": "fast"}), (Mesh, {"layer_sizing": "yplus"}), (Mesh, {"target_yplus": 0}),
    (Inflow, {"bogus": 1}),
])
def test_physics_models_reject_invalid_values(model, fields: dict) -> None:
    with pytest.raises(ValidationError):
        model(**fields)


@pytest.mark.parametrize("method, fields, label", [
    ("update_physics", {"nu": 2e-5}, "Edit physics (nu)"),
    ("update_inflow", {"speed": 30.0, "alpha_deg": 4.0}, "Edit inflow (speed, alpha_deg)"),
    ("update_solver", {"iterations": 500}, "Edit solver (iterations)"),
])
def test_update_apis_are_one_undoable_step_and_validate(method, fields, label) -> None:
    p = Project.new("e")
    before = p.sim
    getattr(p, method)(**fields)
    assert len(p._undo) == 1 and p.undo_label == label
    p.undo()
    assert p.sim == before
    p.redo()
    assert p.sim != before
    bad = {k: -1 for k in fields}
    with pytest.raises(ValidationError):
        getattr(p, method)(**bad)
    p2 = Project.new("n")
    getattr(p2, method)(**{k: getattr(getattr(p2.sim, {"update_physics": "physics", "update_inflow": "inflow", "update_solver": "solvers"}[method]), k) for k in fields})
    assert not p2.can_undo  # same values: no trace


def test_v3_round_trip_with_physics(tmp_path: Path) -> None:
    sim = Simulation(name="rt", physics=Physics(nu=2e-5), inflow=Inflow(speed=35, alpha_deg=-3),
                     solvers=Solvers(iterations=77), mesh=Mesh(layer_sizing="absolute_yplus", target_yplus=30))
    path = tmp_path / "p.json"
    save_simulation(sim, path)
    assert load_simulation(path) == sim


def test_solver_residual_targets_defaults_and_validation() -> None:
    sv = Solvers()
    assert (sv.residual_p, sv.residual_u, sv.residual_k, sv.residual_omega) == (1e-4, 1e-5, 1e-5, 1e-5)
    for key in ("residual_p", "residual_u", "residual_k", "residual_omega"):
        with pytest.raises(ValidationError):
            Solvers(**{key: 0})
    p = Project.new("r")
    p.update_solver(residual_p=1e-6)
    assert p.sim.solvers.residual_p == 1e-6 and p.undo_label == "Edit solver (residual_p)"
    assert load_simulation(V2_FIXTURE).solvers == Solvers()  # a v2 file gets the defaults


# -- reference values and report slots (schema v4) --------------------------------------------------

from vortexcfd.core.model import REPORT_SLOTS, Reports

V3_FIXTURE = Path(__file__).parent / "data" / "project_v3.json"


def test_v3_fixture_migrates_to_v4_with_unset_reports_and_keeps_its_data() -> None:
    """Hand-written v3 project (tests/data/project_v3.json): reports gains the unset overrides
    and empty slots; every v3 value is kept."""
    raw = json.loads(V3_FIXTURE.read_text())
    assert raw["schema_version"] == 3 and raw["reports"] == {}
    sim = load_simulation(V3_FIXTURE)
    assert sim.schema_version == 4
    assert sim.reports == Reports()
    assert sim.reports.reference_area is None and sim.reports.reference_length is None
    assert sim.reports.center_of_rotation is None and sim.reports.slots == [None] * REPORT_SLOTS
    assert (sim.physics.nu, sim.physics.rho_ref) == (1.6e-05, 1.2)
    assert (sim.inflow.speed, sim.inflow.alpha_deg) == (35.0, 4.0)
    assert (sim.solvers.iterations, sim.solvers.residual_p) == (800, 1e-05)
    assert sim.mesh.layer_sizing == "absolute_yplus" and sim.mesh.target_yplus == 30.0
    assert sim.domain.symmetry == "y_min" and [p.units for p in sim.geometry.parts] == ["mm"]


def test_reports_validation() -> None:
    r = Reports(reference_area=0.5, reference_length=0.2, center_of_rotation=(0.25, 0, 0),
                slots=["Cd", None, "yplus_avg"])
    assert r.center_of_rotation == (0.25, 0.0, 0.0)
    for bad in ({"reference_area": 0}, {"reference_length": -1}, {"slots": ["Cd"]},
                {"slots": ["Cd", "bogus", None]}, {"center_of_rotation": (1, 2)}):
        with pytest.raises(ValidationError):
            Reports(**bad)


def test_update_reports_is_undoable_and_saved(tmp_path: Path) -> None:
    p = Project.new("r")
    p.update_reports(reference_area=0.75, slots=["Cl", None, None])
    assert p.undo_label == "Edit reports (reference_area, slots)"
    path = tmp_path / "r.json"
    p.save(path)
    loaded = Project.open(path)
    assert loaded.sim.reports.reference_area == 0.75 and loaded.sim.reports.slots == ["Cl", None, None]
    p.undo()
    assert p.sim.reports == Reports()
    with pytest.raises(ValidationError):
        p.update_reports(reference_length=0.0)
