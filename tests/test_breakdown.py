"""Force breakdown, centre of pressure, mass balance, wall shear stress / skin friction, y+
histogram and probes, from real v2606 output (tests/data/breakdown_run, two_parts_run) (D-060,
D-061)."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from pydantic import ValidationError

from vortexcfd.core.model import AsymptoticCriterion, Probe, Reports, Solvers, StoppingCriteria
from vortexcfd.core.reports import (
    available_reports,
    criterion_quantities,
    is_criterion_quantity,
    is_report_id,
    missing_reference,
    report_label,
)
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.convergence import asymptotic_range, evaluate, relative_range, run_time_control
from vortexcfd.foam.forces import (
    CP_MIN_NORMAL,
    CoeffAxes,
    ForceSample,
    breakdown,
    mass_imbalance,
    read_coeff_axes,
)
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.wall_fields import (
    case_yplus_histogram,
    skin_friction,
    skin_friction_along,
    wall_face_values,
    yplus_histogram,
)

DATA = Path(__file__).parent / "data"
RUN = DATA / "breakdown_run"
TWO = DATA / "two_parts_run"
FOAM_SRC = Path("/usr/lib/openfoam/openfoam2606/src")


def _monitor(tmp_path: Path, source: Path) -> ReportMonitor:
    case = tmp_path / "case"
    shutil.copytree(source, case)
    monitor = ReportMonitor(case)
    assert monitor.poll()
    return monitor


# -- report ids and model --------------------------------------------------------------------------------


def test_report_ids_labels_and_availability() -> None:
    for good in ("Cd", "Cd_viscous", "x_cp", "CmPitch@Ball", "x_cp@Pod", "mass_imbalance", "yplus_max",
                 "probe:wake:p", "probe:wake:Umag"):
        assert is_report_id(good), good
    for bad in ("Cs", "Cd@", "probe:wake:k", "probe:1x:p", "x_cp@Ball@Pod" and "bogus@Ball", ""):
        assert not is_report_id(bad), bad
    assert is_criterion_quantity("Cl_pressure@Ball") and is_criterion_quantity("probe:wake:U")
    assert not is_criterion_quantity("x_cp") and not is_criterion_quantity("mass_imbalance")
    assert not is_criterion_quantity("probe:wake:Ux")
    assert report_label("Cd_pressure@Ball") == "Cd pressure (Ball)" and report_label("probe:wake:Umag") == "Probe wake |U|"
    one = available_reports(["Ball"], [])
    assert "Cd@Ball" not in one and one[:3] == ["Cd", "Cl", "CmPitch"] and "mass_imbalance" in one
    two = available_reports(["Ball", "Pod"], ["wake"])
    assert "x_cp@Pod" in two and "probe:wake:Uz" in two
    assert criterion_quantities(["Ball", "Pod"], ["wake"])[-2:] == ["probe:wake:p", "probe:wake:U"]
    assert missing_reference("Cd@Pod", ["Ball"], []) == "no part patch 'Pod'"
    assert missing_reference("Cd@Ball", ["Ball"], []) == "per-part reports need several parts"
    assert missing_reference("probe:x:p", ["Ball"], ["wake"]) == "no probe 'x'"


def test_probe_and_slot_validation() -> None:
    r = Reports(probes=[Probe(name="wake", location=(1.5, 0, 0))], slots=["probe:wake:p", "Cd@Ball", None])
    assert r.probes[0].location == (1.5, 0.0, 0.0)
    for bad in ({"probes": [{"name": "1st", "location": (0, 0, 0)}]},
                {"probes": [{"name": "a b", "location": (0, 0, 0)}]},
                {"probes": [{"name": "a", "location": (0, 0, 0)}, {"name": "a", "location": (1, 0, 0)}]},
                {"slots": ["Cs", None, None]}):
        with pytest.raises(ValidationError):
            Reports(**bad)
    with pytest.raises(ValidationError):
        AsymptoticCriterion(quantity="x_cp")


# -- solver files --------------------------------------------------------------------------------------------


def _inp(patches=("Ball",), probes=(), criteria=()):
    from vortexcfd.core.model import Inflow, Physics
    from vortexcfd.foam.physics_case import SolverCaseInput

    return SolverCaseInput(Physics(), Inflow(), Solvers(stopping=StoppingCriteria(criteria=list(criteria))),
                           tuple(patches), (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), False,
                           Reports(probes=list(probes)))


def test_function_objects_for_breakdown_mass_wall_shear_and_probes() -> None:
    from vortexcfd.foam.physics_case import build_solver_files

    probe = Probe(name="wake", location=(2.0, 0.0, 0.1))
    functions = build_solver_files(_inp(probes=[probe]))["system/controlDict"].content["functions"]
    assert list(functions) == ["forceCoeffs1", "forces1", "massFlow_inlet", "massFlow_outlet", "yPlus1",
                               "wallShearStress1", "probe_wake"]  # no criteria: no runTimeControl
    assert functions["massFlow_outlet"] == {
        "type": "surfaceFieldValue", "libs": ["fieldFunctionObjects"], "regionType": "patch", "name": "outlet",
        "operation": "sum", "fields": ["phi"], "writeFields": False, "writeControl": "timeStep",
        "writeInterval": 1, "log": False}
    assert functions["wallShearStress1"] == {
        "type": "wallShearStress", "libs": ["fieldFunctionObjects"], "patches": ["Ball"], "writeFields": True,
        "executeControl": "writeTime", "writeControl": "writeTime"}
    assert functions["probe_wake"] == {
        "type": "probes", "libs": ["sampling"], "fields": ["p", "U"], "probeLocations": [[2.0, 0.0, 0.1]],
        "interpolationScheme": "cellPoint", "sampleOnExecute": True, "writeControl": "timeStep",
        "writeInterval": 1}
    two = build_solver_files(_inp(patches=("Ball", "Pod")))["system/controlDict"].content["functions"]
    for name in ("forceCoeffs_Ball", "forces_Ball", "forceCoeffs_Pod", "forces_Pod"):
        assert name in two
    assert two["forces_Pod"]["patches"] == ["Pod"] and two["forceCoeffs_Pod"]["patches"] == ["Pod"]
    assert two["forceCoeffs_Pod"]["log"] is False and two["forceCoeffs1"]["log"] is True


@pytest.mark.skipif(not FOAM_SRC.is_dir(), reason="OpenFOAM v2606 sources not installed")
def test_new_function_objects_use_the_v2606_keywords() -> None:
    from vortexcfd.foam.physics_case import build_solver_files

    functions = build_solver_files(_inp(probes=[Probe(name="w", location=(2, 0, 0))]))["system/controlDict"].content["functions"]
    sources = {
        "surfaceFieldValue": ["functionObjects/field/fieldValues/surfaceFieldValue/surfaceFieldValue.C",
                              "functionObjects/field/fieldValues/fieldValue/fieldValue.C"],
        "wallShearStress": ["functionObjects/field/wallShearStress/wallShearStress.C"],
        "probes": ["sampling/probes/Probes/Probes.C", "sampling/probes/probes.C",
                   "sampling/probes/probeModels/probeModel.C"],
    }
    generic = {"type", "libs", "writeControl", "writeInterval", "executeControl", "log", "writeFields"}
    for fo in (functions["massFlow_inlet"], functions["wallShearStress1"], functions["probe_w"]):
        text = "".join((FOAM_SRC / f).read_text() for f in sources[fo["type"]] if (FOAM_SRC / f).is_file())
        for key in set(fo) - generic:
            assert f'"{key}"' in text, (fo["type"], key)
    assert '"sum"' in (FOAM_SRC / sources["surfaceFieldValue"][0]).read_text()
    # the probes' interpolation scheme is a registered v2606 interpolation type
    cell_point = FOAM_SRC / "finiteVolume/interpolation/interpolation/interpolationCellPoint/interpolationCellPoint.H"
    assert f'TypeName("{functions["probe_w"]["interpolationScheme"]}")' in cell_point.read_text()
    assert '"patch"' in (FOAM_SRC / sources["surfaceFieldValue"][0]).read_text()


def test_criteria_on_part_coefficients_and_probes_are_evaluated_by_the_app(tmp_path: Path) -> None:
    """An asymptotic criterion on a part coefficient or a probe is not a runTimeControl condition
    (D-058): the app evaluates it from the files of the run (here the real two-part and
    breakdown runs)."""
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd_pressure@Pod", window=5),
                                      AsymptoticCriterion(quantity="probe:wake:U", window=5, floor=0.2)])
    assert run_time_control(stop) is None
    two, run = _monitor(tmp_path / "a", TWO), _monitor(tmp_path / "b", RUN)
    pod, wake = evaluate(stop, {}, lambda q: two.series(q) if "@" in q else run.series(q))
    assert pod.iteration == 30.0 and pod.value == pytest.approx(
        asymptotic_range(two.series("Cd_pressure@Pod"), 5, 0.01))
    assert wake.iteration == 300.0 and wake.value is not None


def test_readiness_flags_a_criterion_on_a_missing_probe(tmp_path: Path) -> None:
    from vortexcfd.core.model import Part
    from vortexcfd.core.project import Project
    from vortexcfd.workflow.solving import physics_problem

    (tmp_path / "geometry").mkdir()
    pv.Sphere(radius=0.5).save(str(tmp_path / "geometry" / "b.stl"))
    p = Project.new("r")
    p.add_part(Part(name="Ball", source_file="geometry/b.stl"))
    p.save(tmp_path / "p.json")
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="probe:gone:p", floor=2.0)])
    p.update_solver(stopping=stop.model_dump())
    assert physics_problem(p) == "Stopping criterion 1 watches Probe gone p: no probe 'gone'."
    p.update_reports(probes=[Probe(name="gone", location=(2, 0, 0)).model_dump()])
    assert physics_problem(p) is None


# -- force breakdown ----------------------------------------------------------------------------------------


def test_coefficient_header_is_read() -> None:
    axes = read_coeff_axes(RUN / "postProcessing/forceCoeffs1/0/coefficient.dat")
    assert axes.drag_dir == (1.0, 0.0, 0.0) and axes.lift_dir == (0.0, 0.0, 1.0)
    assert (axes.mag_u, axes.cofr) == (20.0, (0.0, 0.0, 0.0))
    assert axes.a_ref == pytest.approx(0.9976687) and axes.l_ref == pytest.approx(0.9976687)


def test_sphere_breakdown_matches_force_coeffs(tmp_path: Path) -> None:
    """Real 300-iteration sphere run (frontal A_ref): the projection of forces1 reproduces
    forceCoeffs' Cd, Cl and CmPitch; pressure drag 0.1604 + viscous 0.01165."""
    m = _monitor(tmp_path, RUN)
    (row,) = m.breakdown_rows()
    assert row.name == "All walls"
    coeff = {k: v[-1][1] for k, v in m._coeffs[None].series.items()}
    assert row.cd == pytest.approx(coeff["Cd"], abs=1e-7) and row.cl == pytest.approx(coeff["Cl"], abs=1e-7)
    assert row.cm == pytest.approx(coeff["CmPitch"], abs=1e-9)
    assert row.cd_pressure == pytest.approx(0.16044, abs=1e-5) and row.cd_viscous == pytest.approx(0.011652, abs=1e-6)
    assert row.cd_pressure + row.cd_viscous == pytest.approx(row.cd)
    assert row.cl_pressure + row.cl_viscous == pytest.approx(row.cl)
    # x_cp = x_CofR - M_y / F_z(body): |C_z| = 0.030 >= 0.001 so it is defined
    assert row.x_cp == pytest.approx(-0.0040227, abs=1e-6)
    assert m.series("Cd_viscous")[-1] == (300.0, pytest.approx(0.011652, abs=1e-6))
    assert len(m.series("Cd_pressure")) == 300  # the last row (repeated by writeAndEnd? no: endTime) once


