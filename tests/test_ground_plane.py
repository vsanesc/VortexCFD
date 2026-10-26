"""The ground plane of a box domain (D-116): model and migration, domain roles, meshing dictionaries,
solver boundary conditions, per-part forces and y+ without the ground, presets, tree and properties."""

from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Domain, Ground, Inflow, Mesh, Part, Physics, Simulation, Solvers
from vortexcfd.core.presets import DEFAULT_BOUNDARY_TYPES, apply_preset, preset_from_simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation, migrate
from vortexcfd.foam.mesh_case import (
    GROUND_PATCH,
    MeshCaseInput,
    block_mesh_dict,
    ground_split,
    ground_split_x,
    safe_part_names,
    snappy_hex_mesh_dict,
)
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, far_field_patches
from vortexcfd.foam.postprocessing import YPlusTail
from vortexcfd.geometry.domain import compute_domain, ground_wall_start, shape_roles
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.workflow import meshing, solving

# A 1 x 0.4 x 0.3 m body 0.05 m above z = 0 and a support crossing the plane z = 0 down to -0.01.
BODY = (0.0, 1.0, 0.0, 0.2, 0.05, 0.35)
STILT = (0.2, 0.23, 0.15, 0.18, -0.01, 0.06)


def _ground(**kw) -> Domain:
    return Domain(symmetry="y_min", ground=Ground(enabled=True, **kw))


# -- model, migration ----------------------------------------------------------------------------------


def test_ground_defaults_off_and_a_v15_project_migrates_unchanged(tmp_path: Path) -> None:
    assert Domain().ground == Ground() and not Ground().enabled
    assert migrate({"schema_version": 15, "x": 1}) == {"schema_version": 25, "x": 1}
    path = tmp_path / "old.vcfd"
    path.write_text('{"schema_version": 15, "name": "old", "domain": {"upstream": 3.0}}', encoding="utf-8")
    sim = load_simulation(path)
    assert sim.schema_version == 25 and sim.domain.upstream == 3.0 and not sim.domain.ground.enabled


def test_the_ground_needs_the_box_shape() -> None:
    with pytest.raises(ValueError, match="box domain"):
        Domain(shape="bullet", ground=Ground(enabled=True))
    Domain(shape="bullet", ground=Ground(enabled=False))  # stored off on any shape


def test_the_mesh_hash_ignores_a_ground_that_is_off_and_the_ground_motion() -> None:
    off = meshing._domain_for_hash(Domain())
    assert "ground" not in off and off == {k: v for k, v in Domain().model_dump().items()
                                           if k not in ("ground", "boundary_types", "units", "wall_layers")}
    still = meshing._domain_for_hash(_ground(motion="stationary"))
    moving = meshing._domain_for_hash(_ground(motion="moving"))
    assert still == moving and still["ground"]["enabled"]
    assert meshing._domain_for_hash(_ground(layers=True)) != still


# -- domain roles and position -------------------------------------------------------------------------


def test_roles_replace_bottom_with_ground_on_a_box_only() -> None:
    assert shape_roles("box", True, True) == ("inlet", "outlet", "sides", "top", "ground", "symmetry")
    assert shape_roles("box", False) == ("inlet", "outlet", "sides", "top", "bottom")
    assert shape_roles("bullet", False, True) == ("inlet", "outlet", "farfield")


def test_the_ground_lies_at_the_parts_lowest_z_or_at_the_value() -> None:
    box = compute_domain([BODY, STILT], _ground(), ["body", "stilt"])
    assert box.ground and box.bounds[4] == pytest.approx(-0.01) and box.boundaries["ground"] == ((2, 0),)
    assert "bottom" not in box.boundaries and box.roles[-2:] == ("ground", "symmetry")
    assert box.bounds[5] == pytest.approx(0.35 + 5 * 1.0)  # the top keeps vertical * L
    box = compute_domain([BODY, STILT], _ground(position="value", z=0.0), ["body", "stilt"])
    assert box.bounds[4] == 0.0 and not [m for m in box.warnings if "ground" in m]  # the stilt crosses it
    assert box.volume == pytest.approx(box.size[0] * box.size[1] * box.size[2])


