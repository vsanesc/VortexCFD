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
    V9_MESH_BEHAVIOUR,
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


# The v5 residual targets as v6 stopping criteria (their old defaults).
DEFAULT_STOPPING = {"criteria": [{"kind": "residual", "field": "p", "threshold": 1e-4},
                                 {"kind": "residual", "field": "U", "threshold": 1e-5},
                                 {"kind": "residual", "field": "k", "threshold": 1e-5},
                                 {"kind": "residual", "field": "omega", "threshold": 1e-5}],
                    "combine": "all"}


def test_migrate_v1_to_v2_and_current_unchanged() -> None:
    """v1 gains the default domain and version 2; current data is returned unchanged. Every older file
    keeps the v9 mesh behaviour that the v10 defaults changed (D-085)."""
    legacy = dict(V9_MESH_BEHAVIOUR)
    assert migrate({"schema_version": 1, "custom": "data"}) == {
        "schema_version": 14, "custom": "data", "domain": {}, "mesh": legacy, "analysis_type": "external",
        "physics": {}, "inflow": {}, "solvers": {"stopping": DEFAULT_STOPPING}, "reports": {},
    }
    assert migrate({"schema_version": 2, "x": 1}) == {
        "schema_version": 14, "x": 1, "physics": {}, "inflow": {}, "solvers": {"stopping": DEFAULT_STOPPING},
        "reports": {}, "analysis_type": "external", "mesh": legacy,
    }
    assert migrate({"schema_version": 3, "reports": {}}) == {"schema_version": 14, "reports": {},
                                                             "analysis_type": "external", "mesh": legacy}
    current = {"schema_version": 14, "custom": "data"}
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
    assert CURRENT_SCHEMA_VERSION == 14


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
    assert sim.mesh == Mesh(**V9_MESH_BEHAVIOUR)  # the defaults it had (D-085)
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
    assert (m.layer_sizing, m.target_yplus) == ("absolute_yplus", 50.0)  # wall-function range (D-086)


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


def test_default_stopping_criteria_are_the_old_residual_targets() -> None:
    sv = Solvers()
    stop = sv.stopping
    assert stop.combine == "all" and stop.min_iterations == 0
    assert [(c.kind, c.field, c.threshold) for c in stop.criteria] == [
        ("residual", "p", 1e-4), ("residual", "U", 1e-5), ("residual", "k", 1e-5), ("residual", "omega", 1e-5)]
    assert (stop.oscillation_threshold, stop.oscillation_window) == (0.01, 100)
    assert load_simulation(V2_FIXTURE).solvers == Solvers()  # a v2 file gets the defaults


# -- reference values and report slots (schema v4) --------------------------------------------------

from vortexcfd.core.model import REPORT_SLOTS, Reports, ResidualCriterion

V3_FIXTURE = Path(__file__).parent / "data" / "project_v3.json"


def test_v3_fixture_migrates_to_v4_with_unset_reports_and_keeps_its_data() -> None:
    """Hand-written v3 project (tests/data/project_v3.json): reports gains the unset overrides
    and empty slots; every v3 value is kept."""
    raw = json.loads(V3_FIXTURE.read_text())
    assert raw["schema_version"] == 3 and raw["reports"] == {}
    sim = load_simulation(V3_FIXTURE)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
    assert sim.reports == Reports()
    assert sim.reports.reference_area is None and sim.reports.reference_length is None
    assert sim.reports.reference_area_basis == "planform"
    assert sim.reports.center_of_rotation is None and sim.reports.slots == [None] * REPORT_SLOTS
    assert (sim.physics.nu, sim.physics.rho_ref) == (1.6e-05, 1.2)
    assert (sim.inflow.speed, sim.inflow.alpha_deg) == (35.0, 4.0)
    assert sim.solvers.iterations == 800
    assert sim.solvers.stopping.criteria[0] == ResidualCriterion(field="p", threshold=1e-05)
    assert sim.mesh.layer_sizing == "absolute_yplus" and sim.mesh.target_yplus == 30.0
    assert sim.domain.symmetry == "y_min" and [p.units for p in sim.geometry.parts] == ["mm"]


