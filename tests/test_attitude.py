"""The angle of attack as a rotation of the geometry (D-120): the rotation sign, points and normals, body- and
wind-frame refinement volumes, the ground and domain errors, the meshing case, the forces in wind axes on a
rotated case (dictionaries and post-processing) and the v17 -> v18 migration."""

import json
import math
from pathlib import Path

import numpy as np
import pyvista as pv
import pytest

from tests.test_refinement_volumes import sphere_project
from vortexcfd.core.model import BoxShape, CylinderShape, Part, RefinementVolume
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation, migrate
from vortexcfd.foam.mesh_case import TRI_SURFACE, searchable_geometry
from vortexcfd.geometry import refinement_volumes as rv
from vortexcfd.geometry.attitude import Attitude, body_axes, rotate_points, rotate_shape, rotate_surface, rotation_matrix
from vortexcfd.workflow import meshing

DATA = Path(__file__).parent / "data"


# -- the rotation ------------------------------------------------------------------------------------


def naca0012(n: int = 61) -> np.ndarray:
    """The upper and lower surface of a NACA 0012 of chord 1, leading edge at x = 0, in the x-z plane."""
    x = 0.5 * (1 - np.cos(np.linspace(0, math.pi, n)))
    t = 0.6 * (0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1036 * x ** 4)
    upper = np.column_stack([x, np.zeros(n), t])
    lower = np.column_stack([x[::-1], np.zeros(n), -t[::-1]])
    return np.vstack([upper, lower[1:]])