def test_two_part_breakdown_per_part(tmp_path: Path) -> None:
    """Real two-part run (Ball + Pod, alpha 4 deg): each part's projected forces reproduce its own
    forceCoeffs object and the parts add up to all walls."""
    m = _monitor(tmp_path, TWO)
    assert m.part_keys() == ["Ball", "Pod"]
    rows = {r.name: r for r in m.breakdown_rows()}
    assert list(rows) == ["All walls", "Ball", "Pod"]
    for part in ("Ball", "Pod"):
        coeff = {k: v[-1][1] for k, v in m._coeffs[part].series.items()}
        assert rows[part].cd == pytest.approx(coeff["Cd"], abs=1e-7)
        assert rows[part].cl == pytest.approx(coeff["Cl"], abs=1e-7)
        assert rows[part].cm == pytest.approx(coeff["CmPitch"], abs=1e-9)
    for attr in ("cd", "cd_pressure", "cd_viscous", "cl", "cm"):
        assert getattr(rows["Ball"], attr) + getattr(rows["Pod"], attr) == pytest.approx(
            getattr(rows["All walls"], attr), abs=1e-7)  # separate reductions: 1.6e-8 apart
    assert m.series("Cd@Pod")[-1] == (30.0, pytest.approx(0.01790015))


def test_centre_of_pressure_in_body_axes_at_alpha_4(tmp_path: Path) -> None:
    """Real two-part run at alpha = 4 deg (tests/data/two_parts_run, iteration 30): x_cp = x_CofR -
    M_y / F_z(body); the app turns the free stream, not the body, so F_z(body) is the global z
    force. By hand from force.dat / moment.dat (CofR x 0.6252914, q A_ref = 0.5 1.225 20^2 2.24301):
    each sphere's centre of pressure lies at its own centre (Ball at x = 0, Pod at x = 1.5), as it
    must for a sphere; the lift-normal definition would not give that at 4 deg."""
    m = _monitor(tmp_path, TWO)
    rows = {r.name: r for r in m.breakdown_rows()}
    q_a = 0.5 * 1.225 * 20.0 ** 2 * 2.243010
    hand = {"All walls": (-3.374339, -3.484443), "Ball": (-2.692395, -4.259943), "Pod": (-0.6819434, 0.7755001)}
    for name, (m_y, f_z) in hand.items():
        assert abs(f_z) / q_a >= CP_MIN_NORMAL == 1e-3  # Pod: 0.0014, defined
        assert rows[name].x_cp == pytest.approx(0.6252914 - m_y / f_z, abs=1e-5)
    assert rows["Ball"].x_cp == pytest.approx(-0.00673, abs=1e-4)
    assert rows["Pod"].x_cp == pytest.approx(1.50465, abs=1e-4)
    # with the lift direction as the normal (the alternative of docs/QUESTIONS.md item 63) the
    # Pod's centre of pressure would move 0.7 m away from the sphere
    lift = (-6.975647e-02, 0.0, 9.975641e-01)
    f_lift = 9.806599 * lift[0] + 0.7755001 * lift[2]
    assert abs((0.6252914 - (-0.6819434) / f_lift) - 1.50465) > 0.5
    # undefined below the threshold: iteration 5, where the Ball's F_z = 0.3675 N changes sign
    # (0.3675 / 549.5 = 6.7e-4 < 1e-3)
    assert 5.0 not in {t for t, _ in m.series("x_cp@Ball")} and len(m.series("x_cp@Ball")) == 29


