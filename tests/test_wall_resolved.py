"""The wall-resolved layer controls (D-122): the stack rule, the surface refinement it asks for, the relaxed quality
set of the layer phase, the mesh study's per-level stacks and 2D scaling, the first-cell share and the study's
hook that leaves a level unsolved."""

import math
from pathlib import Path

import pytest

from tests.test_section_2d import airfoil_project
from vortexcfd.core.model import Mesh
from vortexcfd.foam import gci
from vortexcfd.foam.mesh_case import (
    MESH_QUALITY,
    ROBUST_RELAXED_QUALITY,
    WALL_RESOLVED_RELAXED_QUALITY,
    MeshCaseInput,
    snappy_hex_mesh_dict,
)
from vortexcfd.foam.mesh_study import LevelResult, StudyRecord, StudyRun, scale_mesh
from vortexcfd.foam.yplus import (
    WR_EXPANSION,
    WR_LAYER_CAP,
    WR_MAX_CELL_TO_FIRST,
    plan_wall_resolved,
    stack_thickness,
)

FIRST = 8.913755755379576e-06  # y+ 1 at the cell centre, 90 m/s, nu 1.5e-5, l_ref 1 m (D-107)


def test_the_stack_is_one_surface_cell_thick() -> None:
    for h in (1.953125e-3, 0.9765625e-3, 0.5e-3):
        plan = plan_wall_resolved(FIRST, h)
        assert plan.expansion == WR_EXPANSION == 1.2
        assert plan.total >= h > stack_thickness(FIRST, 1.2, plan.count - 1)  # the smallest such count
        assert plan.final / h == pytest.approx(0.17, abs=0.04)  # the last layer about (r - 1) / r of the cell
        assert plan.warning is None and plan.thickness_warning is None
    assert plan_wall_resolved(FIRST, 1.953125e-3).count == 21  # the study's level-9 case (D-122)


def test_a_coarse_surface_or_the_cap_is_reported() -> None:
    coarse = plan_wall_resolved(FIRST, 2 * WR_MAX_CELL_TO_FIRST * FIRST)
    assert coarse.warning is not None and "refine the surface" in coarse.warning
    huge = plan_wall_resolved(1e-7, 0.05)
    assert huge.count == WR_LAYER_CAP and huge.capped and huge.thickness_warning is not None


def test_the_relaxed_quality_set_of_the_layer_phase() -> None:
    def inputs(controls: str) -> MeshCaseInput:
        mesh = Mesh(layer_controls=controls, target_yplus=1.0)
        return MeshCaseInput(domain_bounds=(-5, 5, -5, 5, -5, 5), symmetric=False, parts=("b",),
                             parts_bounds=(-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), reference_length=1.0, mesh=mesh,
                             first_layer_thickness=FIRST, layer_count=21, layer_expansion=1.2)

    wr = snappy_hex_mesh_dict(inputs("wall_resolved")).content
    q = wr["meshQualityControls"]
    assert q["relaxed"] == WALL_RESOLVED_RELAXED_QUALITY == {"minTetQuality": 1e-15, "minDeterminant": 1e-5,
                                                             "maxNonOrtho": 75}
    assert q["minDeterminant"] == MESH_QUALITY["minDeterminant"] == 0.001 and q["maxNonOrtho"] == 65  # snapping
    layers = wr["addLayersControls"]
    assert layers["nRelaxedIter"] == 0 and layers["featureAngle"] == 130 and layers["nOuterIter"] == 2
    assert layers["expansionRatio"] == 1.2
    robust = snappy_hex_mesh_dict(inputs("robust")).content
    assert robust["meshQualityControls"]["relaxed"] == ROBUST_RELAXED_QUALITY  # D-106 unchanged


