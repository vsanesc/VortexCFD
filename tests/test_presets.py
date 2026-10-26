"""Analysis presets (D-077): built-ins, user presets on disk, validation, and the v8 -> v9 migration."""

import json
from pathlib import Path

import pytest

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Domain, Mesh, Simulation
from vortexcfd.core.presets import (
    BUILTIN_PRESETS,
    DEFAULT_BOUNDARY_TYPES,
    PRESET_FORMAT_VERSION,
    Preset,
    PresetDomain,
    PresetError,
    PresetStore,
    apply_preset,
    migrate_preset,
    preset_from_simulation,
)
from vortexcfd.core.project_io import load_simulation

# Every field a preset may carry; anything about physics, turbulence, inflow or solvers is forbidden.
PRESET_KEYS = {"format_version", "schema_version", "name", "analysis_type", "dimension", "domain", "boundary_types", "mesh"}
FORBIDDEN = ("physics", "inflow", "solvers", "turbulence", "nu", "speed", "alpha", "iterations", "cores",
             "stopping", "relaxation", "reports")


def _custom_sim() -> Simulation:
    sim = Simulation(name="wing")
    data = sim.model_dump()
    data["domain"].update(shape="bullet", radius=7.0, downstream=12.0, symmetry="y_min", parts=["Wing"])
    data["mesh"].update(background_cells_target=250_000, layers=5)
    data["physics"].update(nu=1e-6, rho_ref=998.0)
    data["inflow"].update(speed=3.0, alpha_deg=4.0)
    data["solvers"].update(iterations=77, cores=3)
    return Simulation.model_validate(data)


def test_builtins_are_external_flow_and_empty() -> None:
    assert [p.name for p in BUILTIN_PRESETS] == ["External flow", "Empty", "2D airfoil", "Internal flow",
                                                 "2D internal flow"]
    assert [p.analysis_type for p in BUILTIN_PRESETS] == ["external", "empty", "external", "internal", "internal"]
    for preset in BUILTIN_PRESETS[:2]:
        assert preset.domain == PresetDomain() and preset.mesh == Mesh() and preset.dimension == "3d"
        assert preset.boundary_types == DEFAULT_BOUNDARY_TYPES
    airfoil = BUILTIN_PRESETS[2]  # D-121, D-122
    assert airfoil.dimension == "2d" and airfoil.domain.shape == "c_type"
    assert airfoil.mesh.layer_controls == "wall_resolved" and airfoil.mesh.target_yplus == 1.0


def test_a_preset_never_carries_physics(tmp_path: Path) -> None:
    preset = preset_from_simulation(_custom_sim(), "Mine")
    dumped = preset.model_dump()
    assert set(dumped) == PRESET_KEYS
    text = json.dumps(dumped)
    for word in FORBIDDEN:
        assert f'"{word}' not in text, word
    with pytest.raises(ValueError):  # unknown fields are refused, not ignored
        Preset.model_validate({**dumped, "physics": {"nu": 1e-6}})
    with pytest.raises(ValueError):
        Preset.model_validate({**dumped, "domain": {**dumped["domain"], "parts": ["Wing"]}})


def test_apply_keeps_physics_and_sets_domain_and_mesh() -> None:
    source = _custom_sim()
    preset = preset_from_simulation(source, "Mine")
    target = Simulation(name="other", physics={"nu": 2e-5}, inflow={"speed": 9.0})
    out = apply_preset(target, preset)
    assert (out.analysis_type, out.preset_name) == ("external", "Mine")
    assert (out.domain.shape, out.domain.radius, out.domain.downstream, out.domain.symmetry) == (
        "bullet", 7.0, 12.0, "y_min")
    assert out.domain.enabled and out.domain.parts is None  # parts belong to a project, not a preset
    assert out.mesh == source.mesh
    assert (out.physics, out.inflow, out.solvers) == (target.physics, target.inflow, target.solvers)
    empty = apply_preset(target, BUILTIN_PRESETS[1])
    assert empty.analysis_type == "empty" and not empty.domain.enabled  # nothing generated automatically


