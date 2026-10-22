"""Internal flow (D-129): the model and migration, the patch roles, the inlet and outlet dictionaries, the hydraulic
diameter, the closed-geometry check, the meshing dictionaries (no domain, layers on walls, locationInMesh inside), the
reports from a recorded run and the GUI rows; one slow real run."""

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.bench.internal_geometries import extruded_outline_solids, pipe_solids, write_pipe, write_solids
from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, Simulation
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation
from vortexcfd.core.reports import available_reports, is_report_id, report_label
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.physics_case import INTERNAL_REPORTS_FILE, build_solver_files
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.geometry import internal as geom
from vortexcfd.geometry.loader import clear_cache, stl_solid_names
from vortexcfd.workflow import internal, meshing, part_ops, solving

DATA = Path(__file__).parent / "data"
D, LENGTH, RHO = 0.1, 0.6, 1000.0


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def _preset(name: str):
    return next(p for p in BUILTIN_PRESETS if p.name == name)


def pipe_project(tmp_path: Path, solids=None, preset: str = "Internal flow") -> Project:
    """A saved internal-flow project with one part whose regions are the pipe's solids, each on its own patch."""
    project = Project.create(tmp_path, "pipe", apply_preset(Simulation(name="pipe"), _preset(preset)))
    stl = project.folder / "geometry" / "pipe.stl"
    write_solids(stl, solids if solids is not None else pipe_solids(D, LENGTH, n_theta=32))
    part = part_ops.with_region_patches(
        part_ops.part_with_solid_regions(project.folder, "pipe", stl, "m", stl_solid_names(stl)))
    project.add_part(part)
    project.update_physics(nu=1e-6, rho_ref=RHO)
    project.update_boundary("inlet", role="inlet", inlet={"kind": "mass_flow", "mass_flow": 2.0})
    project.update_boundary("outlet", role="outlet", outlet={"pressure": 100.0})
    project.save()
    return project


# -- model, migration, roles ------------------------------------------------------------------------------