def test_breakdown_and_centre_of_pressure_hand_values() -> None:
    axes = CoeffAxes((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), 10.0, 2.0, 0.5, (0.25, 0.0, 0.0))
    q_a = 0.5 * 1.0 * 100 * 0.5  # 25 N
    sample = ForceSample(1.0, ((5.0, 0.0, 10.0), (4.0, 0.0, 10.0), (1.0, 0.0, 0.0)),
                         ((0.0, -2.5, 0.0), (0.0, -2.5, 0.0), (0.0, 0.0, 0.0)))
    row = breakdown("x", sample, axes, 1.0)
    assert (row.cd, row.cd_pressure, row.cd_viscous) == pytest.approx((5 / q_a, 4 / q_a, 1 / q_a))
    assert row.cl == pytest.approx(10 / q_a) and row.cm == pytest.approx(-2.5 / (q_a * 2.0))
    assert row.x_cp == pytest.approx(0.25 + 2.5 / 10.0)  # x_CofR - M_y / F_z
    tiny = ForceSample(1.0, ((5.0, 0.0, 0.9 * CP_MIN_NORMAL * q_a), (5.0, 0, 0), (0, 0, 0)), sample.moment)
    assert breakdown("x", tiny, axes, 1.0).x_cp is None


# -- mass balance --------------------------------------------------------------------------------------------