def test_meshing_raises_the_surface_level_to_the_first_layer(tmp_path: Path) -> None:
    from vortexcfd.workflow import meshing

    project = airfoil_project(tmp_path, target_surface_size=0.02)  # coarse on purpose: 20 mm wanted
    box = meshing.loaded_parts(project)[0]
    plain = meshing.estimate_for(box, project.sim.mesh, 1.0)
    est = meshing.project_estimate(project, box)
    plan = meshing.plan_layers_for(project, box)
    assert plain.surface_size > WR_MAX_CELL_TO_FIRST * plan.first
    assert est.surface_size <= WR_MAX_CELL_TO_FIRST * plan.first * (1 + 1e-9) < 2 * est.surface_size
    assert est.level_max == math.ceil(math.log2(est.base_size / (WR_MAX_CELL_TO_FIRST * plan.first)))
    project.update_mesh(layer_controls="robust", target_yplus=5.0)  # below 5 robust gives way (D-123)
    assert meshing.project_estimate(project, box).level_max == plain.level_max  # robust: the settings as they are


def test_2d_study_levels_scale_the_area_and_keep_the_first_layer(tmp_path: Path) -> None:
    from vortexcfd.workflow import mesh_study

    assert scale_mesh(Mesh(background_cells_target=8000), 2.0, dimensions=2).background_cells_target == 2000
    assert scale_mesh(Mesh(background_cells_target=8000), 2.0).background_cells_target == 1000
    assert gci.cell_size(100.0, 25, dimensions=2) == pytest.approx(2.0)
    project = airfoil_project(tmp_path)
    plan = mesh_study.plan_study(project)
    sizes = [lp.estimate.surface_size for lp in plan.levels]
    assert sizes[0] == pytest.approx(2 * sizes[2]) and sizes[1] == pytest.approx(math.sqrt(2) * sizes[2], rel=1e-6)
    stacks = [mesh_study.level_layers(project, plan, lp) for lp in plan.levels]
    assert len({s[0] for s in stacks}) == 1 and all(s[2] == 1.2 for s in stacks)  # one first layer, one ratio
    assert stacks[0][1] > stacks[1][1] > stacks[2][1]  # each grown to its own surface cell
    for (first, count, ratio), h in zip(stacks, sizes):
        assert stack_thickness(first, ratio, count) >= h
    study_dir, record, _inputs = mesh_study.prepare_study(project)
    assert record.dimensions == 2 and record.domain_volume == pytest.approx(plan.domain_volume)
    assert [lv.planned_layers for lv in record.levels] == [[s[0], s[1]] for s in stacks]


def test_a_level_can_be_left_unsolved(tmp_path: Path) -> None:
    from tests.test_mesh_study import FakeMeshRun, FakeSolverRun

    FakeMeshRun.calls, FakeSolverRun.n = [], 0
    levels = [LevelResult(i, n, 1.0, planned_layers=[FIRST, 21]) for i, n in enumerate(("coarse", "medium", "fine"))]
    record = StudyRecord(2.0 ** 0.5, "fine", ["Cd"], 1, 100.0, levels, dimensions=2)
    seen = []

    def before(level, report):
        seen.append((level.name, report.cells))
        return "layers collapsed" if level.name == "coarse" else None

    run = StudyRun(tmp_path, record, lambda case: None, mesh_run_factory=FakeMeshRun, solver_run_factory=FakeSolverRun,
                   before_solve=before)
    run.start()
    out = run.wait(10)
    assert out.status == "finished" and [s[0] for s in seen] == ["coarse", "medium", "fine"]
    assert out.levels[0].error == "layers collapsed" and out.levels[0].state is None
    assert out.levels[1].state is not None and FakeSolverRun.n == 2
    assert out.levels[0].h == pytest.approx((100.0 / 1000) ** 0.5)  # 2D: (A / N)^(1/2)


def test_each_2d_level_uses_its_own_span_for_the_reference_area(tmp_path: Path) -> None:
    """A 2D level's slab is one of its own surface cells thick: the study writes chord x that span (the coarse
    level's span is twice the fine one's), not the project's."""
    from vortexcfd.foam.dictfile import read_foam_file
    from vortexcfd.workflow import mesh_study

    project = airfoil_project(tmp_path)
    study_dir, record, _inputs = mesh_study.prepare_study(project)
    writer = mesh_study.solver_writer(project)
    areas = []
    for n in (1, 3):
        case = study_dir / f"level_{n}"
        writer(case)
        areas.append(float(read_foam_file(case / "system" / "controlDict")["functions"]["forceCoeffs1"]["Aref"]))
    assert areas[0] == pytest.approx(2 * areas[1])


