"""The robust prism-layer controls of task 5.4 (D-106): the layer cap with the expansion ratio raised to keep
the planned stack, the snappyHexMeshDict entries, the v12 -> v13 migration and the mesh hash."""

import json
from pathlib import Path

import pytest

from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Mesh
from vortexcfd.core.presets import migrate_preset
from vortexcfd.core.project_io import V13_MESH_FIELDS, V14_MESH_FIELDS, load_simulation, migrate
from vortexcfd.foam.mesh_case import (
    ROBUST_CONTROLS_REVISION,
    ROBUST_LAYER_CONTROLS,
    ROBUST_RELAXED_QUALITY,
    MeshCaseInput,
    snappy_hex_mesh_dict,
)
from vortexcfd.foam.mesh_study import reference_layers
from vortexcfd.foam.yplus import (
    LAYER_CAP,
    MAX_EXPANSION_RATIO,
    layer_cap,
    plan_layers,
    stack_thickness,
)

DATA = Path(__file__).parent / "data"
BOX = (-5, 10, -5, 5, -5, 5)
PARTS = (0.0, 1.0, -0.5, 0.5, 0.0, 0.3)


def test_cap_raises_the_expansion_ratio_to_keep_the_planned_stack() -> None:
    # 0.5 h / t1 = 20: n = ceil(ln 20 / ln 1.2) + 1 = 17 + 1 = 18 layers at 1.2 (128 mm); a cap of 15 reaches it
    # below 1.3 (15 layers at 1.3: 167 mm)
    first, h = 1e-3, 0.04
    free = plan_layers(first, 1.2, h)
    assert free.count == free.planned_count == 18 and not free.capped and free.thickness_warning is None
    capped = plan_layers(first, 1.2, h, max_layers=15, max_expansion=1.3)
    assert capped.capped and capped.count == 15 and capped.first == first  # the y+ first layer is kept
    assert capped.planned_count == 18 and capped.planned_total == pytest.approx(free.total)
    assert 1.2 < capped.expansion <= 1.3
    assert capped.total == pytest.approx(capped.planned_total, rel=1e-9)  # the planned total, reached
    assert capped.thickness_warning is None and capped.thickness_percent == pytest.approx(100.0)
    assert capped.final == pytest.approx(first * capped.expansion ** 14)


def test_cap_that_cannot_reach_the_planned_stack_keeps_the_first_layer_and_warns() -> None:
    # the 5.4 aircraft: 0.64 mm first layer, 84 mm surface cells: 24 planned layers (251 mm at 1.2)
    first, h = 0.64e-3, 0.084
    plan = plan_layers(first, 1.2, h, max_layers=12, max_expansion=1.3)
    assert plan.planned_count == 24 and plan.count == 12 and plan.first == first
    assert plan.expansion == MAX_EXPANSION_RATIO  # the hard maximum
    assert plan.total == pytest.approx(stack_thickness(first, 1.3, 12)) and plan.total < plan.planned_total
    assert plan.thickness_percent == pytest.approx(100.0 * plan.total / plan.planned_total)
    assert plan.thickness_warning and "thinner than planned" in plan.thickness_warning
    assert f"{plan.planned_total:.3g}" in plan.thickness_warning and "first layer" in plan.thickness_warning


def test_cap_does_not_touch_a_stack_within_it_or_a_ratio_above_the_maximum() -> None:
    within = plan_layers(1e-3, 1.2, 8.4e-3, max_layers=12, max_expansion=1.3)  # 9 layers (hand value)
    assert within == plan_layers(1e-3, 1.2, 8.4e-3) or (within.count, within.expansion) == (9, 1.2)
    assert not within.capped and within.thickness_warning is None
    steep = plan_layers(1e-4, 1.4, 0.1, max_layers=12, max_expansion=1.3)  # the user's 1.4 is never lowered
    assert steep.capped and steep.count == 12 and steep.expansion == 1.4


def test_layer_cap_arguments_follow_the_layer_controls() -> None:
    assert layer_cap("robust") == {"max_layers": LAYER_CAP, "max_expansion": MAX_EXPANSION_RATIO}
    assert layer_cap("legacy") == {}
    assert 12 <= LAYER_CAP <= 15 and MAX_EXPANSION_RATIO == 1.3  # D2 of task 5.4
    assert Mesh().layer_controls == "robust"


def test_mesh_study_shares_the_capped_stack() -> None:
    robust = reference_layers(Mesh(), 0.084, 0.64e-3)
    assert (robust.count, robust.expansion) == (LAYER_CAP, MAX_EXPANSION_RATIO)
    legacy = reference_layers(Mesh(layer_controls="legacy"), 0.084, 0.64e-3)
    assert (legacy.count, legacy.expansion) == (24, 1.2)