def test_mass_imbalance_hand_values_and_real_sphere(tmp_path: Path) -> None:
    assert mass_imbalance(-100.0, 100.2) == pytest.approx(0.2)
    assert mass_imbalance(-100.0, 99.0) == pytest.approx(-1.0)
    assert mass_imbalance(0.0, 1.0) is None
    m = _monitor(tmp_path, RUN)
    inlet, outlet, pct = m.mass_balance()
    assert (inlet, outlet) == (-2419.487, 2419.487) and pct == 0.0  # equal to 7 digits at iteration 300
    series = m.series("mass_imbalance")
    assert len(series) == 300 and max(abs(v) for _, v in series) == pytest.approx(0.0083075, abs=1e-6)  # iteration 2


# -- wall shear stress and skin friction ------------------------------------------------------------------------


def test_skin_friction_sign_and_separation_on_the_real_sphere() -> None:
    """sphere_wall.vtp (the Sphere patch at iteration 300, read from the real case): Cf_x > 0 on
    the windward half, Cf_x < 0 on most of the leeward cap (separated flow, about 110-120 deg from
    the stagnation point), and -rho * sum(tau A) equals the viscous force of forces1 (2.848 N)."""
    wall = pv.read(str(RUN / "sphere_wall.vtp"))
    tau = np.asarray(wall.cell_data["wallShearStress"])
    cf, cfx = skin_friction(tau, 20.0), skin_friction_along(tau, (1.0, 0.0, 0.0), 20.0)
    assert cf.max() == pytest.approx(0.009861, abs=1e-5) and (cf >= np.abs(cfx) - 1e-12).all()
    c = wall.cell_centers().points
    theta = np.degrees(np.arccos(np.clip(-c[:, 0] / np.linalg.norm(c, axis=1), -1, 1)))
    assert (cfx[theta < 105] > 0).all()
    assert np.mean(cfx[(theta > 130) & (theta < 160)] < 0) > 0.8
    assert int((cfx < 0).sum()) == 2200 and wall.n_cells == 9460
    area = wall.compute_cell_sizes(length=False, volume=False).cell_data["Area"]
    viscous = -1.225 * (tau * area[:, None]).sum(axis=0)
    forces = [line for line in (RUN / "postProcessing/forces1/0/force.dat").read_text().splitlines()
              if not line.startswith("#")][-1].split()
    assert viscous[0] == pytest.approx(float(forces[7]), rel=1e-3)  # viscous_x = 2.84817 N
    with pytest.raises(ValueError):
        skin_friction(tau, 0.0)