def test_a_target_y_plus_below_5_selects_the_wall_resolved_controls(tmp_path: Path) -> None:
    """D-123 (QUESTIONS 187): the robust controls with absolute sizing and a target y+ below 5 mesh with the
    wall-resolved controls; the stored choice is kept, so a target of 5 or more gives the robust controls back."""
    from vortexcfd.core.model import WALL_RESOLVED_AUTO_YPLUS
    from vortexcfd.workflow import meshing

    assert WALL_RESOLVED_AUTO_YPLUS == 5.0
    assert Mesh(target_yplus=1.0).effective_layer_controls == "wall_resolved" and Mesh(target_yplus=1.0).wall_resolved_auto
    assert Mesh(target_yplus=4.99).effective_layer_controls == "wall_resolved"
    assert Mesh(target_yplus=5.0).effective_layer_controls == "robust"
    assert Mesh(target_yplus=1.0, layer_sizing="relative").effective_layer_controls == "robust"
    assert Mesh(target_yplus=1.0, layer_controls="legacy").effective_layer_controls == "legacy"  # pre-v13 projects
    assert not Mesh(target_yplus=1.0, layer_controls="wall_resolved").wall_resolved_auto  # chosen, not automatic

    project = airfoil_project(tmp_path, target_surface_size=0.02)
    box = meshing.loaded_parts(project)[0]
    chosen = (meshing.project_estimate(project, box), meshing.plan_layers_for(project, box),
              meshing.inputs_hash(project))
    project.update_mesh(layer_controls="robust")  # y+ 1 (the preset): automatic
    assert project.sim.mesh.layer_controls == "robust" and project.sim.mesh.wall_resolved_auto
    settings = meshing.meshing_settings(project, box)
    assert settings.layer_controls == "wall_resolved" and project.sim.mesh.layer_controls == "robust"
    assert meshing.project_estimate(project, box).level_max == chosen[0].level_max  # the surface refined (D-122)
    assert meshing.plan_layers_for(project, box) == chosen[1]
    assert meshing.inputs_hash(project) != chosen[2]  # recorded as automatic: a robust mesh made before is stale
    job_inputs = meshing.prepare_job(project).inputs
    assert job_inputs.mesh.layer_controls == "wall_resolved"
    shm = snappy_hex_mesh_dict(job_inputs).content
    assert shm["meshQualityControls"]["relaxed"] == WALL_RESOLVED_RELAXED_QUALITY
    project.update_mesh(target_yplus=30.0)  # out of the viscous sublayer: robust again
    assert meshing.meshing_settings(project, box).layer_controls == "robust" and not project.sim.mesh.wall_resolved_auto


def test_the_2d_study_uses_the_domain_area_for_the_cell_size(tmp_path: Path) -> None:
    """QUESTIONS 189: a 2D study's h is (A / N)^(1/2) with A the domain's x-z area (not area x span); round 1's
    NACA 0012 10 deg study (docs/validation/naca0012/RESULT.md) recomputed from its recorded values."""
    from vortexcfd.workflow import mesh_study, meshing

    project = airfoil_project(tmp_path)
    plan = mesh_study.plan_study(project)
    box = meshing.loaded_parts(project)[0]
    assert plan.domain_volume == pytest.approx(box.volume / (box.bounds[3] - box.bounds[2]))
    area, cells = 35806.46779498581, (68331, 119064, 210526)  # round 1's record
    h = [gci.cell_size(area, n, dimensions=2) for n in cells]
    assert h == pytest.approx([0.7238888, 0.5483912, 0.4124088], rel=1e-6)
    assert h[0] / h[1] == pytest.approx(1.32, abs=0.005) and h[1] / h[2] == pytest.approx(1.33, abs=0.005)
    viscous = gci.study([0.005404367044595616, 0.005465528902118417, 0.005509831046611236], h)
    assert viscous.convergence == "monotonic" and viscous.order == pytest.approx(1.24, abs=0.02)
    assert viscous.gci_fine == pytest.approx(0.0237, abs=0.0005) and viscous.extrapolated == pytest.approx(0.005614, abs=1e-6)
    assert gci.study([1.040667, 1.034575, 1.047405], h).convergence == "oscillatory"  # CL: no GCI


