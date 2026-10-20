"""User refinement volumes (D-103): model, project edits, sizing, dictionaries, estimate, domain check,
wake helper, migration and presets. No OpenFOAM run, except the one ``slow`` test at the end."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from vortexcfd.core.model import (
    CURRENT_SCHEMA_VERSION,
    BoxShape,
    ConeShape,
    CylinderShape,
    Part,
    RefinementVolume,
    Simulation,
    SphereShape,
)
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset, preset_from_simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation, migrate
from vortexcfd.foam.mesh_case import (
    INSIDE_DISTANCE,
    VOLUME_PREFIX,
    VolumeEntry,
    searchable_geometry,
    snappy_hex_mesh_dict,
)
from vortexcfd.foam.mesh_estimate import MAX_BACKGROUND_CELLS, volume_extra_cells, volume_level
from vortexcfd.geometry import refinement_volumes as rv
from vortexcfd.geometry.domain import compute_domain
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow import meshing, refinement

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def sphere_project(tmp_path: Path, **inflow) -> Project:
    """A 1 m sphere at the origin in the default box domain (base size about 0.2686 m, levels 4-5)."""
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("p")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
    if inflow:
        project.update_inflow(**inflow)
    project.update_reports(reference_length=1.0)
    project.save(folder / "p.json")
    return project


def box_volume(name: str = "box", size: float = 0.05, **shape) -> RefinementVolume:
    return RefinementVolume(id="x", name=name, shape=BoxShape(**{"centre": (1.5, 0, 0), "size": (1, 1, 1), **shape}),
                            target_size=size)


# -- model and project edits ----------------------------------------------------------------------


def test_model_validates_shapes_and_unique_names() -> None:
    with pytest.raises(ValueError):
        BoxShape(size=(1, 0, 1))
    with pytest.raises(ValueError):
        CylinderShape(point1=(0, 0, 0), point2=(0, 0, 0))
    with pytest.raises(ValueError):
        ConeShape(radius1=0, radius2=0)
    with pytest.raises(ValueError):
        RefinementVolume(id="a", name="bad name", shape=SphereShape(), target_size=0.1)
    with pytest.raises(ValueError):
        Simulation(name="s", refinement_volumes=[box_volume("A"), box_volume("a").model_copy(update={"id": "y"})])
    v = RefinementVolume.model_validate({"id": "a", "name": "w", "shape": {"kind": "cone"}, "target_size": 0.1})
    assert isinstance(v.shape, ConeShape) and v.enabled


def test_add_duplicate_edit_delete_are_undoable_steps(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    vid = project.add_refinement_volume(box_volume("wake"))
    assert [v.name for v in project.sim.refinement_volumes] == ["wake"] and project.undo_label.startswith("Add")
    dup = project.duplicate_refinement_volume(vid)
    assert [v.name for v in project.sim.refinement_volumes] == ["wake", "wake_2"] and dup != vid
    project.update_refinement_volume(dup, name="near", target_size=0.02, shape={"yaw_deg": 30.0})
    near = project.volume(dup)
    assert near.name == "near" and near.target_size == 0.02 and near.shape.yaw_deg == 30.0
    assert near.shape.size == (1.0, 1.0, 1.0)  # the other shape fields are kept
    project.update_refinement_volume(dup, enabled=False)
    assert not project.volume(dup).enabled
    with pytest.raises(ValueError):
        project.update_refinement_volume(dup, name="WAKE")  # names are unique ignoring case
    project.remove_refinement_volume(vid)
    assert [v.name for v in project.sim.refinement_volumes] == ["near"]
    for _ in range(3):  # remove, disable, rename
        assert project.undo()
    assert [v.name for v in project.sim.refinement_volumes] == ["wake", "wake_2"]
    assert project.redo() and project.volume(dup).name == "near"


def test_enabled_volume_edits_put_the_mesh_out_of_date(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    before = meshing.inputs_hash(project)
    vid = project.add_refinement_volume(box_volume())
    added = meshing.inputs_hash(project)
    assert added != before
    project.update_refinement_volume(vid, target_size=0.04)
    edited = meshing.inputs_hash(project)
    assert edited not in (before, added)
    project.remove_refinement_volume(vid)
    assert meshing.inputs_hash(project) == before  # no volumes: the hash of a project made before v12


def test_a_disabled_volume_leaves_the_mesh_current_until_it_is_enabled(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    before = meshing.inputs_hash(project)
    vid = project.add_refinement_volume(box_volume().model_copy(update={"enabled": False}))
    assert meshing.inputs_hash(project) == before  # adding a disabled volume
    project.update_refinement_volume(vid, target_size=0.02, shape={"centre": (2.0, 0.0, 0.0)}, name="later")
    assert meshing.inputs_hash(project) == before  # editing a disabled volume
    project.update_refinement_volume(vid, enabled=True)
    enabled = meshing.inputs_hash(project)
    assert enabled != before  # enabling it marks the mesh out of date
    project.update_refinement_volume(vid, enabled=False)
    assert meshing.inputs_hash(project) == before  # and disabling it again


# -- sizing ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("target, level", [(1.0, 0), (0.5, 1), (0.49, 2), (0.25, 2), (0.26, 2), (0.124, 4)])
def test_level_rounds_towards_the_finer_level(target: float, level: int) -> None:
    assert volume_level(1.0, target) == level


def test_info_shows_level_achieved_size_and_finer_warning(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    box, _names, _ = meshing.loaded_parts(project)
    est = meshing.project_estimate(project, box)
    finest = refinement.finest_part_level(project, est)
    assert finest == est.level_max == 5
    coarse = refinement.volume_info(box_volume(size=0.05), box, est, finest)
    assert coarse.level == volume_level(est.base_size, 0.05) == 3
    assert coarse.achieved_size == pytest.approx(est.base_size / 8) and coarse.achieved_size <= 0.05
    assert coarse.status == "inside" and coarse.messages == ()
    fine = refinement.volume_info(box_volume(size=0.002), box, est, finest)
    assert fine.level == volume_level(est.base_size, 0.002) > finest and any("finer than the finest part surface level (level 5" in m for m in fine.messages)


# -- dictionaries ---------------------------------------------------------------------------------


def test_searchable_shapes_and_keywords() -> None:
    assert searchable_geometry(BoxShape(centre=(1, 2, 3), size=(2, 4, 6))) == {
        "type": "searchableBox", "min": [0.0, 0.0, 0.0], "max": [2.0, 4.0, 6.0]}
    assert searchable_geometry(CylinderShape(point1=(0, 0, 0), point2=(2, 0, 0), radius=0.5)) == {
        "type": "searchableCylinder", "point1": [0.0, 0.0, 0.0], "point2": [2.0, 0.0, 0.0], "radius": 0.5}
    assert searchable_geometry(SphereShape(centre=(1, 0, 0), radius=2)) == {
        "type": "searchableSphere", "centre": [1.0, 0.0, 0.0], "radius": 2.0}
    assert searchable_geometry(ConeShape(point1=(0, 0, 0), point2=(3, 0, 0), radius1=0.5, radius2=1.0)) == {
        "type": "searchableCone", "point1": [0.0, 0.0, 0.0], "radius1": 0.5, "innerRadius1": 0.0,
        "point2": [3.0, 0.0, 0.0], "radius2": 1.0, "innerRadius2": 0.0}


def _written_corners(g: dict) -> np.ndarray:
    """The corners of a searchableRotatedBox as v2606 builds it: the local box (0 0 0)-(span) placed at
    origin with the local axes e1, e2 = e3 x e1, e3 (searchableRotatedBox.C)."""
    e1, e3 = np.array(g["e1"]), np.array(g["e3"])
    e2 = np.cross(e3, e1)
    span = g["span"]
    local = np.array([(i, j, k) for i in (0, span[0]) for j in (0, span[1]) for k in (0, span[2])], dtype=float)
    return np.array(g["origin"]) + local @ np.vstack([e1, e2, e3])


def test_unrotated_box_stays_a_plain_searchable_box() -> None:
    assert searchable_geometry(BoxShape(centre=(1, 2, 3), size=(2, 4, 6), pitch_deg=0.0, yaw_deg=360.0))["type"] == \
        "searchableBox"


@pytest.mark.parametrize("pitch, yaw, e1, e3", [
    (0.0, 90.0, (0, 1, 0), (0, 0, 1)),  # yawed: e1 turns from +x to +y, e3 stays z
    (30.0, 0.0, (math.cos(math.radians(30)), 0, math.sin(math.radians(30))),
     (-math.sin(math.radians(30)), 0, math.cos(math.radians(30)))),  # pitched nose-up: e1 towards +z
    (10.0, 45.0, (math.cos(math.radians(10)) * math.sqrt(0.5), math.cos(math.radians(10)) * math.sqrt(0.5),
                  math.sin(math.radians(10))),
     (-math.sin(math.radians(10)) * math.sqrt(0.5), -math.sin(math.radians(10)) * math.sqrt(0.5),
      math.cos(math.radians(10)))),
])
def test_pitched_and_yawed_boxes_are_searchable_rotated_boxes(pitch, yaw, e1, e3) -> None:
    shape = BoxShape(centre=(1, 1, 0), size=(2, 1, 4), pitch_deg=pitch, yaw_deg=yaw)
    g = searchable_geometry(shape)
    assert g["type"] == "searchableRotatedBox" and g["span"] == [2.0, 1.0, 4.0]
    assert g["e1"] == pytest.approx(e1, abs=1e-12) and g["e3"] == pytest.approx(e3, abs=1e-12)
    assert np.dot(g["e1"], g["e3"]) == pytest.approx(0.0, abs=1e-12)
    corners = _written_corners(g)
    assert np.allclose(np.sort(corners, axis=0), np.sort(rv.box_corners(shape), axis=0))
    assert np.allclose(corners.mean(axis=0), shape.centre)
    # the long edge (2 m) runs along e1
    assert np.linalg.norm(corners[4] - corners[0]) == pytest.approx(2.0)
    assert (corners[4] - corners[0]) / 2.0 == pytest.approx(e1, abs=1e-12)
    inside = rv.contains(shape, [shape.centre, np.array(shape.centre) + 0.99 * np.array(e1),
                                 np.array(shape.centre) + 1.01 * np.array(e1)])
    assert inside.tolist() == [True, True, False]


def test_snappy_dict_has_one_geometry_and_one_inside_region_per_volume(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    project.add_refinement_volume(box_volume("near", size=0.05))
    project.add_refinement_volume(RefinementVolume(id="x", name="ball", shape=SphereShape(centre=(0, 0, 0), radius=1.5),
                                                   target_size=0.1))
    off = project.add_refinement_volume(box_volume("off", size=0.05))
    project.update_refinement_volume(off, enabled=False)
    project.add_refinement_volume(box_volume("far", centre=(500, 0, 0)))  # wholly outside: not written
    inputs, _box, _ = meshing.mesh_inputs(project)
    est = inputs.estimate()
    assert [v.name for v in inputs.volumes] == ["near", "ball"]
    d = snappy_hex_mesh_dict(inputs).content
    geometry = d["geometry"]
    assert geometry[f"{VOLUME_PREFIX}near"]["type"] == "searchableBox"
    assert geometry[f"{VOLUME_PREFIX}ball"]["type"] == "searchableSphere"
    assert f"{VOLUME_PREFIX}off" not in geometry and f"{VOLUME_PREFIX}far" not in geometry
    regions = d["castellatedMeshControls"]["refinementRegions"]
    assert regions == {
        f"{VOLUME_PREFIX}near": {"mode": "inside", "levels": [[INSIDE_DISTANCE, volume_level(est.base_size, 0.05)]]},
        f"{VOLUME_PREFIX}ball": {"mode": "inside", "levels": [[INSIDE_DISTANCE, volume_level(est.base_size, 0.1)]]},
    }
    assert "Ball.stl" in geometry  # the part is still there
    from vortexcfd.foam.mesh_estimate import CELLS_BETWEEN_LEVELS

    assert d["castellatedMeshControls"]["nCellsBetweenLevels"] == CELLS_BETWEEN_LEVELS  # the estimate's buffer


def test_dict_without_volumes_is_unchanged(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    inputs, _, _ = meshing.mesh_inputs(project)
    assert inputs.volumes == ()
    assert snappy_hex_mesh_dict(inputs).content["castellatedMeshControls"]["refinementRegions"] == {}


# -- estimate and domain check --------------------------------------------------------------------


def test_estimate_with_and_without_volumes(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    box, _, _ = meshing.loaded_parts(project)
    plain = meshing.estimate_with_volumes(project, box)
    assert plain.volume_cells == 0 and plain.budget_cells == plain.total_cells
    project.add_refinement_volume(box_volume(size=0.05))  # 1 m3, level 3
    est = meshing.estimate_with_volumes(project, box)
    h = est.base_size / 8
    edge = 1.0 + 2 * 3 * 3 * h  # grown by 3 cells per level step, 3 steps
    expected = volume_extra_cells(edge ** 3, est.base_size, 3)
    assert expected == round(edge ** 3 * (8 ** 3 - 1) / est.base_size ** 3)
    assert est.volume_cells == expected and est.budget_cells == est.total_cells + expected
    assert est.total_cells == plain.total_cells and meshing.readiness(project) is None
    project.add_refinement_volume(box_volume("huge", size=0.004))
    est = meshing.estimate_with_volumes(project, box)
    assert est.budget_cells > MAX_BACKGROUND_CELLS
    reason = meshing.readiness(project)
    assert reason is not None and "refinement volumes" in reason
    assert "counted twice" in refinement.OVERLAP_NOTE


def test_level_buffer_grows_the_volume_before_its_cells_are_counted() -> None:
    """Hand calculation: base 1 m, a 1 m box with a 0.25 m target -> level 2 (0.25 m cells); grown by
    nCellsBetweenLevels (3) cells x 2 level steps x 0.25 m = 1.5 m on every side -> a 4 m box, 64 m3;
    extra cells = 64 x (8^2 - 1) / 1^3 = 4032 (the ungrown box would give 63)."""
    from vortexcfd.core.model import Domain, Mesh
    from vortexcfd.foam.mesh_estimate import CELLS_BETWEEN_LEVELS, estimate_mesh, volume_buffer

    assert CELLS_BETWEEN_LEVELS == 3
    domain = compute_domain([(0.0, 1.0, 0.0, 1.0, 0.0, 1.0)], Domain())  # x -5..11, y and z -5..6
    est = estimate_mesh(domain.bounds, 1.0, Mesh(base_size=1.0))
    volume = RefinementVolume(id="x", name="b", shape=BoxShape(centre=(5.0, 0.5, 0.5), size=(1, 1, 1)), target_size=0.25)
    info = refinement.volume_info(volume, domain, est, finest=5)
    assert (info.level, info.achieved_size, info.buffer) == (2, 0.25, 1.5) == (2, 0.25, volume_buffer(2, 0.25))
    assert info.extra_cells == 4032
    assert rv.grow(volume.shape, 1.5).size == (4.0, 4.0, 4.0)
    sphere = rv.grow(SphereShape(radius=1.0), 0.5)
    assert sphere.radius == 1.5
    cone = rv.grow(ConeShape(point1=(0, 0, 0), point2=(2, 0, 0), radius1=0.5, radius2=1.0), 0.5)
    assert (cone.point1, cone.point2, cone.radius1, cone.radius2) == ((-0.5, 0.0, 0.0), (2.5, 0.0, 0.0), 1.0, 1.5)
    assert rv.grow(volume.shape, 0.0) is volume.shape


def test_outside_and_partly_outside_volumes(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    box, _, _ = meshing.loaded_parts(project)
    est = meshing.project_estimate(project, box)
    b = box.bounds
    outside = refinement.volume_info(box_volume(centre=(b[1] + 10, 0, 0)), box, est, 5)
    assert outside.status == "outside" and outside.ignored and not outside.written and outside.extra_cells == 0
    assert outside.messages == ("Ignored: outside the domain",)
    half = refinement.volume_info(box_volume(centre=(b[1], 0, 0), size=0.1), box, est, 5)  # half beyond x_max
    assert half.status == "partial" and half.written and half.fraction == pytest.approx(0.5, abs=0.03)
    assert any("lies outside the domain" in m for m in half.messages)
    full = refinement.volume_info(box_volume(size=0.1), box, est, 5)
    assert full.extra_cells == pytest.approx(2 * half.extra_cells, rel=0.07)
    assert refinement.volume_entries([outside, half, full]) == (
        VolumeEntry("box", half.volume.shape, half.level), VolumeEntry("box", full.volume.shape, full.level))


def test_domain_fraction_in_a_rounded_domain_matches_the_domain_test() -> None:
    from vortexcfd.core.model import Domain

    box = compute_domain([(0, 1, 0, 1, 0, 1)], Domain(shape="bullet", radius=3.0))
    pts = np.random.default_rng(0).uniform(-6, 16, size=(2000, 3))
    assert np.array_equal(rv.inside_domain(box, pts), np.array([box.contains(p) for p in pts]))
    sphere = SphereShape(centre=tuple(box.axis), radius=0.5)
    assert rv.domain_fraction(sphere, box) == 1.0


def test_shape_volumes_and_containment() -> None:
    cone = ConeShape(point1=(0, 0, 0), point2=(2, 0, 0), radius1=0.5, radius2=1.0)
    assert rv.volume(cone) == pytest.approx(math.pi * 2 / 3 * (0.25 + 0.5 + 1.0))
    assert rv.contains(cone, [(1, 0, 0.74), (1, 0, 0.76), (-0.1, 0, 0)]).tolist() == [True, False, False]
    rot = BoxShape(centre=(0, 0, 0), size=(2, 0.2, 1), yaw_deg=90)
    assert rv.contains(rot, [(0, 0.9, 0), (0.9, 0, 0)]).tolist() == [True, False]
    assert rv.bounds(rot) == pytest.approx((-0.1, 0.1, -1, 1, -0.5, 0.5))
    for shape in (rot, cone, CylinderShape(), SphereShape()):
        assert rv.outline(shape).n_cells > 0


# -- wake helper ----------------------------------------------------------------------------------


WING = (0.0, 10.0, -5.0, 5.0, -1.2, 1.2)  # a wing-like part: 10 x 10 x 2.4 m (wide and flat), L = 10 m


def test_wake_box_for_a_wing_like_part_along_the_free_stream() -> None:
    box, target = rv.wake_box(WING, 0.0, 0.05)
    assert box.size == pytest.approx((20.0, 11.0, 4.8))  # 2 L long, 1.1 x the span, 2 x the thickness
    assert box.centre == pytest.approx((20.0, 0.0, 0.0))  # from the rear (x = 10) downstream
    assert (box.pitch_deg, box.yaw_deg) == (0.0, 0.0) and target == pytest.approx(0.1)
    assert searchable_geometry(box) == {"type": "searchableBox", "min": [10.0, -5.5, -2.4], "max": [30.0, 5.5, 2.4]}


def test_wake_box_is_pitched_by_the_angle_of_attack() -> None:
    a = math.radians(6.0)
    box, _ = rv.wake_box(WING, 6.0, 0.05)
    assert box.pitch_deg == 6.0 and box.size == pytest.approx((20.0, 11.0, 4.8))
    e1 = np.array(box.axes()[0])
    assert e1 == pytest.approx((math.cos(a), 0.0, math.sin(a)))  # along the free stream
    upstream_face = np.array(box.centre) - 10.0 * e1
    assert upstream_face == pytest.approx((10.0, 0.0, 5.0 * math.tan(a)))  # the line through the centre leaves at x = 10
    g = searchable_geometry(box)
    assert g["type"] == "searchableRotatedBox" and g["span"] == pytest.approx([20.0, 11.0, 4.8])
    assert rv.contains(box, [upstream_face + 0.5 * e1, upstream_face - 0.5 * e1]).tolist() == [True, False]


def test_wake_volume_uses_the_inflow_angle_and_the_part_surface_size(tmp_path: Path) -> None:
    project = sphere_project(tmp_path, alpha_deg=4.0)
    box, _names, meshes = meshing.loaded_parts(project)
    est = meshing.project_estimate(project, box)
    bounds = [tuple(float(x) for x in m.bounds) for m in meshes]
    wake = refinement.wake_volume(project, [0], bounds, est)
    assert wake.name == "wake" and isinstance(wake.shape, BoxShape) and wake.shape.pitch_deg == 4.0
    assert wake.target_size == pytest.approx(2 * est.surface_size)
    b = bounds[0]
    length = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])  # L: the largest extent
    assert wake.shape.size == pytest.approx((2 * length, 1.1 * (b[3] - b[2]), 2 * (b[5] - b[4])), rel=1e-6)
    project.add_refinement_volume(wake)
    project.update_refinement_volume(project.sim.refinement_volumes[0].id, shape={"pitch_deg": 0.0}, target_size=0.1)
    assert project.sim.refinement_volumes[0].shape.pitch_deg == 0.0  # editable afterwards
    cone = ConeShape(point1=(1, 0, 0), point2=(3, 0, 0), radius1=0.2, radius2=0.4)  # still a shape of its own
    assert searchable_geometry(cone)["type"] == "searchableCone"


# -- migration and presets ------------------------------------------------------------------------


def test_v11_project_migrates_without_volumes() -> None:
    stored = json.loads((DATA / "project_v11.json").read_text())
    assert stored["schema_version"] == 11 and "refinement_volumes" not in stored
    sim = load_simulation(DATA / "project_v11.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 12 and sim.refinement_volumes == []
    assert sim.inflow.alpha_deg == 4.0 and [p.name for p in sim.geometry.parts] == ["Body"]
    assert migrate({"schema_version": 11, "x": 1}) == {"schema_version": 12, "x": 1}


def test_volumes_round_trip_and_are_not_saved_in_presets(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    project.add_refinement_volume(box_volume(pitch_deg=5.0, yaw_deg=15.0))
    project.save()
    sim = load_simulation(project.path)
    assert sim.refinement_volumes == project.sim.refinement_volumes
    preset = preset_from_simulation(sim, "Mine")
    assert "refinement_volumes" not in preset.model_dump_json() and "box" not in json.loads(preset.model_dump_json())
    applied = apply_preset(sim, BUILTIN_PRESETS[0])
    assert applied.refinement_volumes == sim.refinement_volumes  # geometry-specific: kept with the project
    assert apply_preset(Simulation(name="new"), preset).refinement_volumes == []


# -- real mesh (not run by agents: the owner runs it through scripts/ship.sh) ------------------------


@pytest.mark.slow
def test_a_box_volume_behind_a_sphere_is_meshed_at_its_level(tmp_path: Path) -> None:
    """A sphere with a box volume behind it, meshed for real: the cells well inside the box are at the
    volume's level (their volume is that level's cube) and checkMesh passes."""
    from vortexcfd.foam.mesh_run import MeshRun

    project = sphere_project(tmp_path)
    project.update_mesh(layer_sizing="relative", layers=0, background_cells_target=20_000)
    shape = BoxShape(centre=(1.5, 0.0, 0.0), size=(1.6, 1.0, 1.0))
    project.add_refinement_volume(RefinementVolume(id="x", name="behind", shape=shape, target_size=0.1))
    job = meshing.prepare_job(project)
    level = job.inputs.volumes[0].level
    base = job.inputs.estimate().base_size
    run = MeshRun(job.case_dir, parts=job.inputs.patches, step_timeout_s=600)
    run.start()
    result = run.wait(900)
    assert result is not None and result.success and result.report.valid and result.report.mesh_ok
    reader = pv.OpenFOAMReader(str(job.case_dir / "case.foam"))
    reader.enable_all_cell_arrays()
    internal = reader.read()["internalMesh"].compute_cell_sizes(length=False, area=False, volume=True)
    centres = np.asarray(internal.cell_centers().points)
    margin = 2 * base / 2 ** level
    inner = BoxShape(centre=shape.centre, size=tuple(s - 2 * margin for s in shape.size))
    inside = rv.contains(inner, centres)
    assert inside.sum() > 100
    expected = (base / 2 ** level) ** 3
    assert np.asarray(internal.cell_data["Volume"])[inside] == pytest.approx(expected, rel=0.02)