def test_a_v18_project_migrates_to_v19_unchanged() -> None:
    stored = json.loads((DATA / "project_v18.json").read_text())
    assert stored["schema_version"] == 18
    sim = load_simulation(DATA / "project_v18.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 19
    assert sim.analysis_type == "external" and sim.boundaries == []
    assert sim.reports.planes == [] and sim.reports.pressure_drops == []
    assert sim.name == "v18 project" and sim.inflow.speed == stored["inflow"]["speed"]


def test_roles_default_to_wall_and_each_edit_is_one_undo_step(tmp_path: Path) -> None:
    project = Project.create(tmp_path, "p", apply_preset(Simulation(name="p"), _preset("Internal flow")))
    assert project.sim.boundary("anything").role == "wall"
    project.update_boundary("in", role="inlet")
    project.update_boundary("in", inlet={"kind": "total_pressure", "total_pressure": 250.0})
    assert project.undo_label == "Edit boundary in (kind, total_pressure)"
    entry = project.sim.boundary("in")
    assert (entry.role, entry.inlet.kind, entry.inlet.total_pressure) == ("inlet", "total_pressure", 250.0)
    project.update_boundary("in", role="wall")  # the inlet settings are kept for a switch back
    assert project.sim.boundary("in").inlet.total_pressure == 250.0
    project.undo()
    project.undo()
    assert project.sim.boundary("in").inlet.kind == "velocity" and project.sim.boundary("in").role == "inlet"
    with pytest.raises(ValueError):
        project.update_boundary("in", inlet={"mass_flow": -1.0})


def test_the_roles_need_an_inlet_and_an_outlet(tmp_path: Path) -> None:
    project = pipe_project(tmp_path)
    assert [(p.name, p.safe, p.role) for p in internal.patches(project)] == [
        ("wall", "wall", "wall"), ("inlet", "inlet_1", "inlet"), ("outlet", "outlet_1", "outlet")]
    assert internal.open_patches(project) == (("inlet_1", "inlet"), ("outlet_1", "outlet"))
    project.update_boundary("outlet", role="wall")
    assert meshing.readiness(project) == "Set at least one patch as an outlet (Boundaries)."
    project.update_boundary("inlet", role="wall")
    assert meshing.readiness(project) == "Set at least one patch as an inlet (Boundaries)."


# -- geometry ---------------------------------------------------------------------------------------------


def test_hydraulic_diameter_of_known_patches() -> None:
    # a pipe's inlet disc: D_h = D (a 256-gon: area and perimeter within 0.01 % of the circle's)
    solids = pipe_solids(0.2, 1.0, n_theta=256)
    mesh = pv.merge([pv.PolyData(p, np.hstack([np.full((len(t), 1), 3), t]).ravel()) for _n, p, t in solids])
    labels = np.concatenate([np.full(len(t), i) for i, (_n, _p, t) in enumerate(solids)])
    area, perimeter, dh = geom.patch_measures(mesh, labels, 1)
    assert dh == pytest.approx(0.2, rel=1e-3) and area == pytest.approx(math.pi * 0.01, rel=1e-3)
    assert perimeter == pytest.approx(math.pi * 0.2, rel=1e-3)
    # a square duct's end face: D_h = the side
    box = pv.Box(bounds=(0, 1, 0, 0.3, 0, 0.3), level=2).triangulate()
    face = (np.asarray(box.cell_centers().points)[:, 0] < 1e-9).astype(int)
    assert geom.patch_measures(box, face, 1)[2] == pytest.approx(0.3)
    # 2D (D-121): a channel of height h, span s: D_h = 2 h whatever the span
    slab = extruded_outline_solids([(0, 0), (2, 0), (2, 0.5), (0, 0.5)], ["bottom", "out", "top", "in"], -1.5, 1.5,
                                   "caps")
    mesh = pv.merge([pv.PolyData(p, np.hstack([np.full((len(t), 1), 3), t]).ravel()) for _n, p, t in slab])
    labels = np.concatenate([np.full(len(t), i) for i, (_n, _p, t) in enumerate(slab)])
    assert geom.patch_measures(mesh, labels, 3, two_d=True)[2] == pytest.approx(1.0)


def test_an_open_geometry_cannot_be_meshed(tmp_path: Path) -> None:
    solids = [s for s in pipe_solids(D, LENGTH, n_theta=32) if s[0] != "outlet"]  # no outlet cap
    project = pipe_project(tmp_path, solids)
    project.update_boundary("wall", role="outlet")  # the roles are fine: the geometry is the problem
    reason = meshing.readiness(project)
    assert reason.startswith("The geometry is not closed (32 open edges)")
    assert "Surface Preparation or Repair" in reason


# -- meshing dictionaries -----------------------------------------------------------------------------------


def test_meshing_has_no_domain_and_layers_on_walls_only(tmp_path: Path) -> None:
    project = pipe_project(tmp_path)
    assert meshing.readiness(project) is None
    length = meshing.surface_length(project, meshing.loaded_parts(project)[0])
    assert length.source == "dh_auto" and length.value == pytest.approx(D, rel=0.01)  # the inlet's D_h
    area = internal.inlet_measures(project, meshing._body_parts(project)[1])["inlet_1"].area
    assert meshing.flow_speed(project) == pytest.approx(2.0 / (RHO * area))  # m / (rho A)
    job = meshing.prepare_job(project)
    case = job.case_dir
    snappy = read_foam_file(case / "system" / "snappyHexMeshDict")
    regions = snappy["castellatedMeshControls"]["refinementSurfaces"]["pipe"]["regions"]
    assert {k: v["patchInfo"]["type"] for k, v in regions.items()} == {"wall": "wall", "inlet_1": "patch",
                                                                       "outlet_1": "patch"}
    assert list(snappy["addLayersControls"]["layers"]) == ["wall"]
    x, y, z = snappy["castellatedMeshControls"]["locationInMesh"]
    assert 0 < x < LENGTH and math.hypot(y, z) < D / 2  # inside the pipe
    block = read_foam_file(case / "system" / "blockMeshDict")
    assert [name for name, _ in block["boundary"]] == ["background"]
    assert (case / "system" / "createPatchDict").is_file()
    guard = json.loads((case / "vortexcfd_domain.json").read_text())
    assert guard == {"shape": "internal", "expected": ["inlet_1", "outlet_1"], "background": ["background"]}
    assert job.inputs.estimate().background_bounds[0] < 0  # the box encloses the parts with a margin
    hash_before = meshing.inputs_hash(project)
    project.update_boundary("outlet", outlet={"pressure": 5.0})  # a solver input only
    assert meshing.inputs_hash(project) == hash_before
    project.update_boundary("outlet", role="wall")  # the patch type and the layers change
    assert meshing.inputs_hash(project) != hash_before


def test_a_2d_internal_section_keeps_a_patch_per_segment(tmp_path: Path) -> None:
    outline = [(0, 0), (2, 0), (2, 0.5), (0, 0.5)]
    solids = extruded_outline_solids(outline, ["lower", "outlet", "upper", "inlet"], -0.5, 0.5, "lower")
    project = pipe_project(tmp_path, solids, preset="2D internal flow")
    project.update_mesh(target_yplus=30.0, layer_controls="robust")  # keep the case small
    assert meshing.readiness(project) is None
    job = meshing.prepare_job(project)
    stl = job.case_dir / "constant" / "triSurface" / "pipe.stl"
    assert stl_solid_names(stl) == ["lower", "outlet_1", "upper", "inlet_1"]
    assert (job.case_dir / "system" / "extrudeMeshDict").is_file()
    assert set(job.inputs.expected_domain_patches()) == {"inlet_1", "outlet_1", "frontAndBack"}
    m = internal.inlet_measures(project, meshing._body_parts(project)[1])["inlet_1"]
    assert m.hydraulic_diameter == pytest.approx(1.0)  # 2 x the inlet's height
    # a patch the section does not cut (the end caps on a patch of their own) is refused before meshing
    solids = extruded_outline_solids(outline, ["lower", "outlet", "upper", "inlet"], -0.5, 0.5, "caps")
    capped = pipe_project(tmp_path / "caps", solids, preset="2D internal flow")
    assert meshing.readiness(capped) == ("Part 'pipe': patch 'caps' is not on the 2D section (the cut at mid y): "
                                         "assign its regions to another patch.")


# -- solver dictionaries ------------------------------------------------------------------------------------


def _solver_files(project: Project) -> dict:
    return build_solver_files(solving.solver_input(project))


def test_dictionaries_per_bc_kind(tmp_path: Path) -> None:
    project = pipe_project(tmp_path)
    dh = internal.inlet_measures(project, meshing._body_parts(project)[1])["inlet_1"].hydraulic_diameter
    files = _solver_files(project)
    u, p = files["0/U"].content["boundaryField"], files["0/p"].content["boundaryField"]
    k, omega = files["0/k"].content["boundaryField"], files["0/omega"].content["boundaryField"]
    # mass-flow inlet: Q = m / rho_ref
    assert u["inlet_1"]["type"] == "flowRateInletVelocity"
    assert u["inlet_1"]["volumetricFlowRate"] == pytest.approx(2.0 / RHO)
    assert p["inlet_1"] == {"type": "zeroGradient"}
    assert k["inlet_1"]["type"] == "turbulentIntensityKineticEnergyInlet" and k["inlet_1"]["intensity"] == 0.05
    assert omega["inlet_1"]["type"] == "turbulentMixingLengthFrequencyInlet"
    assert omega["inlet_1"]["mixingLength"] == pytest.approx(0.07 * dh)
    # static outlet, kinematic; backflow-safe velocity and turbulence
    assert p["outlet_1"]["type"] == "fixedValue" and p["outlet_1"]["value"] == pytest.approx(0.1)
    assert u["outlet_1"]["type"] == k["outlet_1"]["type"] == omega["outlet_1"]["type"] == "inletOutlet"
    assert u["wall"] == {"type": "noSlip"} and files["0/nut"].content["boundaryField"]["wall"]["type"] == \
        "nutUSpaldingWallFunction"
    # velocity inlet
    project.update_boundary("inlet", inlet={"kind": "velocity", "speed": 3.0, "length_scale": 0.004})
    files = _solver_files(project)
    assert files["0/U"].content["boundaryField"]["inlet_1"]["type"] == "surfaceNormalFixedValue"
    assert files["0/U"].content["boundaryField"]["inlet_1"]["refValue"] == -3.0
    assert files["0/omega"].content["boundaryField"]["inlet_1"]["mixingLength"] == 0.004
    # total-pressure inlet, kinematic
    project.update_boundary("inlet", inlet={"kind": "total_pressure", "total_pressure": 500.0})
    files = _solver_files(project)
    assert files["0/U"].content["boundaryField"]["inlet_1"]["type"] == "pressureInletOutletVelocity"
    assert files["0/p"].content["boundaryField"]["inlet_1"]["type"] == "totalPressure"
    assert files["0/p"].content["boundaryField"]["inlet_1"]["p0"] == ("uniform", pytest.approx(0.5))
    # a pressure-driven flow solves with SIMPLE and the pressure relaxed (D-131); the others with SIMPLEC
    solution = files["system/fvSolution"].content
    assert solution["SIMPLE"]["consistent"] is False and solution["relaxationFactors"]["fields"] == {"p": 0.3}
    project.update_boundary("inlet", inlet={"kind": "mass_flow"})
    assert _solver_files(project)["system/fvSolution"].content["SIMPLE"]["consistent"] is True
    # reports: no force objects; the pressure fields first, then the flow and the averages
    functions = files["system/controlDict"].content["functions"]
    assert not any(name.startswith(("forceCoeffs", "forces")) for name in functions)
    names = list(functions)
    assert names[:2] == ["pStatic", "pTotal"]
    assert {"massFlow_inlet_1", "pArea_outlet_1", "pMass_inlet_1"} <= set(names)
    assert functions["pMass_inlet_1"]["weightField"] == "U"
    assert functions["pTotal"]["rhoInf"] == RHO and functions["pTotal"]["mode"] == "total"


def test_planes_and_pressure_drops_reach_the_case(tmp_path: Path) -> None:
    project = pipe_project(tmp_path)
    project.update_reports(planes=[{"name": "a", "point": (0.2, 0, 0), "normal": (2, 0, 0)}],
                           pressure_drops=[{"name": "dp1", "upstream": "patch:inlet_1", "downstream": "plane:a"}])
    assert solving.internal_problem(project) is None
    files = _solver_files(project)
    plane = files["system/controlDict"].content["functions"]["planeFlow_a"]
    assert plane["regionType"] == "sampledSurface" and plane["operation"] == "areaNormalIntegrate"
    assert plane["sampledSurfaceDict"]["pointAndNormalDict"]["normal"] == [1.0, 0.0, 0.0]  # unit normal
    # off any layer of mesh faces: 1e-6 of the parts' largest extent (the pipe's 0.6 m) along the normal
    assert plane["sampledSurfaceDict"]["pointAndNormalDict"]["point"] == [pytest.approx(0.2 + 0.6e-6), 0.0, 0.0]
    reports = files[INTERNAL_REPORTS_FILE].content
    assert reports == {"rho": RHO, "pressureDrops": {"dp1": {"upstream": "patch:inlet_1", "downstream": "plane:a"}}}
    project.update_reports(pressure_drops=[{"name": "dp1", "upstream": "patch:inlet_1", "downstream": "plane:b"}])
    assert solving.internal_problem(project) == "Pressure drop dp1: no inlet, outlet or plane 'b'."
    scope = solving.report_scope(project)
    options = available_reports(**scope)
    assert "Cd" not in options and "flow:mdot:patch:inlet_1" in options and "dp:dp1:total" in options


# -- reports from a recorded run ----------------------------------------------------------------------------


def test_reports_from_a_recorded_run(tmp_path: Path) -> None:
    case = tmp_path / "case"
    shutil.copytree(DATA / "internal_run", case)
    monitor = ReportMonitor(case)
    assert monitor.poll()
    rows = {r.name: r for r in monitor.internal_rows()}
    assert list(rows) == ["inlet_1", "outlet_1", "mid"]
    assert rows["inlet_1"].mdot == pytest.approx(-1.5) and rows["outlet_1"].mdot == pytest.approx(1.5)
    assert rows["mid"].mdot == pytest.approx(1.500006) and rows["mid"].kind == "plane"
    assert (rows["outlet_1"].p_area, rows["outlet_1"].p0_mass) == (0.0, pytest.approx(19.08872))
    assert rows["inlet_1"].p0_area == pytest.approx(24.41706)
    assert monitor.drop_rows() == [("loss", pytest.approx(6.013708), pytest.approx(24.41706 - 19.08872))]
    inflow, outflow, imbalance = monitor.mass_balance()
    assert (inflow, outflow, imbalance) == (pytest.approx(-1.5e-3), pytest.approx(1.5e-3), pytest.approx(0.0))
    assert monitor.series("flow:p0_mass:plane:mid")[-1] == (300.0, pytest.approx(21.57556))
    assert monitor.series("dp:loss:static")[0] == (1.0, pytest.approx(monitor.series("flow:p_mass:patch:inlet_1")[0][1]))
    assert len(monitor.series("mass_imbalance")) == 6
    assert report_label("flow:mdot:patch:inlet_1") == "Mass flow (kg/s) patch inlet_1" and is_report_id("dp:loss:total")


# -- the GUI ------------------------------------------------------------------------------------------------


@pytest.fixture
def internal_window(qtbot: QtBot, tmp_path: Path):
    from vortexcfd.gui.main_window import MainWindow

    made = []

    def make() -> MainWindow:
        project = pipe_project(tmp_path)
        w = MainWindow(project, FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        w.project.save = lambda *a, **k: None
        w.close()


def test_tree_rows_and_role_editing(internal_window) -> None:
    w = internal_window()
    kinds = {key[0] for key in w._items}
    assert "internal_patch" in kinds and "internal_reports" in kinds
    assert not kinds & {"inflow", "fluid_domain", "polar_sweep", "generate_domain"}
    assert not w.act_generate_domain.isEnabled() and not w.act_add_wake.isEnabled()  # nothing unbuilt enabled (P4)
    texts = [w._items[("internal_patch", i)].text(0) for i in range(3)]
    assert texts == ["wall (Wall)", "inlet (Mass-flow inlet)", "outlet (Static-pressure outlet)"]
    w._select_node("internal_patch", 1)
    panel = w.properties
    assert panel._rows["ip_mass"].isVisibleTo(panel) and not panel._rows["ip_speed"].isVisibleTo(panel)
    assert panel.ip_mass.suffix() == " kg/s" and panel.ip_mass.value() == 2.0
    assert panel.ip_p0.suffix() == " Pa" and panel.ip_intensity.suffix() == " %"
    assert "m (area" in panel.ip_dh.text() and "auto, 0.07 D_h" in panel.ip_dh.text()
    before = len(w.project._undo)
    panel.ip_kind.setCurrentIndex(panel.ip_kind.findData("total_pressure"))
    assert w.project.sim.boundary("inlet").inlet.kind == "total_pressure" and len(w.project._undo) == before + 1
    assert panel._rows["ip_p0"].isVisibleTo(panel)
    assert w._items[("internal_patch", 1)].text(0) == "inlet (Total-pressure inlet)"
    w._select_node("internal_patch", 0)
    w.properties.ip_role.setCurrentIndex(w.properties.ip_role.findData("outlet"))
    assert w.project.sim.boundary("wall").role == "outlet" and len(w.project._undo) == before + 2
    assert w.properties._rows["ip_pout"].isVisibleTo(w.properties)


def test_planes_and_drops_rows(internal_window) -> None:
    w = internal_window()
    w._select_node("internal_reports", None)
    panel = w.properties
    panel.ir_add_plane.click()
    (plane,) = w.project.sim.reports.planes
    assert plane.name == "plane1" and plane.normal == (1.0, 0.0, 0.0) and plane.point[0] == pytest.approx(LENGTH / 2)
    panel.ir_add_drop.click()
    (drop,) = w.project.sim.reports.pressure_drops
    assert (drop.upstream, drop.downstream) == ("patch:inlet_1", "patch:outlet_1")
    combo = panel.ir_widgets["drops"][0]["downstream"]
    combo.setCurrentIndex(combo.findData("plane:plane1"))
    assert w.project.sim.reports.pressure_drops[0].downstream == "plane:plane1"
    edit = panel.ir_widgets["planes"][0]["point"]
    edit.setText("0.1 0 0")
    edit.editingFinished.emit()
    assert w.project.sim.reports.planes[0].point == (0.1, 0.0, 0.0)
    w.project.undo()
    assert w.project.sim.reports.planes[0].point[0] == pytest.approx(LENGTH / 2)


def test_the_reports_node_shows_the_internal_table(internal_window, tmp_path: Path) -> None:
    w = internal_window()
    case = tmp_path / "recorded"
    shutil.copytree(DATA / "internal_run", case)
    monitor = ReportMonitor(case)
    monitor.poll()
    w._select_node("reports", None)
    w.properties.set_report_monitor(monitor, case)
    panel = w.properties
    assert panel._internal_host.isVisibleTo(panel) and not panel._forces_host.isVisibleTo(panel)
    table = panel.internal_table
    assert table.text("mdot", "inlet_1") == "-1.5 kg/s" and table.text("p0_mass", "outlet_1") == "19.089 Pa"
    assert table.text("dp", "loss").startswith("6.0137 / 5.3283")
    assert "kg/s" in panel.mass_inlet.text()


# -- a real run ---------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_a_short_pipe_with_a_mass_flow_inlet_balances_its_mass(tmp_path: Path) -> None:
    """A 0.6 m pipe (D 0.1 m) of water, a mass-flow inlet of 2 kg/s and a static outlet, through the app's
    pipeline (prepare_job, MeshRun, prepare_solver_case, SolverRun): it converges to the residual criteria within
    600 iterations and the outlet's mass flow equals the inlet's within 0.1 %."""
    from vortexcfd.core.model import ResidualCriterion, StoppingCriteria
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.solver_run import SolverRun

    project = pipe_project(tmp_path)
    project.update_solver(iterations=600, write_interval=600, cores=2, stopping=StoppingCriteria(criteria=[
        ResidualCriterion(field="p", threshold=1e-4), ResidualCriterion(field="U", threshold=1e-5)]))
    job = meshing.prepare_job(project)
    mesh = MeshRun(job.case_dir, parts=job.inputs.patches, cores=2, walls=internal.wall_patches(project))
    mesh.start()
    meshed = mesh.wait()
    assert meshed.success and meshed.report.valid and not meshed.report.domain_errors
    case = solving.prepare_solver_case(project)
    run = SolverRun(case, cores=2, stopping=project.sim.solvers.stopping, timeout_s=900)
    run.start()
    result = run.wait()
    assert result.state == "criteria_met", result.state
    monitor = ReportMonitor(case)
    monitor.poll()
    inflow, outflow, imbalance = monitor.mass_balance()
    assert inflow == pytest.approx(-2.0 / RHO, rel=1e-6)
    assert abs(imbalance) < 0.1