def _dict(mesh: Mesh, **kw) -> dict:
    inp = MeshCaseInput(BOX, False, ("Wing",), PARTS, 1.0, mesh, **kw)
    return snappy_hex_mesh_dict(inp).content


def test_robust_controls_and_the_plan_ratio_are_written_for_y_plus_layers() -> None:
    d = _dict(Mesh(), first_layer_thickness=1e-3, layer_count=12, layer_expansion=1.27)
    alc = d["addLayersControls"]
    assert alc["expansionRatio"] == 1.27 and alc["firstLayerThickness"] == 1e-3
    assert alc["layers"]['"Wing.*"'] == {"nSurfaceLayers": 12}
    for key, value in ROBUST_LAYER_CONTROLS.items():
        assert alc[key] == value, key
    # the tet check stays on during layer addition with the robust controls (5.4b study, D-106)
    assert d["meshQualityControls"]["relaxed"] == ROBUST_RELAXED_QUALITY == {"minTetQuality": 1e-15}
    assert d["meshQualityControls"]["minTetQuality"] == 1e-15 and alc["nOuterIter"] == 2


def test_legacy_and_relative_sizing_keep_the_pre_5_4_controls() -> None:
    legacy = _dict(Mesh(layer_controls="legacy"), first_layer_thickness=1e-3, layer_count=24, layer_expansion=1.2)
    relative = _dict(Mesh(layer_sizing="relative", layers=3, expansion_ratio=1.25), layer_expansion=1.3)
    for d in (legacy, relative):
        alc = d["addLayersControls"]
        assert alc["featureAngle"] == 60 and "nOuterIter" not in alc and alc["nSmoothThickness"] == 10
    assert legacy["meshQualityControls"]["relaxed"] == {"minTetQuality": -1e30}  # D-045, unchanged
    assert "relaxed" not in relative["meshQualityControls"]
    assert relative["addLayersControls"]["expansionRatio"] == 1.25  # relative sizing: the setting


def test_v12_project_migrates_to_the_legacy_layer_controls() -> None:
    stored = json.loads((DATA / "project_v12.json").read_text())
    assert stored["schema_version"] == 12 and "layer_controls" not in stored["mesh"]
    sim = load_simulation(DATA / "project_v12.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 19
    assert sim.mesh.layer_controls == "legacy" and sim.mesh.expansion_ratio == 1.2  # stored settings kept
    assert sim.inflow.speed == 30.0 and sim.reports.reference_length == 1.5
    assert migrate({"schema_version": 12})["mesh"] == {**V13_MESH_FIELDS, **V14_MESH_FIELDS}
    assert migrate({"schema_version": 12, "mesh": {"layer_controls": "robust"}})["mesh"]["layer_controls"] == "robust"
    # a preset written before v13 keeps them too; a v13 preset keeps the robust default
    assert migrate_preset({"schema_version": 12, "name": "p", "mesh": {}})["mesh"]["layer_controls"] == "legacy"
    assert "layer_controls" not in migrate_preset({"schema_version": 13, "name": "p", "mesh": {}})["mesh"]


def test_a_migrated_project_keeps_its_mesh_hash(monkeypatch) -> None:
    from vortexcfd.core.project import Project
    from vortexcfd.workflow.meshing import inputs_hash

    project = Project.new("h")
    project.update_mesh(layer_controls="legacy")
    legacy = inputs_hash(project)
    original = Mesh.model_dump

    def v12_dump(self, *a, **k):  # a v12 Mesh had no layer_controls field
        d = original(self, *a, **k)
        d.pop("layer_controls", None)
        return d

    with monkeypatch.context() as m:
        m.setattr(Mesh, "model_dump", v12_dump)
        assert inputs_hash(project) == legacy  # the hash the project had before v13
    project.update_mesh(layer_controls="robust")
    assert inputs_hash(project) != legacy


def test_a_mesh_made_with_the_5_4_robust_controls_is_out_of_date(monkeypatch) -> None:
    from vortexcfd.core.project import Project
    from vortexcfd.workflow import meshing

    project = Project.new("r")
    current = meshing.inputs_hash(project)
    monkeypatch.setattr(meshing, "ROBUST_CONTROLS_REVISION", "5.4")
    assert meshing.inputs_hash(project) != current  # the controls changed in 5.4b (D-106)
    assert ROBUST_CONTROLS_REVISION == "5.4b"
    project.update_mesh(layer_controls="legacy")
    legacy = meshing.inputs_hash(project)
    monkeypatch.setattr(meshing, "ROBUST_CONTROLS_REVISION", "5.4b")
    assert meshing.inputs_hash(project) == legacy  # legacy projects keep their hash
