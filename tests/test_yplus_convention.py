"""The target y+ at the first cell centre (schema v14, D-107). [NUMERICS-REVIEW]"""

import json
import math
from pathlib import Path

import pytest

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Mesh
from vortexcfd.core.presets import migrate_preset
from vortexcfd.core.project_io import V14_MESH_FIELDS, load_simulation, migrate
from vortexcfd.foam.yplus import first_layer_thickness, yplus_of_first_cell

DATA = Path(__file__).parent / "data"


def test_first_layer_against_a_hand_calculation() -> None:
    # V = 20 m/s, nu = 1.5e-5 m2/s, L = 1 m: Re = 1,333,333; Re^(1/7) = 7.4990; Cf = 0.026 / 7.4990 = 0.0034672;
    # u* = sqrt(0.5 * 20^2 * 0.0034672) = 0.83273 m/s; y(y+ 50) = 50 * 1.5e-5 / 0.83273 = 9.0065e-4 m.
    y = 50 * 1.5e-5 / math.sqrt(0.5 * 20.0**2 * 0.026 / (20.0 * 1.0 / 1.5e-5) ** (1 / 7))
    assert y == pytest.approx(9.0065e-4, rel=1e-4)
    assert first_layer_thickness(50.0, 20.0, 1.5e-5, 1.0, "cell_height") == pytest.approx(9.0065e-4, rel=1e-4)
    # at the first cell centre the target distance is half the first layer: the layer is 1.8013 mm
    assert first_layer_thickness(50.0, 20.0, 1.5e-5, 1.0, "cell_centre") == pytest.approx(1.8013e-3, rel=1e-4)
    assert first_layer_thickness(50.0, 20.0, 1.5e-5, 1.0) == first_layer_thickness(50.0, 20.0, 1.5e-5, 1.0,
                                                                                   "cell_height")  # function default
    with pytest.raises(ValueError):
        first_layer_thickness(50.0, 20.0, 1.5e-5, 1.0, "wall")


def test_the_cell_centre_layer_gives_the_target_at_the_cell_centre() -> None:
    # yplus_of_first_cell is the cell-centre y+ (OpenFOAM's nearWallDist): the inverse of the cell_centre rule
    h = first_layer_thickness(30.0, 40.0, 1.5e-5, 2.0, "cell_centre")
    assert yplus_of_first_cell(h, 40.0, 1.5e-5, 2.0) == pytest.approx(30.0, rel=1e-12)
    h_old = first_layer_thickness(30.0, 40.0, 1.5e-5, 2.0, "cell_height")
    assert yplus_of_first_cell(h_old, 40.0, 1.5e-5, 2.0) == pytest.approx(15.0, rel=1e-12)


def test_new_meshes_place_the_target_at_the_cell_centre() -> None:
    assert Mesh().yplus_at == "cell_centre" and V14_MESH_FIELDS == {"yplus_at": "cell_height"}


def test_v13_project_keeps_the_cell_height_convention() -> None:
    stored = json.loads((DATA / "project_v13.json").read_text())
    assert stored["schema_version"] == 13 and "yplus_at" not in stored["mesh"]
    sim = load_simulation(DATA / "project_v13.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 25
    assert sim.mesh.yplus_at == "cell_height" and sim.mesh.layer_controls == "robust"  # stored settings kept
    assert sim.mesh.target_yplus == 50.0 and sim.inflow.speed == 20.0
    assert migrate({"schema_version": 13, "mesh": {"yplus_at": "cell_centre"}})["mesh"]["yplus_at"] == "cell_centre"
    assert migrate_preset({"schema_version": 13, "name": "p", "mesh": {}})["mesh"]["yplus_at"] == "cell_height"
    assert "yplus_at" not in migrate_preset({"schema_version": 14, "name": "p", "mesh": {}})["mesh"]


def test_the_layer_plan_follows_the_convention(monkeypatch) -> None:
    from vortexcfd.core.project import Project
    from vortexcfd.workflow import meshing

    project = Project.new("y")
    seen = []

    def fake_first(target, speed, nu, length, yplus_at="cell_height"):
        seen.append(yplus_at)
        return first_layer_thickness(target, speed, nu, length, yplus_at)

    monkeypatch.setattr(meshing, "first_layer_thickness", fake_first)
    monkeypatch.setattr(meshing, "surface_length", lambda *a, **k: type("L", (), {"value": 1.0})())

    class Box:
        reference_length = 1.0

    monkeypatch.setattr(meshing, "estimate_for", lambda *a, **k: type("E", (), {"surface_size": 0.02})())
    plan = meshing.plan_layers_for(project, Box())
    assert seen == ["cell_centre"]
    assert plan.first == pytest.approx(first_layer_thickness(50.0, project.sim.inflow.speed, project.sim.physics.nu,
                                                             1.0, "cell_centre"))
    project.update_mesh(yplus_at="cell_height")
    assert meshing.plan_layers_for(project, Box()).first == pytest.approx(plan.first / 2)


def test_a_migrated_project_keeps_its_mesh_hash(monkeypatch) -> None:
    from vortexcfd.core.project import Project
    from vortexcfd.workflow.meshing import inputs_hash

    project = Project.new("h")
    project.update_mesh(yplus_at="cell_height")
    legacy = inputs_hash(project)
    original = Mesh.model_dump

    def v13_dump(self, *a, **k):  # a v13 Mesh had no yplus_at field
        d = original(self, *a, **k)
        d.pop("yplus_at", None)
        return d

    with monkeypatch.context() as m:
        m.setattr(Mesh, "model_dump", v13_dump)
        assert inputs_hash(project) == legacy  # the hash the project had before v14
    project.update_mesh(yplus_at="cell_centre")
    assert inputs_hash(project) != legacy