def test_reports_validation() -> None:
    r = Reports(reference_area_basis="custom", reference_area=0.5, reference_length=0.2,
                center_of_rotation=(0.25, 0, 0), slots=["Cd", None, "yplus_avg"])
    assert r.center_of_rotation == (0.25, 0.0, 0.0)
    assert Reports().reference_area_basis == "planform" and Reports(reference_area_basis="frontal").reference_area is None
    # an unpublished v4 file with only reference_area reads as custom
    assert Reports.model_validate({"reference_area": 0.7}).reference_area_basis == "custom"
    for bad in ({"reference_area_basis": "custom", "reference_area": 0}, {"reference_length": -1},
                {"slots": ["Cd"]}, {"slots": ["Cd", "bogus", None]}, {"center_of_rotation": (1, 2)},
                {"reference_area_basis": "custom"}, {"reference_area_basis": "frontal", "reference_area": 1.0},
                {"reference_area_basis": "wetted"}):
        with pytest.raises(ValidationError):
            Reports(**bad)


def test_update_reports_is_undoable_and_saved(tmp_path: Path) -> None:
    p = Project.new("r")
    p.update_reports(reference_area_basis="custom", reference_area=0.75, slots=["Cl", None, None])
    assert p.undo_label == "Edit reports (reference_area_basis, reference_area, slots)"
    path = tmp_path / "r.json"
    p.save(path)
    loaded = Project.open(path)
    assert loaded.sim.reports.reference_area == 0.75 and loaded.sim.reports.slots == ["Cl", None, None]
    p.undo()
    assert p.sim.reports == Reports()
    with pytest.raises(ValidationError):
        p.update_reports(reference_length=0.0)
    with pytest.raises(ValidationError):
        p.update_reports(reference_area=1.0)  # a custom area needs the custom basis


# -- per-part surface levels (schema v5) ------------------------------------------------------------------

V4_FIXTURE = Path(__file__).parent / "data" / "project_v4.json"


def test_v4_fixture_migrates_to_v5_with_unset_part_levels_and_keeps_its_data() -> None:
    raw = json.loads(V4_FIXTURE.read_text())
    assert raw["schema_version"] == 4 and "surface_level_min" not in raw["geometry"]["parts"][0]
    sim = load_simulation(V4_FIXTURE)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
    assert [(p.name, p.units, p.surface_level_min, p.surface_level_max) for p in sim.geometry.parts] == [
        ("Ball", "m", None, None), ("Pod", "mm", None, None)]
    assert sim.mesh.surface_level_max == 5 and sim.solvers.iterations == 500
    assert sim.reports.reference_area_basis == "frontal" and sim.reports.slots == ["Cd", None, "yplus_avg"]
    assert migrate({"schema_version": 4, "x": 1}) == {"schema_version": 14, "x": 1, "analysis_type": "external",
                                                     "mesh": dict(V9_MESH_BEHAVIOUR)}  # no solvers: nothing to convert


def test_part_levels_validation_and_update() -> None:
    from vortexcfd.core.model import Part

    assert Part(name="a", source_file="a.stl", surface_level_min=5, surface_level_max=6).surface_level_max == 6
    for bad in ({"surface_level_min": -1}, {"surface_level_min": 6, "surface_level_max": 5}):
        with pytest.raises(ValidationError):
            Part(name="a", source_file="a.stl", **bad)
    p = Project.new("lv")
    p.add_part(Part(name="Pod", source_file="pod.stl"))
    p.update_part(0, surface_level_max=7)
    assert p.sim.geometry.parts[0].surface_level_max == 7 and p.sim.geometry.parts[0].surface_level_min is None
    p.undo()
    assert p.sim.geometry.parts[0].surface_level_max is None