def test_store_save_load_rename_delete(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "presets")
    assert store.scan() == ([], [])
    path = store.save(preset_from_simulation(_custom_sim(), "Wind tunnel"))
    data = json.loads(path.read_text())
    assert data["format_version"] == PRESET_FORMAT_VERSION and data["name"] == "Wind tunnel"
    assert [p.name for p in store.presets()] == ["Wind tunnel"]
    loaded = store.find("wind TUNNEL").preset
    assert loaded.domain.shape == "bullet" and loaded.mesh.layers == 5
    with pytest.raises(PresetError, match="already exists"):
        store.save(Preset(name="Wind tunnel"))
    store.save(Preset(name="Wind tunnel", analysis_type="empty"), overwrite=True)
    assert store.find("Wind tunnel").preset.analysis_type == "empty" and len(store.presets()) == 1
    store.save(Preset(name="Other"))
    with pytest.raises(PresetError, match="already exists"):
        store.rename("Other", "Wind tunnel")
    store.rename("Wind tunnel", "Tunnel B")
    assert [p.name for p in store.presets()] == ["Other", "Tunnel B"]
    store.delete("Other")
    assert [p.name for p in store.presets()] == ["Tunnel B"]
    with pytest.raises(PresetError):
        store.delete("Other")


@pytest.mark.parametrize("name", ["External flow", "empty", "  EMPTY "])
def test_builtin_names_are_reserved(tmp_path: Path, name: str) -> None:
    store = PresetStore(tmp_path)
    with pytest.raises(PresetError, match="built-in"):
        store.save(Preset(name=name))
    store.save(Preset(name="Mine"))
    with pytest.raises(PresetError, match="built-in"):
        store.rename("Mine", name)


def test_invalid_files_are_listed_as_broken(tmp_path: Path) -> None:
    store = PresetStore(tmp_path)
    store.save(Preset(name="Good"))
    (tmp_path / "garbage.json").write_bytes(b"\xff not json")
    (tmp_path / "list.json").write_text("[1, 2]")
    (tmp_path / "physics.json").write_text(json.dumps({**Preset(name="P").model_dump(), "physics": {}}))
    (tmp_path / "future.json").write_text(json.dumps({**Preset(name="F").model_dump(), "format_version": 99}))
    (tmp_path / "bad_type.json").write_text(json.dumps(
        {**Preset(name="B").model_dump(), "boundary_types": {"inlet": "wall"}}))
    (tmp_path / "builtin.json").write_text(json.dumps(Preset(name="X").model_dump() | {"name": "Empty"}))
    good, broken = store.scan()
    assert [s.preset.name for s in good] == ["Good"]
    assert sorted(b.path.name for b in broken) == ["bad_type.json", "builtin.json", "future.json", "garbage.json",
                                                   "list.json", "physics.json"]
    assert all(b.error for b in broken)
    store.delete_file(tmp_path / "list.json")
    assert not (tmp_path / "list.json").exists()


def test_preset_validation() -> None:
    with pytest.raises(ValueError):
        Preset(name="  ")
    with pytest.raises(ValueError):
        Preset(name="x" * 65)
    with pytest.raises(ValueError):
        Preset(name="P", boundary_types={"wall": "slip"})
    with pytest.raises(ValueError):
        Preset(name="P", domain={"radius": 0})


def test_v8_project_migrates_to_external(tmp_path: Path) -> None:
    path = Path(__file__).parent / "data" / "project_v8.json"
    assert json.loads(path.read_text())["schema_version"] == 8
    sim = load_simulation(path)
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 25
    assert (sim.analysis_type, sim.preset_name) == ("external", None)
    assert sim.domain == Domain(upstream=3.0, downstream=8.0, lateral=4.0, vertical=4.0, symmetry="y_min")
    assert sim.domain.shape == "box" and sim.domain.parts is None
    (body,) = sim.geometry.parts
    assert [r.name for r in body.regions] == ["nose", "rest"] and body.region_ids.endswith(".npy")
    assert (sim.mesh.background_cells_target, sim.mesh.layers, sim.inflow.speed) == (80000, 2, 15.0)
    assert (sim.solvers.iterations, sim.solvers.cores, sim.reports.slots) == (400, 2, ["Cd", "Cl", None])


