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
from vortexcfd.foam.convergence import asymptotic_delta, quantity_source, run_time_control
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
        "sampleOnExecute": True, "writeControl": "timeStep", "writeInterval": 1}
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
    assert '"patch"' in (FOAM_SRC / sources["surfaceFieldValue"][0]).read_text()


def test_criteria_on_part_coefficients_and_probes_read_their_function_objects() -> None:
    assert quantity_source("Cd") == ("forceCoeffs1", "Cd")
    assert quantity_source("Cl_viscous") == ("forceCoeffs1", "ClViscous")  # forceCoeffs.C: coeff & "viscous"
    assert quantity_source("Cd_pressure@Pod") == ("forceCoeffs_Pod", "CdPressure")
    assert quantity_source("probe:wake:p") == ("probe_wake", "average(p)")  # Probes.C setResult
    assert quantity_source("probe:wake:U") == ("probe_wake", "average(U)")
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="probe:wake:U", window=10, tolerance=0.01)])
    cond = run_time_control(stop)["conditions"]["c1_asymptotic_probe:wake:U"]
    assert (cond["functionObject"], cond["fields"]) == ("probe_wake", ["average(U)"])


@pytest.mark.skipif(not FOAM_SRC.is_dir(), reason="OpenFOAM v2606 sources not installed")
def test_result_names_are_those_v2606_sets() -> None:
    text = (FOAM_SRC / "functionObjects/forces/forceCoeffs/forceCoeffs.C").read_text()
    assert 'setResult(coeffName & "pressure"' in text and 'setResult(coeffName & "viscous"' in text
    word = (FOAM_SRC / "OpenFOAM/primitives/strings/word/word.C").read_text()
    assert "camelCase[a.size()] = char(toupper(b[0]));" in word  # Cd & pressure = CdPressure
    assert 'this->setResult("average(" + fieldName + ")", avgVal);' in (
        FOAM_SRC / "sampling/probes/Probes/Probes.C").read_text()


def test_readiness_flags_a_criterion_on_a_missing_probe(tmp_path: Path) -> None:
    from vortexcfd.core.model import Part
    from vortexcfd.core.project import Project
    from vortexcfd.gui.solving import physics_problem

    (tmp_path / "geometry").mkdir()
    pv.Sphere(radius=0.5).save(str(tmp_path / "geometry" / "b.stl"))
    p = Project.new("r")
    p.add_part(Part(name="Ball", source_file="geometry/b.stl"))
    p.save(tmp_path / "p.json")
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="probe:gone:p")])
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
    # x_cp = x_CofR - M_y / F_z: |C_z| = 0.030 >= 0.01 so it is defined
    assert row.x_cp == pytest.approx(-0.0040227, abs=1e-6)
    assert m.series("Cd_viscous")[-1] == (300.0, pytest.approx(0.011652, abs=1e-6))
    assert len(m.series("Cd_pressure")) == 300  # the last row (repeated by writeAndEnd? no: endTime) once


def test_two_part_breakdown_per_part(tmp_path: Path) -> None:
    """Real two-part run (Ball + Pod, alpha 4 deg): each part's projected forces reproduce its own
    forceCoeffs object, the parts add up to all walls, and x_cp is undefined (|C_z| < 0.01)."""
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
    assert all(r.x_cp is None for r in rows.values())
    assert m.series("Cd@Pod")[-1] == (30.0, pytest.approx(0.01790015))
    assert m.series("x_cp@Ball") and m.series("x_cp@Ball")[-1][0] < 30  # undefined once |C_z| < 0.01


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
    m = _monitor(tmp_path, RUN)
    assert m.series("probe:wake:p")[-1] == (300.0, 20.4072) and len(m.series("probe:wake:p")) == 300
    assert m.series("probe:front:p")[-1] == (300.0, 42.7191)
    assert m.series("probe:wake:U")[-1] == (300.0, (13.9701, 0.462082, 2.20037))
    assert m.series("probe:wake:Uz")[-1] == (300.0, 2.20037)
    assert m.series("probe:wake:Umag")[-1][1] == pytest.approx(np.linalg.norm([13.9701, 0.462082, 2.20037]))
    assert m.series("probe:absent:p") == []
    # an asymptotic criterion on U uses the length of the vector difference (the average condition's mag)
    u = m.series("probe:wake:U")
    last = np.array([v for _, v in u[-5:]])
    assert asymptotic_delta(u, 5) == pytest.approx(np.linalg.norm(last[-1] - last.mean(axis=0)))
    with pytest.raises(KeyError):
        m.series("bogus")


@pytest.mark.slow
def test_probe_criterion_stops_simplefoam_on_the_session_mesh(sphere_mesh, tmp_path: Path) -> None:
    """runTimeControl reads a probe's result: an asymptotic criterion on probe p with a loose
    tolerance stops simpleFoam at its earliest iteration (window 6 -> iteration 6)."""
    from vortexcfd.core.model import Inflow, Physics
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files
    from vortexcfd.foam.solver_run import CONVERGED, SolverRun

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case)
    stop = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="probe:wake:p", window=6, tolerance=1e3)])
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(iterations=40, write_interval=40, stopping=stop),
                          sphere_mesh.inputs.parts, sphere_mesh.inputs.parts_bounds, False,
                          Reports(probes=[Probe(name="wake", location=(1.5, 0.0, 0.0))]))
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    run = SolverRun(case, timeout_s=110)
    run.start()
    try:
        result = run.wait(115)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(30)
    assert result is not None and result.state == CONVERGED and result.iterations == 6
    assert result.criteria_met == ("c1_asymptotic_probe:wake:p",)
    monitor = ReportMonitor(case)
    monitor.poll()
    assert len({t for t, _ in monitor.series("probe:wake:p")}) == 6
    assert monitor.mass_balance() is not None and monitor.breakdown_rows()[0].name == "All walls"