def test_cf_fields_in_the_results_scene_list() -> None:
    from vortexcfd.foam.results import FIELDS_BY_KEY, field_values

    tau = np.array([[-0.4, 0.0, 0.0], [0.2, 0.0, 0.3]])
    assert field_values(FIELDS_BY_KEY["Cf"], {"wallShearStress": tau}, 2.0) == pytest.approx([0.2, np.hypot(0.2, 0.3) / 2])
    a = np.radians(10.0)
    d = (np.cos(a), 0.0, np.sin(a))
    cfx = field_values(FIELDS_BY_KEY["Cf_x"], {"wallShearStress": tau}, 2.0, d)
    assert cfx == pytest.approx([0.4 * np.cos(a) / 2, -(0.2 * np.cos(a) + 0.3 * np.sin(a)) / 2])


# -- y+ histogram ----------------------------------------------------------------------------------------------


def test_yplus_histogram_bins() -> None:
    h = yplus_histogram([0.5, 1.0, 4.99, 5.0, 29.9, 30.0, 299.0, 300.0, 1e4, -1.0, float("nan")])
    assert h.faces == 9  # negative and nan left out; an edge value goes to the upper bin
    assert h.fractions == pytest.approx((1 / 9, 2 / 9, 2 / 9, 2 / 9, 2 / 9))
    assert yplus_histogram([]).faces == 0