def test_the_wall_resolved_2d_staircase_has_a_thicker_buffer(tmp_path: Path) -> None:
    """D-124: in 2D the wall-resolved controls (chosen or automatic) grow each staircase box by WR_SECTION_BUFFER_CELLS
    cells of its level; the other modes keep snappyHexMesh's nCellsBetweenLevels (3); only the wall-resolved 2D
    projects' mesh hash changes."""
    from vortexcfd.foam.mesh_case import (CELLS_BETWEEN_LEVELS, SECTION_BUFFER_CELLS, WR_SECTION_BUFFER_CELLS,
                                          section_buffer_cells)
    from vortexcfd.workflow import meshing

    assert SECTION_BUFFER_CELLS == CELLS_BETWEEN_LEVELS == 3 and WR_SECTION_BUFFER_CELLS == 12
    assert section_buffer_cells(Mesh(layer_controls="wall_resolved", target_yplus=1.0)) == 12
    assert section_buffer_cells(Mesh(target_yplus=1.0)) == 12  # robust below y+ 5: automatic (D-123)
    assert section_buffer_cells(Mesh(target_yplus=50.0)) == 3
    assert section_buffer_cells(Mesh(layer_controls="wall_resolved", layer_sizing="relative")) == 3
    assert section_buffer_cells(Mesh(layer_controls="legacy", target_yplus=1.0)) == 3

    def top_box(mesh: Mesh) -> tuple[dict, float]:
        inp = MeshCaseInput(domain_bounds=(-10.0, 21.0, -5.0, 5.0, -10.0, 10.0), symmetric=False, parts=("wing",),
                            parts_bounds=(0.0, 1.0, -0.5, 0.5, -0.06, 0.06), reference_length=1.0, mesh=mesh,
                            part_bounds=((0.0, 1.0, -0.5, 0.5, -0.06, 0.06),), surface_length=1.0, two_d=True,
                            first_layer_thickness=FIRST, layer_count=20, layer_expansion=1.2)
        est = inp.estimate()
        snappy = snappy_hex_mesh_dict(inp).content
        return snappy["geometry"][f"section_wing_{est.level_max}"], est.base_size / 2 ** est.level_max

    for mesh, cells in ((Mesh(layer_controls="wall_resolved", target_yplus=1.0, surface_level_max=8), 12),
                        (Mesh(target_yplus=50.0, surface_level_max=8), 3)):
        box, h = top_box(mesh)
        assert box["min"][0] == pytest.approx(-cells * h) and box["max"][2] == pytest.approx(0.06 + cells * h)

    def layer_controls(mesh: Mesh, two_d: bool = True) -> dict:
        inp = MeshCaseInput(domain_bounds=(-10.0, 21.0, -5.0, 5.0, -10.0, 10.0), symmetric=False, parts=("wing",),
                            parts_bounds=(0.0, 1.0, -0.5, 0.5, -0.06, 0.06), reference_length=1.0, mesh=mesh,
                            part_bounds=((0.0, 1.0, -0.5, 0.5, -0.06, 0.06),), surface_length=1.0, two_d=two_d,
                            first_layer_thickness=FIRST, layer_count=20, layer_expansion=1.2)
        return snappy_hex_mesh_dict(inp).content["addLayersControls"]

    # D-125: the medial-axis walk is limited to 10 edges for wall-resolved 2D sections only
    assert layer_controls(Mesh(layer_controls="wall_resolved", target_yplus=1.0))["nMedialAxisIter"] == 10
    assert "nMedialAxisIter" not in layer_controls(Mesh(layer_controls="wall_resolved", target_yplus=1.0), False)
    assert "nMedialAxisIter" not in layer_controls(Mesh(target_yplus=50.0))

    project = airfoil_project(tmp_path)  # the "2D airfoil" preset: wall-resolved
    wr = meshing.inputs_hash(project)
    project.update_mesh(target_yplus=50.0, layer_controls="robust")
    robust = meshing.inputs_hash(project)
    from vortexcfd.foam import mesh_case

    keep = mesh_case.WR_SECTION_BUFFER_CELLS
    try:
        mesh_case.WR_SECTION_BUFFER_CELLS = 3  # as before D-124
        assert meshing.inputs_hash(project) == robust  # robust 2D: unchanged
        project.update_mesh(target_yplus=1.0, layer_controls="wall_resolved")
        assert meshing.inputs_hash(project) != wr  # wall-resolved 2D: the buffer is in the hash
    finally:
        mesh_case.WR_SECTION_BUFFER_CELLS = keep