def test_internal_is_selectable_and_its_presets_have_no_domain() -> None:
    """D-129: "internal" is an analysis type (schema v19); its built-in presets generate no domain; the 3D one keeps
    the wall-function default (y+ 50), the 2D one is wall-resolved (y+ 1)."""
    from vortexcfd.core.model import ANALYSIS_TYPES, RESERVED_ANALYSIS_TYPES

    assert "internal" in ANALYSIS_TYPES and "internal" not in RESERVED_ANALYSIS_TYPES
    assert Simulation(name="x", analysis_type="internal").internal
    internal, internal_2d = (p for p in BUILTIN_PRESETS if p.analysis_type == "internal")
    assert (internal.name, internal.dimension, internal.mesh.target_yplus) == ("Internal flow", "3d", 50.0)
    assert internal.mesh.layer_controls == "robust" and internal.mesh.target_surface_size == 0.05
    assert (internal_2d.dimension, internal_2d.mesh.target_yplus, internal_2d.mesh.layer_controls) == (
        "2d", 1.0, "wall_resolved")
    for preset in (internal, internal_2d):
        sim = apply_preset(Simulation(name="n"), preset)
        assert sim.analysis_type == "internal" and not sim.domain.enabled


PRESET_V1 = Path(__file__).parent / "data" / "preset_v1.json"


def test_a_preset_written_before_v10_keeps_the_v9_mesh_behaviour(tmp_path: Path) -> None:
    """D-090: a hand-written format 1 preset (no schema_version, so written before schema v10) is
    migrated like a v9 project: relative layers with target y+ 1, surface size from the largest
    extent, no curvature refinement; its stored mesh values are kept."""
    raw = json.loads(PRESET_V1.read_text())
    assert raw["format_version"] == 1 and "schema_version" not in raw and "layer_sizing" not in raw["mesh"]
    folder = tmp_path / "presets"
    folder.mkdir()
    (folder / "old.json").write_text(PRESET_V1.read_text())
    (preset,) = PresetStore(folder).presets()
    assert preset.schema_version == CURRENT_SCHEMA_VERSION and preset.format_version == PRESET_FORMAT_VERSION
    mesh = preset.mesh
    assert (mesh.layer_sizing, mesh.target_yplus) == ("relative", 1.0)
    assert (mesh.surface_size_reference, mesh.curvature_levels) == ("largest_extent", 0)
    for key, value in raw["mesh"].items():
        assert getattr(mesh, key) == value, key
    sim = apply_preset(Simulation(name="n"), preset)  # a new simulation from it has the v9 mesh
    assert sim.mesh == mesh and sim.domain.symmetry == "y_min"
    # an explicit value in an old preset wins over the v9 behaviour
    explicit = {**raw, "mesh": {**raw["mesh"], "layer_sizing": "absolute_yplus", "target_yplus": 30.0}}
    assert migrate_preset(explicit)["mesh"]["layer_sizing"] == "absolute_yplus"


def test_a_current_preset_round_trips_with_the_new_defaults_and_a_newer_schema_is_broken(tmp_path: Path) -> None:
    store = PresetStore(tmp_path)
    path = store.save(Preset(name="New"))
    data = json.loads(path.read_text())
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION == 25
    mesh = store.find("New").preset.mesh
    assert (mesh.layer_sizing, mesh.surface_size_reference, mesh.curvature_levels) == ("absolute_yplus", "l_ref", 2)
    (tmp_path / "newer.json").write_text(json.dumps({**data, "name": "Newer", "schema_version": CURRENT_SCHEMA_VERSION + 1}))
    good, broken = store.scan()
    assert [s.preset.name for s in good] == ["New"]
    assert len(broken) == 1 and f"schema version {CURRENT_SCHEMA_VERSION + 1}" in broken[0].error