def test_a_part_below_the_ground_is_reported_and_blocks_nothing_else() -> None:
    below = (2.0, 2.1, 0.0, 0.1, -0.5, -0.2)
    box = compute_domain([BODY, below], _ground(position="value", z=0.0), ["body", "low"])
    assert box.warnings == ["low lies below the ground plane (z = 0 m): it is outside the fluid."]


# -- meshing dictionaries ------------------------------------------------------------------------------


def _mesh_input(ground: bool, layers: bool = False) -> MeshCaseInput:
    box = compute_domain([BODY], _ground() if ground else Domain(symmetry="y_min"))
    return MeshCaseInput(box.bounds, True, tuple(safe_part_names(["body"])), BODY, box.reference_length,
                         Mesh(layer_sizing="relative", layers=3), ground=ground, ground_layers=layers)


def _patches(inp: MeshCaseInput) -> dict[str, dict]:
    return dict(block_mesh_dict(inp).content["boundary"])


def test_block_mesh_writes_the_ground_as_a_wall_patch_on_z_min() -> None:
    plain, ground = _patches(_mesh_input(False)), _patches(_mesh_input(True))
    assert plain["bottom"]["type"] == "patch" and GROUND_PATCH not in plain
    assert ground[GROUND_PATCH] == {"type": "wall", "faces": [[0, 3, 2, 1]]} and "bottom" not in ground
    assert _mesh_input(True).expected_domain_patches() == ("inlet", "outlet", "sides", "top", "ground",
                                                           "symmetry")


def test_prism_layers_on_the_ground_only_when_asked() -> None:
    def layers(inp):
        return snappy_hex_mesh_dict(inp).content["addLayersControls"]["layers"]

    assert GROUND_PATCH not in layers(_mesh_input(True))
    assert layers(_mesh_input(True, layers=True))[GROUND_PATCH] == {"nSurfaceLayers": 3}
    assert layers(_mesh_input(False)) == layers(_mesh_input(True))  # the parts' layers are unchanged


def test_ground_is_a_reserved_patch_name() -> None:
    assert safe_part_names(["ground"]) == ["ground_1"]


# -- solver files --------------------------------------------------------------------------------------


def _solver_files(ground: str | None, patches=("body", "stilt")) -> dict:
    inp = SolverCaseInput(Physics(), Inflow(speed=40.0), Solvers(), patches, BODY, True,
                          far_field=far_field_patches("box", ground is not None), ground=ground)
    return build_solver_files(inp)


def _bc(files: dict, field: str, patch: str):
    return files[f"0/{field}"].content["boundaryField"].get(patch)


def test_stationary_ground_has_the_parts_wall_conditions() -> None:
    files = _solver_files("stationary")
    for field in ("U", "p", "k", "omega", "nut"):
        assert _bc(files, field, GROUND_PATCH) == _bc(files, field, "body")
        assert _bc(files, field, "bottom") is None
    assert _bc(files, "U", GROUND_PATCH) == {"type": "noSlip"}
    assert _bc(files, "nut", GROUND_PATCH)["type"] == "nutUSpaldingWallFunction"
    assert _bc(files, "U", "sides") == {"type": "slip"} and _bc(files, "U", "top") == {"type": "slip"}


def test_moving_ground_has_the_free_stream_speed_along_x() -> None:
    files = _solver_files("moving")
    assert _bc(files, "U", GROUND_PATCH) == {"type": "fixedValue", "value": [40.0, 0.0, 0.0]}
    for field in ("p", "k", "omega", "nut"):
        assert _bc(files, field, GROUND_PATCH) == _bc(files, field, "body")


def test_without_the_ground_the_bottom_stays_slip() -> None:
    files = _solver_files(None)
    assert _bc(files, "U", "bottom") == {"type": "slip"} and _bc(files, "U", GROUND_PATCH) is None
    assert far_field_patches("box", False) == ("sides", "top", "bottom")
    assert far_field_patches("box", True) == ("sides", "top")
    assert far_field_patches("c_type", True) == ("farfield", "sides")