def _planned_cell(case: Path, point: tuple[float, float]) -> float:
    """The planned x-z cell size at ``point`` of a 2D level case: its background cell over 2^k, k the finest
    staircase or volume box that contains the point (from blockMeshDict and snappyHexMeshDict)."""
    from vortexcfd.foam.dictfile import read_foam_file

    block = read_foam_file(case / "system" / "blockMeshDict")
    xs = [float(v[0]) for v in block["vertices"]]
    base = (max(xs) - min(xs)) / int(block["blocks"][2][0])
    snappy = read_foam_file(case / "system" / "snappyHexMeshDict")
    level = 0
    for key, region in snappy["castellatedMeshControls"]["refinementRegions"].items():
        box = snappy["geometry"].get(key, {})
        if box.get("type") != "searchableBox":
            continue
        lo, hi = box["min"], box["max"]
        if lo[0] <= point[0] <= hi[0] and lo[2] <= point[1] <= hi[2]:
            level = max(level, int(region["levelIncrement"][2][0]))
    return base / 2 ** level


def test_a_2d_study_level_is_finer_everywhere(tmp_path: Path) -> None:
    """D-127 (QUESTIONS 195): the staircase boxes are the same on every level (the buffer scales with the level),
    so the cell one chord ahead, one chord above and two chords down the wake shrinks by the study ratio from coarse
    to medium to fine, like the background and the wall."""
    from vortexcfd.workflow import mesh_study

    project = airfoil_project(tmp_path, alpha=10.0)
    study_dir, record, _ = mesh_study.prepare_study(project)
    ratio = record.ratio
    for point in ((-1.0, 0.0), (0.25, 1.0), (3.0, -0.17)):  # ahead, above, the wake 2 chords behind the TE
        sizes = [_planned_cell(study_dir / f"level_{i + 1}", point) for i in range(3)]
        assert sizes[0] / sizes[1] == pytest.approx(ratio, rel=0.02) and sizes[1] / sizes[2] == pytest.approx(ratio, rel=0.02)
    from vortexcfd.foam.dictfile import read_foam_file

    boxes = [{k: v for k, v in read_foam_file(study_dir / f"level_{i}" / "system" / "snappyHexMeshDict")["geometry"].items()
              if k.startswith("section_")} for i in (1, 2, 3)]
    assert boxes[0].keys() == boxes[1].keys() == boxes[2].keys()  # the same levels ...
    for key in boxes[2]:  # ... in the same boxes (x and z; along y each spans its own slab)
        for b in boxes[:2]:
            assert [b[key]["min"][0], b[key]["min"][2], b[key]["max"][0], b[key]["max"][2]] == pytest.approx(
                [boxes[2][key]["min"][0], boxes[2][key]["min"][2], boxes[2][key]["max"][0], boxes[2][key]["max"][2]])