def test_v6_fixture_migrates_to_v7_with_default_studies() -> None:
    """Hand-written v6 project (tests/data/project_v6.json): v7 adds ``studies`` with the defaults
    (D-066); everything else is kept."""
    import json
    import math
    from pathlib import Path

    from vortexcfd.core.project_io import load_simulation

    path = Path(__file__).parent / "data" / "project_v6.json"
    assert json.loads(path.read_text())["schema_version"] == 6
    sim = load_simulation(path)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION
    assert sim.studies.mesh.ratio == pytest.approx(math.sqrt(2)) and sim.studies.mesh.current_as == "fine"
    assert sim.studies.mesh.quantities == ["Cd"] and sim.studies.mesh.cores == 1
    assert sim.mesh.background_cells_target == 50000 and sim.solvers.cores == 2
    assert sim.solvers.stopping.criteria[0].window == 30 and sim.reports.slots == ["Cd", "Cl", None]


def test_mesh_study_settings_validation() -> None:
    from vortexcfd.core.model import MeshStudySettings

    with pytest.raises(ValueError):
        MeshStudySettings(ratio=1.2)
    with pytest.raises(ValueError):
        MeshStudySettings(quantities=["nope"])
    with pytest.raises(ValueError):
        MeshStudySettings(quantities=["Cd", "Cd"])
    assert MeshStudySettings(quantities=["Cd@Ball", "probe:wake:p"]).quantities == ["Cd@Ball", "probe:wake:p"]


V9_FIXTURE = Path(__file__).parent / "data" / "project_v9.json"


def load_simulation_data(data: dict) -> Simulation:
    return Simulation.model_validate(migrate(data))


def test_v9_fixture_keeps_its_mesh_behaviour() -> None:
    """Hand-written v9 project as the app saved it (tests/data/project_v9.json): its stored mesh values
    are kept and the settings the v10 defaults changed take the values it had (D-085)."""
    stored = json.loads(V9_FIXTURE.read_text())
    assert stored["schema_version"] == 9 and "curvature_levels" not in stored["mesh"]
    sim = load_simulation(V9_FIXTURE)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 14
    for key, value in stored["mesh"].items():
        assert getattr(sim.mesh, key) == value, key
    assert sim.mesh.surface_size_reference == "largest_extent" and sim.mesh.curvature_levels == 0
    assert sim.reports.reference_length is None and sim.inflow.speed == 20.0
    assert (sim.mesh.layer_sizing, sim.mesh.target_yplus) == ("relative", 1.0)  # its stored layers (D-086)
    # a minimal v9 file without layer settings keeps the v9 defaults, not the v10 ones
    minimal = load_simulation_data({"schema_version": 9, "name": "m", "mesh": {"layers": 2}})
    assert (minimal.mesh.layer_sizing, minimal.mesh.target_yplus, minimal.mesh.layers) == ("relative", 1.0, 2)


def test_new_simulation_sizes_the_surface_from_l_ref_with_curvature() -> None:
    mesh = Simulation(name="x").mesh
    assert (mesh.layer_sizing, mesh.target_yplus) == ("absolute_yplus", 50.0)  # D-086
    assert mesh.surface_size_reference == "l_ref" and mesh.target_surface_size == 0.01
    assert mesh.curvature_levels == 2
    with pytest.raises(ValidationError):
        Mesh(curvature_levels=3)  # at most 2 levels above the part's surface level (D-085)


def test_v10_file_keeps_explicit_values(tmp_path: Path) -> None:
    """A v10 project that chose the older behaviour keeps it on load (no migration at the current version)."""
    sim = Simulation(name="x", mesh=Mesh(surface_size_reference="largest_extent", curvature_levels=0))
    path = tmp_path / "p.vcfd"
    save_simulation(sim, path)
    again = load_simulation(path)
    assert again.mesh == sim.mesh