def test_forces_and_wall_shear_stress_exclude_the_ground() -> None:
    functions = _solver_files("moving")["system/controlDict"].content["functions"]
    for name, entry in functions.items():
        if entry.get("type") in ("forces", "forceCoeffs", "wallShearStress"):
            assert GROUND_PATCH not in entry["patches"], name
    assert functions["forces_body"]["patches"] == ["body"] and functions["forces_stilt"]["patches"] == ["stilt"]
    assert functions["forceCoeffs1"]["patches"] == ["body", "stilt"]


def test_part_yplus_leaves_the_ground_out(tmp_path: Path) -> None:
    path = tmp_path / "yPlus.dat"
    path.write_text("# Time patch min max average\n"
                    "10 body 1 80 40\n10 ground 0.5 500 200\n", encoding="utf-8")
    tail = YPlusTail(path)
    tail.poll()
    assert tail.series("average", {"body": 10, "ground": 1000}) == [(10.0, 40.0)]
    assert tail.series("max") == [(10.0, 80.0)] and tail.series("min") == [(10.0, 1.0)]


# -- presets -------------------------------------------------------------------------------------------


def test_presets_store_the_ground_option() -> None:
    sim = Simulation(name="a", domain=_ground(motion="moving", position="value", z=-0.01, layers=True))
    preset = preset_from_simulation(sim, "Ground")
    assert preset.domain.ground == sim.domain.ground and DEFAULT_BOUNDARY_TYPES["ground"] == "wall"
    assert apply_preset(Simulation(name="b"), preset).domain.ground == sim.domain.ground
    old = preset.model_dump()
    del old["domain"]["ground"]
    assert type(preset).model_validate(old).domain.ground == Ground()  # presets without it: off


# -- workflow ------------------------------------------------------------------------------------------


@pytest.fixture
def ground_project(tmp_path: Path) -> Project:
    clear_cache()
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True)
    pv.Box(bounds=BODY).triangulate().save(str(folder / "geometry" / "body.stl"))
    pv.Box(bounds=STILT).triangulate().save(str(folder / "geometry" / "stilt.stl"))
    project = Project.new("Ground")
    project.add_part(Part(name="body", source_file="geometry/body.stl", units="m"))
    project.add_part(Part(name="stilt", source_file="geometry/stilt.stl", units="m"))
    project.update_domain(symmetry="y_min")
    project.save(folder / "g.vcfd")
    return project


def test_workflow_inputs_carry_the_ground(ground_project: Project) -> None:
    before = meshing.inputs_hash(ground_project), solving.results_hash(ground_project)
    inp, box, _ = meshing.mesh_inputs(ground_project)
    assert not inp.ground and "bottom" in solving.solver_input(ground_project).far_field
    ground = {"enabled": True, "position": "value", "z": 0.0}
    ground_project.update_domain(ground=ground)
    inp, box, _ = meshing.mesh_inputs(ground_project)
    assert inp.ground and not inp.ground_layers and inp.domain_bounds[4] == 0.0
    s = solving.solver_input(ground_project)
    assert s.ground == "stationary" and s.far_field == ("sides", "top") and GROUND_PATCH not in s.patches
    mesh_hash, results = meshing.inputs_hash(ground_project), solving.results_hash(ground_project)
    assert mesh_hash != before[0]
    ground_project.update_domain(ground={**ground, "motion": "moving"})
    assert meshing.inputs_hash(ground_project) == mesh_hash  # the motion is a solver input only
    assert solving.results_hash(ground_project) != results
    ground_project.update_domain(ground={**ground, "z": 0.5})
    assert "ground plane is above every part" in meshing.readiness(ground_project)


# -- GUI -----------------------------------------------------------------------------------------------