def test_positive_alpha_is_nose_up() -> None:
    """A positive angle of attack lifts the leading edge above the trailing edge (the free stream is +x, lift
    +z: a symmetric airfoil then gets a positive lift); the quarter-chord centre stays put."""
    section = naca0012()
    centre = (0.25, 0.0, 0.0)
    for alpha in (5.0, 10.0, 15.0):
        p = rotate_points(section, alpha, centre)
        le, te = p[0], p[len(section) // 2]
        assert le[2] > te[2]
        assert math.degrees(math.atan2(le[2] - te[2], te[0] - le[0])) == pytest.approx(alpha)
        assert rotate_points([centre], alpha, centre)[0] == pytest.approx(centre)
    p = rotate_points(section, -5.0, centre)
    assert p[0][2] < p[len(section) // 2][2]  # negative: nose down
    assert rotation_matrix(10.0) @ np.array([1.0, 0.0, 0.0]) == pytest.approx(
        [math.cos(math.radians(10)), 0.0, -math.sin(math.radians(10))])
    assert body_axes(10.0)[1] == pytest.approx((math.sin(math.radians(10)), 0.0, math.cos(math.radians(10))))


def test_points_and_normals_turn_and_the_cached_surface_does_not() -> None:
    mesh = pv.Box(bounds=(0.0, 2.0, -0.5, 0.5, -0.1, 0.1)).triangulate().clean()
    mesh = mesh.compute_normals(cell_normals=True, point_normals=True, auto_orient_normals=True)
    before = np.asarray(mesh.points).copy()
    centre = (1.0, 0.0, 0.0)
    turned = rotate_surface(mesh, 12.0, centre)
    assert np.asarray(mesh.points) == pytest.approx(before)  # the original is untouched
    rot = rotation_matrix(12.0)
    assert np.asarray(turned.points) == pytest.approx((before - centre) @ rot.T + centre)
    assert np.asarray(turned.cell_data["Normals"]) == pytest.approx(np.asarray(mesh.cell_data["Normals"]) @ rot.T, abs=1e-6)
    assert np.asarray(turned.point_data["Normals"]) == pytest.approx(np.asarray(mesh.point_data["Normals"]) @ rot.T,
                                                                     abs=1e-6)
    recomputed = turned.compute_normals(cell_normals=True, point_normals=False, auto_orient_normals=False,
                                        consistent_normals=False)
    assert np.asarray(recomputed.cell_data["Normals"]) == pytest.approx(
        np.asarray(mesh.cell_data["Normals"]) @ rot.T, abs=1e-6)  # the face orientation is kept
    assert turned.volume == pytest.approx(mesh.volume)


def test_rotated_shapes() -> None:
    centre = (0.0, 0.0, 0.0)
    box = BoxShape(centre=(2.0, 0.0, 0.0), size=(2.0, 1.0, 0.5), pitch_deg=4.0, yaw_deg=20.0)
    turned = rotate_shape(box, 10.0, centre)
    e = [np.array(v) for v in box.axes()]
    for a, b in zip(turned.axes(), e):
        assert np.array(a) == pytest.approx(rotation_matrix(10.0) @ b)
    assert rv.box_corners(turned) == pytest.approx(rotate_points(rv.box_corners(box), 10.0, centre))
    g = searchable_geometry(turned)
    assert g["type"] == "searchableRotatedBox" and g["e1"] == pytest.approx(list(turned.axes()[0]))
    grown = rv.grow(turned, 0.1)
    assert grown.axes() == turned.axes() and grown.size == pytest.approx((2.2, 1.2, 0.7))
    cyl = rotate_shape(CylinderShape(point1=(1, 0, 0), point2=(3, 0, 0), radius=0.2), 90.0, centre)
    assert cyl.point1 == pytest.approx((0.0, 0.0, -1.0)) and cyl.point2 == pytest.approx((0.0, 0.0, -3.0))
    assert rotate_shape(box, 0.0, centre) is box


# -- meshing -----------------------------------------------------------------------------------------


def _wing(tmp_path: Path, alpha: float = 0.0, **domain) -> Project:
    """A flat 2 x 4 x 0.2 m plate-wing from x = 0 in the default box domain."""
    folder = tmp_path / "wing"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    pv.Box(bounds=(0.0, 2.0, -2.0, 2.0, -0.1, 0.1)).triangulate().save(str(folder / "geometry" / "wing.stl"))
    project = Project.new("w")
    project.add_part(Part(name="Wing", source_file="geometry/wing.stl", units="m"))
    project.update_inflow(alpha_deg=alpha)
    if domain:
        project.update_domain(**domain)
    project.save(folder / "w.json")
    return project


def test_the_domain_is_sized_around_the_rotated_parts_and_the_reference_values_are_not(tmp_path: Path) -> None:
    flat = _wing(tmp_path / "a")
    turned = _wing(tmp_path / "b", 20.0)
    box0, _n, _m = meshing.loaded_parts(flat)
    box20, _n, meshes = meshing.loaded_parts(turned)
    b = meshes[0].bounds
    a = math.radians(20.0)
    assert b[5] - b[4] == pytest.approx(2.0 * math.sin(a) + 0.2 * math.cos(a), rel=1e-6)  # rotated about (1, 0, 0)
    assert box20.parts_bounds == pytest.approx(tuple(b))
    assert box20.bounds[5] - box20.bounds[4] > box0.bounds[5] - box0.bounds[4]
    assert meshing.body_bounds(turned) == pytest.approx((0.0, 2.0, -2.0, 2.0, -0.1, 0.1))
    _box, _names, ref_bounds = meshing.parts_layout(turned)
    assert ref_bounds == pytest.approx((0.0, 2.0, -2.0, 2.0, -0.1, 0.1))  # A_ref, l_ref, CofR: as imported
    assert meshing.readiness(turned) is None


def test_the_meshing_case_gets_the_rotated_surface(tmp_path: Path) -> None:
    project = _wing(tmp_path, 10.0)
    job = meshing.prepare_job(project)
    written = pv.read(str(job.case_dir / TRI_SURFACE / "Wing.stl"))
    body = pv.read(str(project.resolve_part_path(project.sim.geometry.parts[0])))
    assert np.asarray(written.points).min(axis=0) == pytest.approx(
        rotate_points(body.points, 10.0, (1.0, 0.0, 0.0)).min(axis=0), abs=1e-6)
    assert job.inputs.parts_bounds == pytest.approx(tuple(written.bounds), abs=1e-6)
    stored = pv.read(str(project.resolve_part_path(project.sim.geometry.parts[0])))
    assert np.asarray(stored.points) == pytest.approx(np.asarray(body.points))  # the project's file unchanged


def test_body_volumes_turn_and_wind_volumes_do_not(tmp_path: Path) -> None:
    project = _wing(tmp_path, 10.0)
    near = RefinementVolume(id="v1", name="near", shape=BoxShape(centre=(1.0, 0.0, 0.0), size=(3.0, 5.0, 0.6)),
                            target_size=0.2)
    wake = RefinementVolume(id="v2", name="wake", shape=BoxShape(centre=(5.0, 0.0, 0.0), size=(6.0, 5.0, 1.0)),
                            target_size=0.3, frame="wind")
    project.add_refinement_volume(near)
    project.add_refinement_volume(wake)
    inputs, _box, _meshes = meshing.mesh_inputs(project)
    entries = {v.name: v for v in inputs.volumes}
    e1 = entries["near"].shape.axes()[0]
    assert e1 == pytest.approx((math.cos(math.radians(10)), 0.0, -math.sin(math.radians(10))))
    assert searchable_geometry(entries["near"].shape)["type"] == "searchableRotatedBox"
    assert entries["wake"].shape == wake.shape  # wind frame: as stored
    assert searchable_geometry(entries["wake"].shape)["type"] == "searchableBox"
    assert project.sim.refinement_volumes[0].shape == near.shape  # the stored volume is unchanged


def test_a_rotated_part_crossing_the_ground_or_leaving_the_domain_is_an_error(tmp_path: Path) -> None:
    project = _wing(tmp_path, 0.0, ground={"enabled": True})
    assert meshing.readiness(project) is None  # at 0 degrees the plate rests on the ground
    project.update_inflow(alpha_deg=10.0)
    reason = meshing.readiness(project)
    assert reason is not None and "crosses the ground plane" in reason and "10 deg" in reason
    lifted = _wing(tmp_path / "lifted", 10.0, ground={"enabled": True, "position": "value", "z": -1.0})
    assert meshing.readiness(lifted) is None  # the ground below the rotated plate
    # a second part the domain is not sized around, outside a rounded domain once rotated
    folder = tmp_path / "two"
    (folder / "geometry").mkdir(parents=True)
    pv.Box(bounds=(0.0, 2.0, -2.0, 2.0, -0.1, 0.1)).triangulate().save(str(folder / "geometry" / "wing.stl"))
    pv.Box(bounds=(-1.5, 1.5, -0.1, 0.1, 6.0, 6.5)).triangulate().save(str(folder / "geometry" / "far.stl"))
    two = Project.new("t")
    two.add_part(Part(name="Wing", source_file="geometry/wing.stl", units="m"))
    two.add_part(Part(name="Far", source_file="geometry/far.stl", units="m"))
    two.update_domain(parts=["Wing"], shape="c_type", radius=1.0, downstream=1.0, lateral=1.0)
    two.save(folder / "t.json")
    two.update_inflow(alpha_deg=60.0)
    reason = meshing.readiness(two)
    assert reason is not None and "leaves the domain" in reason and "'Far'" in reason


def test_the_mesh_hash_carries_the_angle_and_the_volume_frames_only_when_rotated(tmp_path: Path) -> None:
    project = _wing(tmp_path)
    volume = RefinementVolume(id="v1", name="near", shape=BoxShape(centre=(1.0, 0.0, 0.0), size=(3.0, 5.0, 0.6)),
                              target_size=0.2)
    project.add_refinement_volume(volume)
    flat = meshing.inputs_hash(project)
    project.update_refinement_volume("v1", frame="wind")
    assert meshing.inputs_hash(project) == flat  # at 0 degrees the frame changes nothing
    project.update_inflow(alpha_deg=5.0)
    wind = meshing.inputs_hash(project)
    assert wind != flat
    project.update_refinement_volume("v1", frame="body")
    assert meshing.inputs_hash(project) != wind
    project.update_reports(center_of_rotation=(0.5, 0.0, 0.0))
    assert meshing.inputs_hash(project) not in (wind, flat)  # the rotation centre moves the parts


# -- forces in wind axes -----------------------------------------------------------------------------


def _coefficient_header(drag, lift, cofr, area=2.0, length=1.0, speed=10.0) -> str:
    def vec(v):
        return "(" + " ".join(f"{x:.12g}" for x in v) + ")"

    return (f"# Force and moment coefficients\n# dragDir     : {vec(drag)}\n# sideDir     : (0 1 0)\n"
            f"# liftDir     : {vec(lift)}\n# rollAxis    : (1 0 0)\n# pitchAxis   : (0 1 0)\n# yawAxis     : (0 0 1)\n"
            f"# magUInf     : {speed}\n# lRef        : {length}\n# Aref        : {area}\n# CofR        : {vec(cofr)}\n"
            "# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\tCs\tCs(f)\tCs(r)\n")


def test_forces_in_wind_and_body_axes_on_a_rotated_case(tmp_path: Path) -> None:
    """A case at alpha 10 (as the app writes it): forceCoeffs1 in the wind axes, forceCoeffsBody in the body axes.
    A known force F = (0.02, 0, 0.9) q A (wind axes: Cd 0.02, Cl 0.9) and pitching moment give C_A, C_N and
    x_cp along the body x axis."""
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.core.model import Inflow, Physics, Solvers
    from vortexcfd.foam.postprocessing import ReportMonitor

    alpha, cofr, rho, speed, area, length = 10.0, (0.25, 0.0, 0.0), 1.225, 10.0, 2.0, 1.0
    inp = SolverCaseInput(Physics(rho_ref=rho), Inflow(speed=speed, alpha_deg=alpha), Solvers(), ("Wing",),
                          (0.0, 1.0, -1.0, 1.0, -0.06, 0.06))
    case = tmp_path / "case"
    for rel, spec in build_solver_files(inp).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    functions = json.loads(json.dumps(__import__("vortexcfd.foam.dictfile", fromlist=["x"]).read_foam_file(
        case / "system" / "controlDict")["functions"], default=float))
    x_b, z_b = body_axes(alpha)
    assert functions["forceCoeffs1"]["dragDir"] == [1.0, 0.0, 0.0] and functions["forceCoeffs1"]["liftDir"] == [0, 0, 1]
    assert functions["forceCoeffsBody"]["dragDir"] == pytest.approx(list(x_b))
    q_a = 0.5 * rho * speed ** 2 * area
    force = np.array([0.02, 0.0, 0.9]) * q_a
    my = -0.05 * q_a * length  # nose-down moment about CofR
    pp = case / "postProcessing"
    (pp / "forceCoeffs1" / "0").mkdir(parents=True)
    (pp / "forceCoeffs1" / "0" / "coefficient.dat").write_text(
        _coefficient_header((1, 0, 0), (0, 0, 1), cofr, area, length, speed) + "1\t0.02\t0\t0\t0.9\t0\t0\t-0.05\t0\t0\t0\t0\t0\n")
    (pp / "forceCoeffsBody" / "0").mkdir(parents=True)
    (pp / "forceCoeffsBody" / "0" / "coefficient.dat").write_text(_coefficient_header(x_b, z_b, cofr, area, length, speed))
    (pp / "forces1" / "0").mkdir(parents=True)
    vec = " ".join(f"{v:.12g}" for v in force)
    (pp / "forces1" / "0" / "force.dat").write_text(f"# Time total pressure viscous\n1\t({vec})\t({vec})\t(0 0 0)\n")
    (pp / "forces1" / "0" / "moment.dat").write_text(f"# Time total pressure viscous\n1\t(0 {my:.12g} 0)\t(0 {my:.12g} 0)\t(0 0 0)\n")
    monitor = ReportMonitor(case)
    monitor.poll()
    row = monitor.breakdown_rows()[0]
    a = math.radians(alpha)
    assert row.cd == pytest.approx(0.02) and row.cl == pytest.approx(0.9)
    assert row.c_axial == pytest.approx(0.02 * math.cos(a) - 0.9 * math.sin(a))
    assert row.c_normal == pytest.approx(0.02 * math.sin(a) + 0.9 * math.cos(a))
    assert row.cm == pytest.approx(-0.05)
    assert row.x_cp == pytest.approx(0.25 + 0.05 / row.c_normal)  # behind CofR along the chord
    assert monitor.series("C_normal") == [(1.0, pytest.approx(row.c_normal))]


# -- migration ---------------------------------------------------------------------------------------


def test_v17_project_migrates_with_a_note(tmp_path: Path) -> None:
    stored = json.loads((DATA / "project_v17.json").read_text())
    assert stored["schema_version"] == 17 and stored["inflow"]["alpha_deg"] == 6.0
    assert stored["studies"]["polar"]["init_from_previous"] is True and "frame" not in stored["refinement_volumes"][0]
    notes: list[str] = []
    sim = load_simulation(DATA / "project_v17.json", notes)
    assert sim.schema_version == 24 and sim.inflow.alpha_deg == 6.0  # the angle is kept
    assert sim.refinement_volumes[0].frame == "body" and sim.refinement_volumes[0].shape.pitch_deg == 6.0
    assert len(notes) == 1 and "rotation of the parts" in notes[0] and "out of date" in notes[0]
    assert "init_from_previous" not in sim.studies.polar.model_dump()
    assert migrate({"schema_version": 17, "inflow": {"alpha_deg": 0.0}}, notes) == {
        "schema_version": 24, "inflow": {"alpha_deg": 0.0}}
    assert len(notes) == 1  # no note at 0 degrees
    path = tmp_path / "old.json"
    path.write_text((DATA / "project_v17.json").read_text())
    project = Project.open(path)
    assert len(project.migration_notes) == 1


def test_a_rotated_project_meshed_before_v18_is_out_of_date(tmp_path: Path) -> None:
    """The hash at 0 degrees has no new entry (projects at 0 keep their mesh); at another angle it carries the
    angle, so a mesh recorded before v18 (which had none) no longer matches."""
    project = sphere_project(tmp_path, alpha_deg=6.0)
    rotated = meshing.inputs_hash(project)
    project.update_inflow(alpha_deg=0.0)
    assert meshing.inputs_hash(project) != rotated
    att = Attitude(6.0, (0.0, 0.0, 0.0))
    assert att.rotated and not Attitude(0.0, (0, 0, 0)).rotated


# -- viewer ------------------------------------------------------------------------------------------


def test_the_viewer_shows_the_rotated_parts_with_a_note(qtbot, tmp_path: Path) -> None:
    """At an angle of attack the part actors carry the rotation about the CofR and the viewer says so; at 0
    degrees neither (D-120)."""
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow

    project = _wing(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=True)
    qtbot.addWidget(w)
    w.show()
    try:
        actor = w.scene.records[0].actor
        assert actor.GetUserTransform() is None and "attitude_note" not in w.viewer.actors
        w.project.update_inflow(alpha_deg=10.0)
        qtbot.waitUntil(lambda: actor.GetUserTransform() is not None, timeout=5000)
        b = actor.GetBounds()
        assert b[0] == pytest.approx(-0.00217, abs=1e-4) and b[5] == pytest.approx(0.2721, abs=2e-3)
        assert "attitude_note" in w.viewer.actors
        assert "alpha = 10" in w.viewer.actors["attitude_note"].GetText(2)
        assert pv.read(str(project.resolve_part_path(project.sim.geometry.parts[0]))).bounds[5] == pytest.approx(0.1)
        w.project.update_inflow(alpha_deg=0.0)
        qtbot.waitUntil(lambda: actor.GetUserTransform() is None, timeout=5000)
        assert "attitude_note" not in w.viewer.actors
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


# -- real runs (marker slow) ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.long
def test_a_rotated_sphere_has_the_same_drag_and_no_lift(tmp_path: Path) -> None:
    """A sphere (24 x 24 STL, radius 0.5 m) at Re 200 (0.003 m/s, steady axisymmetric wake) through the app's
    polar sweep at alpha 0 and 20 deg: each angle meshed with the sphere rotated about its centre (D-120), run
    to Cd and Cl asymptotic (window 50, 1e-4) on 4 cores. The two drags agree within 1 % and both lifts are near
    zero: the rotation changes the mesh around the body, not the flow.

        .venv/bin/pytest -m slow -s tests/test_attitude.py -k sphere
    """
    from vortexcfd.core.model import AsymptoticCriterion, StoppingCriteria
    from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR
    from vortexcfd.foam.polar_sweep import SweepRun
    from vortexcfd.workflow.polar_sweep import point_preparer, point_writer, prepare_sweep

    project = sphere_project(tmp_path, speed=0.003)
    project.update_reports(reference_area_basis="frontal")
    project.update_mesh(**V9_MESH_BEHAVIOUR, background_cells_target=60_000)
    stopping = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=50, tolerance=1e-4),
                                          AsymptoticCriterion(quantity="Cl", window=50, tolerance=1e-4)])
    project.update_solver(iterations=1500, write_interval=1500, stopping=stopping.model_dump())
    project.update_study("polar", mode="list", values=[0.0, 20.0], cores=4)
    sweep_dir, record = prepare_sweep(project, resume=False)
    run = SweepRun(sweep_dir, record, point_preparer(project), point_writer(project),
                   stopping=project.sim.solvers.stopping, parts=meshing.mesh_inputs(project)[0].patches,
                   solver_timeout_s=1200, mesh_timeout_s=600)
    run.start()
    try:
        rec = run.wait(3600)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(120)
    assert rec is not None and rec.status == "finished", rec
    for p in rec.points:
        print(f"\nalpha {p.alpha:g}: {p.cells} cells, Cd {p.cd:.6g}, Cl {p.cl:.3g}, {p.iterations} it., {p.state_label}, "
              f"mesh {p.mesh_duration_s} s, solve {p.duration_s} s")
    flat, turned = rec.points
    assert flat.state == turned.state == "criteria_met"
    assert abs(turned.cd - flat.cd) <= 0.01 * flat.cd
    assert abs(flat.cl) < 0.01 * flat.cd * 10 and abs(turned.cl) < 0.01 * flat.cd * 10  # |Cl| < 10 % of Cd