def test_yplus_histogram_of_the_real_sphere_field(tmp_path: Path) -> None:
    values = wall_face_values(RUN / "300" / "yPlus", ["Sphere", "inlet", "absent"])
    assert list(values) == ["Sphere", "inlet"] and values["Sphere"].shape == (9460,)  # absent: left out
    h = yplus_histogram(values["Sphere"])
    assert h.faces == 9460
    assert h.fractions == pytest.approx((0.0, 0.0, 328 / 9460, 9132 / 9460, 0.0))
    case = tmp_path / "case"
    shutil.copytree(RUN, case)
    time, again = case_yplus_histogram(case, ["Sphere"])
    assert time == "300" and again == h


# -- probes ---------------------------------------------------------------------------------------------------


def test_probe_series_from_the_real_files(tmp_path: Path) -> None:
    """Probes interpolated with cellPoint (the fixture's controlDict). Upstream of the sphere on the
    stagnation line the total pressure is the free stream's: p + |U|^2 / 2 = 20^2 / 2 = 200 m2/s2
    (198.9 here; the cell values of the previous fixture gave 199.6 with p 42.72 instead of 49.53)."""
    control = read_foam_file(RUN / "system" / "controlDict")["functions"]
    assert control["probe_wake"]["interpolationScheme"] == control["probe_front"]["interpolationScheme"] == "cellPoint"
    m = _monitor(tmp_path, RUN)
    assert m.series("probe:wake:p")[-1] == (300.0, 21.7841) and len(m.series("probe:wake:p")) == 300
    assert m.series("probe:front:p")[-1] == (300.0, 49.5309)
    assert m.series("probe:wake:U")[-1] == (300.0, (14.2693, 0.389491, 1.21209))
    assert m.series("probe:wake:Uz")[-1] == (300.0, 1.21209)
    assert m.series("probe:wake:Umag")[-1][1] == pytest.approx(np.linalg.norm([14.2693, 0.389491, 1.21209]))
    front_u = np.array(m.series("probe:front:U")[-1][1])
    assert 49.5309 + 0.5 * front_u @ front_u == pytest.approx(200.0, rel=0.01)
    assert m.series("probe:absent:p") == []
    # an asymptotic criterion on U: the length of the per-component ranges over |mean vector|
    u = m.series("probe:wake:U")
    last = np.array([v for _, v in u[-5:]])
    expected = np.linalg.norm(last.max(axis=0) - last.min(axis=0)) / max(np.linalg.norm(last.mean(axis=0)), 0.2)
    assert asymptotic_range(u, 5, 0.2) == pytest.approx(expected)
    assert relative_range([v for _, v in u[-5:]], 0.2) == pytest.approx(expected)
    with pytest.raises(KeyError):
        m.series("bogus")


@pytest.mark.slow
def test_probe_criterion_stops_simplefoam_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """An asymptotic criterion on probe p with a loose tolerance is met at its earliest iteration
    (window 6 -> iteration 6) from the probe's file; the app stops simpleFoam cleanly, which
    runs and writes iteration 8 (the signal applies at the next time increment)."""
    from vortexcfd.core.model import Inflow, Physics
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.foam.solver_run import CRITERIA_MET, SolverRun

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="probe:wake:p", window=6, tolerance=1e3,
                                                          floor=2.0)])
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(iterations=40, write_interval=40, stopping=stop),
                          sphere_mesh.inputs.parts, sphere_mesh.inputs.parts_bounds, False,
                          Reports(probes=[Probe(name="wake", location=(1.5, 0.0, 0.0))]))
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    run = SolverRun(case, timeout_s=110, stopping=stop)
    run.start()
    try:
        result = run.wait(115)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(30)
    assert result is not None and result.state == CRITERIA_MET and result.exit_code == 0
    assert result.criteria_met == ("c1_asymptotic_probe:wake:p",) and result.met_iteration == 6
    assert result.iterations == 8 and (case / "8" / "U").is_file()
    monitor = ReportMonitor(case)
    monitor.poll()
    assert len({t for t, _ in monitor.series("probe:wake:p")}) == 8
    assert monitor.mass_balance() is not None and monitor.breakdown_rows()[0].name == "All walls"