def test_a_3d_study_level_gets_the_current_buffer_distances() -> None:
    """D-127: a 3D level other than the current one has distance shells around each part at the current settings'
    buffer distances and nCellsBetweenLevels 1; the current level is the single mesh's dictionary."""
    from vortexcfd.foam.mesh_case import CELLS_BETWEEN_LEVELS, STUDY_CELLS_BETWEEN_LEVELS

    def controls(scale: float) -> tuple[dict, float, int]:
        mesh = Mesh(layer_sizing="relative", surface_level_min=3, surface_level_max=4)
        inp = MeshCaseInput(domain_bounds=(-5.0, 10.0, -5.0, 5.0, -5.0, 5.0), symmetric=False, parts=("ball",),
                            parts_bounds=(-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), reference_length=1.0, mesh=mesh,
                            part_bounds=((-0.5, 0.5, -0.5, 0.5, -0.5, 0.5),), buffer_scale=scale)
        cm = snappy_hex_mesh_dict(inp).content["castellatedMeshControls"]
        return cm, inp.estimate().base_size, inp.estimate().level_max

    current, base, top = controls(1.0)
    assert "ball" not in current["refinementRegions"] and current["nCellsBetweenLevels"] == CELLS_BETWEEN_LEVELS
    # buffer_scale: the current settings' background cell over this level's; here the level's own base is
    # ``base`` (same settings), so the current base the shells use is scale x base
    coarse, _, _ = controls(0.5)
    shells = coarse["refinementRegions"]["ball"]
    assert shells["mode"] == "distance" and coarse["nCellsBetweenLevels"] == STUDY_CELLS_BETWEEN_LEVELS == 1
    expected, reach = [], 0.0
    for k in range(top, 0, -1):
        reach += 3 * 0.5 * base / 2 ** k  # 3 cells of the current settings' size of each level
        expected.append([pytest.approx(reach), k])
    assert shells["levels"] == expected



def test_the_study_places_the_current_settings_within_the_wall_resolved_limit(tmp_path: Path) -> None:
    """D-128 (QUESTIONS 199): with the wall-resolved controls the study keeps the user's "current as" when its
    coarse level stays within WR_MAX_CELL_TO_FIRST first layers, else it takes the next position that does, and its
    plan and record say so; other modes keep the user's choice."""
    from vortexcfd.foam.mesh_study import level_factors, read_record, write_record
    from vortexcfd.workflow import mesh_study

    assert level_factors(2.0, "coarse") == (1.0, 0.5, 0.25)
    project = airfoil_project(tmp_path)  # the "2D airfoil" preset: 1.307 mm cells, 147 first layers
    assert project.sim.studies.mesh.current_as == "fine"
    plan = mesh_study.plan_study(project)
    over = 2.0 * plan.levels[1].estimate.surface_size  # the coarse level as if the preset's mesh were the fine one
    assert plan.current_as == "medium" and f"({1e3 * over:.3g} mm)" in plan.current_as_note
    assert "220 first layers" in plan.current_as_note
    sizes = [lp.estimate.surface_size for lp in plan.levels]
    assert max(sizes) <= WR_MAX_CELL_TO_FIRST * FIRST * 1.000001 and sizes[1] == pytest.approx(1.31e-3, rel=0.01)
    study_dir, record, _ = mesh_study.prepare_study(project)
    assert record.current_as == "medium" and record.current_as_note == plan.current_as_note
    write_record(study_dir, record)
    assert read_record(study_dir).current_as_note == plan.current_as_note  # kept in study.json
    project.update_study("mesh", current_as="medium")  # the user's own choice fits: no note
    plan = mesh_study.plan_study(project)
    assert plan.current_as == "medium" and plan.current_as_note is None
    project.update_study("mesh", ratio=2.0)  # 2.6 mm even as the medium level: the current settings are the coarse
    plan = mesh_study.plan_study(project)
    assert plan.current_as == "coarse" and "as the medium level" in plan.current_as_note
    assert [lp.level.factor for lp in plan.levels] == [1.0, 0.5, 0.25]
    project.update_study("mesh", ratio=2.0 ** 0.5, current_as="fine")
    project.update_mesh(target_yplus=50.0, layer_controls="robust")  # wall functions: the user's choice stands
    plan = mesh_study.plan_study(project)
    assert plan.current_as == "fine" and plan.current_as_note is None


def test_the_study_node_shows_the_automatic_choice(qtbot, tmp_path: Path) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow

    project = airfoil_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.tree.setCurrentItem(w._items[("mesh_study", None)])
        p = w.properties
        assert p.ms_current.currentText() == "fine"  # the user's setting, unchanged
        assert p.ms_current_used.text() == "medium (automatic)"
        assert "wall-resolved limit" in p.ms_current_used.toolTip()
    finally:
        w.project.save = lambda *a, **k: None
        w.close()