@pytest.fixture
def window(qtbot: QtBot, ground_project: Project):
    w = MainWindow(ground_project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    assert not w.project.observer_errors
    w.project.save = lambda *a, **k: None
    w.close()


def _children(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_tree_lists_the_ground_and_its_properties_edit_it(window: MainWindow) -> None:
    w = window
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p = w.properties
    assert p._rows["dom_ground_enabled"].isVisible() and not p._rows["dom_ground_motion"].isVisible()
    before = len(w.project._undo)
    p.ground_enabled.setChecked(True)
    assert w.project.sim.domain.ground.enabled and len(w.project._undo) == before + 1
    assert _children(w._items[("fluid_domain", None)])[:6] == ["inlet", "outlet", "sides", "top", "ground",
                                                              "symmetry"]
    w.tree.setCurrentItem(w._items[("boundary_ground", None)])
    assert p._rows["dom_ground_motion"].isVisible() and not p._rows["dom_ground_z"].isVisible()
    assert p.ground_bcs.text().startswith("U noSlip;")
    p.ground_motion.setCurrentIndex(1)
    assert w.project.sim.domain.ground.motion == "moving"
    assert p.ground_bcs.text().startswith("U fixedValue (U_inf, 0, 0);")
    p.ground_position.setCurrentIndex(1)
    assert w.project.sim.domain.ground.position == "value"
    assert w.project.sim.domain.ground.z == pytest.approx(-0.01)  # starts from the plane in use
    assert p._rows["dom_ground_z"].isVisible()
    p.ground_layers.setChecked(True)
    assert w.project.sim.domain.ground.layers
    w.project.undo()
    assert not w.project.sim.domain.ground.layers


# -- the slip strip ahead of the ground wall (D-118) ---------------------------------------------------


def _strip_input(start: float | None, layers: bool = False) -> MeshCaseInput:
    domain = _ground(wall_start_x=start, layers=layers)
    box = compute_domain([BODY], domain)
    return MeshCaseInput(box.bounds, True, tuple(safe_part_names(["body"])), BODY, box.reference_length,
                         Mesh(layer_sizing="relative", layers=3), ground=True, ground_layers=layers,
                         ground_wall_start=ground_wall_start(domain, box.bounds))


def test_a_v16_project_migrates_without_a_slip_strip(tmp_path: Path) -> None:
    assert migrate({"schema_version": 16, "x": 1}) == {"schema_version": 25, "x": 1}
    path = tmp_path / "v16.vcfd"
    path.write_text('{"schema_version": 16, "name": "v16", "domain": {"ground": {"enabled": true}}}',
                    encoding="utf-8")
    sim = load_simulation(path)
    assert sim.schema_version == 25 and sim.domain.ground.enabled and sim.domain.ground.wall_start_x is None
    # no slip strip: the mesh hash of schema v16
    assert "wall_start_x" not in meshing._domain_for_hash(_ground())["ground"]
    assert meshing._domain_for_hash(_ground(wall_start_x=-1.0))["ground"]["wall_start_x"] == -1.0


def test_the_wall_start_inside_the_box_only_makes_a_strip() -> None:
    box = compute_domain([BODY], _ground())
    x0, x1 = box.bounds[0], box.bounds[1]
    assert ground_wall_start(_ground(wall_start_x=-1.0), box.bounds) == -1.0
    assert ground_wall_start(_ground(wall_start_x=x0), box.bounds) is None  # at the inlet: no strip
    assert ground_wall_start(_ground(wall_start_x=None), box.bounds) is None
    assert ground_wall_start(Domain(ground=Ground(wall_start_x=-1.0)), box.bounds) is None  # ground off
    assert ground_wall_start(_ground(wall_start_x=x1 + 1), box.bounds) == x1 + 1  # meshing refuses it


def test_block_mesh_splits_the_ground_into_the_slip_strip_and_the_wall() -> None:
    one, two = _mesh_input(True), _strip_input(-1.32)
    est = two.estimate()
    x0, x1 = est.background_bounds[0], est.background_bounds[1]
    nx, ny, nz = est.cells
    step = (x1 - x0) / nx
    blocks = block_mesh_dict(two).content["blocks"]
    n_up = blocks[2][0]
    assert blocks[0] == "hex" and blocks[5] == "hex"
    assert blocks[2] == [n_up, ny, nz] and blocks[7] == [nx - n_up, ny, nz]  # the same cells as one block
    split = ground_split_x(two)
    assert split == pytest.approx(x0 + n_up * step) and abs(split - (-1.32)) <= step / 2
    vertices = block_mesh_dict(two).content["vertices"]
    assert sorted({v[0] for v in vertices}) == pytest.approx([x0, split, x1])
    patches = _patches(two)
    assert patches["ground_slip"]["type"] == "patch" and patches[GROUND_PATCH]["type"] == "wall"
    assert len(patches["ground_slip"]["faces"]) == 1 and len(patches[GROUND_PATCH]["faces"]) == 1

    def xs(face):
        return {vertices[i][0] for i in face}

    def zs(face):
        return {vertices[i][2] for i in face}

    assert xs(patches["ground_slip"]["faces"][0]) == {x0, split} and zs(patches["ground_slip"]["faces"][0]) == {est.background_bounds[4]}
    assert xs(patches[GROUND_PATCH]["faces"][0]) == {split, x1}
    assert xs(patches["inlet"]["faces"][0]) == {x0} and xs(patches["outlet"]["faces"][0]) == {x1}
    assert len(patches["top"]["faces"]) == 2 and len(patches["symmetry"]["faces"]) == 2
    assert two.expected_domain_patches() == ("inlet", "outlet", "sides", "top", "ground", "ground_slip", "symmetry")
    # without a strip: the single block as before
    assert ground_split_x(one) is None and len(block_mesh_dict(one).content["blocks"]) == 5


def test_the_split_keeps_both_patches_non_empty() -> None:
    assert ground_split(0.0, 10.0, 10, -5.0) == 1 and ground_split(0.0, 10.0, 10, 3.4) == 3
    assert ground_split(0.0, 10.0, 10, 9.9) == 9


def test_prism_layers_go_on_the_ground_wall_only() -> None:
    layers = snappy_hex_mesh_dict(_strip_input(-1.32, layers=True)).content["addLayersControls"]["layers"]
    assert layers[GROUND_PATCH] == {"nSurfaceLayers": 3} and "ground_slip" not in layers


def test_the_slip_strip_is_reserved_and_takes_the_far_field_conditions() -> None:
    assert safe_part_names(["ground_slip"]) == ["ground_slip_1"]
    assert far_field_patches("box", True, True) == ("sides", "top", "ground_slip")
    inp = SolverCaseInput(Physics(), Inflow(speed=40.0), Solvers(), ("body", "stilt"), BODY, True,
                          far_field=far_field_patches("box", True, True), ground="stationary")
    files = build_solver_files(inp)
    for field in ("U", "p", "k", "omega", "nut"):
        assert _bc(files, field, "ground_slip") == _bc(files, field, "top")
    assert _bc(files, "U", "ground_slip") == {"type": "slip"} and _bc(files, "U", GROUND_PATCH) == {"type": "noSlip"}
    for name, entry in files["system/controlDict"].content["functions"].items():
        if entry.get("type") in ("forces", "forceCoeffs", "wallShearStress"):
            assert GROUND_PATCH not in entry["patches"] and "ground_slip" not in entry["patches"], name


def test_workflow_inputs_carry_the_wall_start(ground_project: Project) -> None:
    ground = {"enabled": True, "position": "value", "z": 0.0}
    ground_project.update_domain(ground=ground)
    mesh_hash = meshing.inputs_hash(ground_project)
    ground_project.update_domain(ground={**ground, "wall_start_x": -0.5})
    inp, box, _ = meshing.mesh_inputs(ground_project)
    assert inp.ground_wall_start == -0.5 and "ground_slip" in inp.expected_domain_patches()
    assert solving.solver_input(ground_project).far_field == ("sides", "top", "ground_slip")
    assert meshing.inputs_hash(ground_project) != mesh_hash
    ground_project.update_domain(ground={**ground, "wall_start_x": box.bounds[1] + 1.0})
    assert "behind the outlet" in meshing.readiness(ground_project)


def test_the_wall_start_is_edited_in_the_ground_properties(window: MainWindow) -> None:
    w = window
    p = w.properties
    w.tree.setCurrentItem(w._items[("fluid_domain", None)])
    p.ground_enabled.setChecked(True)
    w.tree.setCurrentItem(w._items[("boundary_ground", None)])
    assert p._rows["dom_ground_start"].isVisible() and p.ground_start.text() == "inlet"
    p.ground_start.setValue(-0.4)
    p.ground_start.editingFinished.emit()
    assert w.project.sim.domain.ground.wall_start_x == pytest.approx(-0.4)
    assert "ground_slip ahead of the wall start: slip" in p.ground_bcs.text()
    p.ground_start.setValue(p.ground_start.minimum())
    p.ground_start.editingFinished.emit()
    assert w.project.sim.domain.ground.wall_start_x is None
