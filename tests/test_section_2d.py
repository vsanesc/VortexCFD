"""The 2D section mode (D-121): airfoil coordinate files (Selig, Lednicer, bad files), the trailing-edge closure,
the section slab, the 2D meshing dictionaries (directional staircases, extrudeMesh, empty patches), the solver
files, the reference area and the 2D reports; one slow test meshes a NACA 0012 slab through the app."""

from pathlib import Path

import numpy as np
import pytest

from tests.validation.naca0012_case import write_dat
from vortexcfd.core.model import Inflow, Mesh, Physics, Reports, Simulation, Solvers
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_case import (
    EXTRUDE_DICT,
    FRONT_AND_BACK,
    MESH_COMMANDS,
    MeshCaseInput,
    build_mesh_files,
)
from vortexcfd.foam.mesh_estimate import estimate_mesh
from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files, far_field_patches, reference_values
from vortexcfd.geometry.section import (
    AirfoilFormatError,
    airfoil_slab,
    loop_area,
    read_airfoil,
    section_loop,
    section_loops,
    slab,
)

LEDNICER = """NACA 0012 (Lednicer)
       5.       5.

 0.0000000 0.0000000
 0.2500000 0.0600000
 0.5000000 0.0500000
 0.7500000 0.0300000
 1.0000000 0.0012600

 0.0000000 0.0000000
 0.2500000 -0.0600000
 0.5000000 -0.0500000
 0.7500000 -0.0300000
 1.0000000 -0.0012600
"""


def _file(tmp_path: Path, text: str, name: str = "a.dat") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


# -- airfoil files -------------------------------------------------------------------------------------------


def test_selig_file(tmp_path: Path) -> None:
    name, fmt, upper, lower = read_airfoil(write_dat(tmp_path / "n.dat", 101))
    assert fmt == "selig" and name.startswith("NACA 0012") and len(upper) == len(lower) == 101
    assert upper[0] == pytest.approx((0.0, 0.0)) and upper[-1] == pytest.approx((1.0, 0.0))
    assert upper[:, 1].max() == pytest.approx(0.5 * 0.11894, abs=2e-4)  # TMR: 11.894 % thick
    assert np.all(lower[1:-1, 1] < 0) and np.all(np.diff(upper[:, 0]) > 0)


def test_lednicer_file(tmp_path: Path) -> None:
    name, fmt, upper, lower = read_airfoil(_file(tmp_path, LEDNICER))
    assert fmt == "lednicer" and name == "NACA 0012 (Lednicer)"
    assert upper[:, 1] == pytest.approx([0.0, 0.06, 0.05, 0.03, 0.00126])
    assert lower[-1] == pytest.approx((1.0, -0.00126))
    with pytest.raises(AirfoilFormatError):
        read_airfoil(_file(tmp_path, LEDNICER), fmt="selig")  # read the wrong way


@pytest.mark.parametrize("text, match", [
    ("only a name\n", "too few lines"),
    ("x\n0 0\n1 a\n", "line 3: expected two numbers"),
    ("x\n1 0\n0 0\n1 0\n", "too few"),
    ("x\n     5.      5.\n0 0\n0.5 0.05\n1 0\n0 0\n0.5 -0.05\n1 0\n", "announces 5 \\+ 5 points, the file has 6"),
    ("x\n     5.      5.\n0.1 0\n0.3 0.05\n0.5 0.05\n0.7 0.03\n1 0\n0 0\n0.3 -0.05\n0.5 -0.05\n0.7 -0.03\n1 0\n",
     "do not start at the same leading-edge point"),
])
def test_bad_files_are_refused_with_the_reason(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(AirfoilFormatError, match=match):
        read_airfoil(_file(tmp_path, text))


def test_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AirfoilFormatError, match="Cannot read"):
        read_airfoil(tmp_path / "missing.dat")


# -- closure and slab ----------------------------------------------------------------------------------------


def test_trailing_edge_closure(tmp_path: Path) -> None:
    _n, _f, upper, lower = read_airfoil(_file(tmp_path, LEDNICER))
    blunt = section_loop(upper, lower, closure="blunt")
    assert len(blunt) == 9 and blunt[0] == pytest.approx((1.0, 0.00126)) and blunt[-1] == pytest.approx((1.0, -0.00126))
    sharp = section_loop(upper, lower, closure="sharp")
    assert len(sharp) == 8 and sharp[0] == pytest.approx((1.0, 0.0))  # one trailing edge point, mid of the two
    le = int(np.argmin(sharp[:, 0]))
    assert sharp[le] == pytest.approx((0.0, 0.0))  # the leading edge does not move
    assert sharp[np.isclose(sharp[:, 0], 0.5) & (sharp[:, 1] > 0)][0, 1] == pytest.approx(0.05 - 0.5 * 0.00126)
    scaled = section_loop(upper, lower, scale=2.0, closure="sharp")
    assert np.ptp(scaled[:, 0]) == pytest.approx(2.0) and loop_area(scaled) == pytest.approx(4 * loop_area(sharp))
    closed = section_loop(*read_airfoil(write_dat(tmp_path / "n.dat", 51))[2:])
    assert len(closed) == 100  # already sharp: the trailing edge point once


def test_slab_and_its_section(tmp_path: Path) -> None:
    surface, name, fmt, loop = airfoil_slab(write_dat(tmp_path / "n.dat", 101), scale=2.0)
    assert surface.is_manifold and surface.n_open_edges == 0
    assert surface.bounds[2] == pytest.approx(-1.0) and surface.bounds[3] == pytest.approx(1.0)  # span = chord
    assert surface.volume == pytest.approx(abs(loop_area(loop)) * 2.0, rel=1e-6)
    (back,) = section_loops(surface)
    assert abs(loop_area(back)) == pytest.approx(abs(loop_area(loop)), rel=1e-6)
    thick = slab([loop], 0.0, 0.01)
    assert thick.bounds[3] - thick.bounds[2] == pytest.approx(0.01)
    with pytest.raises(ValueError):
        section_loops(surface, y=5.0)


# -- dictionaries --------------------------------------------------------------------------------------------


def _inputs(**extra) -> MeshCaseInput:
    mesh = Mesh(background_cells_target=2000, target_surface_size=0.01, curvature_levels=0,
                layer_sizing="relative", layers=3)
    data = dict(domain_bounds=(-10.0, 21.0, -5.0, 5.0, -10.0, 10.0), symmetric=False, parts=("wing",),
                parts_bounds=(0.0, 1.0, -0.5, 0.5, -0.06, 0.06), reference_length=1.0, mesh=mesh,
                part_bounds=((0.0, 1.0, -0.5, 0.5, -0.06, 0.06),), surface_length=1.0, two_d=True)
    data.update(extra)
    return MeshCaseInput(**data)


def test_the_2d_estimate_is_one_cell_across_a_span_of_one_surface_cell() -> None:
    est = _inputs().estimate()
    assert est.base_size == pytest.approx((31.0 * 20.0 / 2000) ** 0.5)  # area-based
    assert est.cells[1] == 1 and est.total_cells == est.cells[0] * est.cells[2]
    assert est.span == pytest.approx(est.surface_size) and est.two_d
    b = est.background_bounds
    assert b[3] - b[2] == pytest.approx(est.span) and (b[2] + b[3]) / 2 == pytest.approx(0.0)
    three = estimate_mesh((-10.0, 21.0, -5.0, 5.0, -10.0, 10.0), 1.0, _inputs().mesh)
    assert three.span == 0.0 and not three.two_d


def test_the_2d_dictionaries() -> None:
    inp = _inputs()
    est = inp.estimate()
    files = build_mesh_files(inp)
    block = files["system/blockMeshDict"].content
    names = [n for n, _ in block["boundary"]]
    assert names == ["inlet", "outlet", "top", "bottom", "slab_front", "slab_back"]  # no "sides"
    assert block["blocks"][2][1] == 1  # one cell across the span
    snappy = files["system/snappyHexMeshDict"].content
    cm = snappy["castellatedMeshControls"]
    assert cm["refinementSurfaces"]["wing"]["level"] == [0, 0] and "curvatureLevel" not in cm["refinementSurfaces"]["wing"]
    stairs = {k: v for k, v in cm["refinementRegions"].items() if k.startswith("section_wing_")}
    assert sorted(stairs) == sorted(f"section_wing_{k}" for k in range(1, est.level_max + 1))
    top = stairs[f"section_wing_{est.level_max}"]
    assert top["mode"] == "inside" and top["levelIncrement"] == [0, 0, [est.level_max, 0, est.level_max]]
    box = snappy["geometry"][f"section_wing_{est.level_max}"]
    grow = 3 * est.base_size / 2 ** est.level_max
    assert box["min"][0] == pytest.approx(-grow) and box["max"][2] == pytest.approx(0.06 + grow)
    assert box["min"][1] < est.background_bounds[2] and box["max"][1] > est.background_bounds[3]
    assert all(f["level"] == 0 for f in cm["features"])
    ext = files[EXTRUDE_DICT].content
    assert ext["constructFrom"] == "patch" and ext["sourceCase"] == '"<case>"' and ext["sourcePatches"] == ["slab_front"]
    assert ext["exposedPatchName"] == "slab_back" and ext["nLayers"] == 1 and ext["flipNormals"] is True
    assert ext["extrudeModel"] == "linearDirection" and ext["mergeTol"] == 0
    assert ext["linearDirectionCoeffs"] == {"direction": [0.0, 1.0, 0.0], "thickness": pytest.approx(est.span)}
    cp = files["system/createPatchDict"].content["patches"]
    assert cp == [{"name": FRONT_AND_BACK, "patchInfo": {"type": "empty"}, "constructFrom": "patches",
                   "patches": ["slab_front", "slab_back"]}]
    assert inp.expected_domain_patches() == ("inlet", "outlet", "top", "bottom", FRONT_AND_BACK)
    steps = [name for name, _ in MESH_COMMANDS]
    assert steps.index("snappyHexMesh") < steps.index("extrudeMesh") < steps.index("createPatch") < steps.index("checkMesh")
    three = build_mesh_files(_inputs(two_d=False))
    assert EXTRUDE_DICT not in three and "system/createPatchDict" not in three


def test_the_2d_c_type_expects_no_sides() -> None:
    inp = _inputs(domain_shape="c_type", domain_volume=500.0, domain_patches=("inlet", "outlet", "farfield", "sides"),
                  inlet_x=-10.0)
    assert inp.expected_domain_patches() == ("inlet", "outlet", "farfield", FRONT_AND_BACK)
    block = build_mesh_files(inp)["system/blockMeshDict"].content
    assert [n for n, _ in block["boundary"]] == ["background", "slab_front", "slab_back"]


def test_the_2d_solver_files_and_the_reference_area() -> None:
    far = far_field_patches("c_type", False, two_d=True)
    assert far == ("farfield",)
    inp = SolverCaseInput(Physics(), Inflow(), Solvers(), ("wing",), (0.0, 1.0, -0.5, 0.5, -0.06, 0.06),
                          far_field=far, span=0.002)
    files = build_solver_files(inp)
    for field in ("U", "p", "k", "omega", "nut"):
        bf = files[f"0/{field}"].content["boundaryField"]
        assert bf[FRONT_AND_BACK] == {"type": "empty"} and "sides" not in bf
    fc = files["system/controlDict"].content["functions"]["forceCoeffs1"]
    assert fc["Aref"] == pytest.approx(1.0 * 0.002) and fc["lRef"] == pytest.approx(1.0)  # chord x span
    ref = reference_values((0.0, 1.0, -0.5, 0.5, -0.06, 0.06), Reports(reference_area_basis="custom", reference_area=3.0),
                           span=0.002)
    assert ref.a_ref == 3.0  # a custom area is kept


def test_2d_needs_a_box_or_c_type_domain_without_symmetry() -> None:
    with pytest.raises(ValueError, match="box or C-type"):
        Simulation(name="x", dimension="2d", domain={"shape": "bullet"})
    with pytest.raises(ValueError, match="no symmetry"):
        Simulation(name="x", dimension="2d", domain={"symmetry": "y_min"})
    project = Project.new("p")
    project.update_domain(shape="bullet", symmetry="y_min")
    project.set_dimension("2d")
    assert project.sim.dimension == "2d" and project.sim.domain.shape == "c_type" and project.sim.domain.symmetry == "none"
    project.undo()
    assert project.sim.dimension == "3d" and project.sim.domain.shape == "bullet"


# -- the workflow --------------------------------------------------------------------------------------------


def airfoil_project(tmp_path: Path, alpha: float = 0.0, **mesh) -> Project:
    from vortexcfd.workflow import part_ops

    folder = tmp_path / "naca"
    (folder / "geometry").mkdir(parents=True)
    project = Project.new("naca")
    project._sim = apply_preset(project.sim, next(p for p in BUILTIN_PRESETS if p.name == "2D airfoil"))
    project.update_inflow(speed=90.0, alpha_deg=alpha)
    project.update_reports(reference_length=1.0, center_of_rotation=(0.25, 0.0, 0.0))
    if mesh:
        project.update_mesh(**mesh)
    project.save(folder / "p.json")
    dat = write_dat(tmp_path / "naca0012.dat", 201)
    project.add_part(part_ops.airfoil_part(folder, dat, "wing", set()))
    return project


def test_the_2d_meshing_case_from_an_airfoil_part(tmp_path: Path) -> None:
    from vortexcfd.foam.dictfile import read_foam_file
    from vortexcfd.workflow import meshing, solving
    import pyvista as pv

    project = airfoil_project(tmp_path, alpha=10.0)
    part = project.sim.geometry.parts[0]
    assert part.section is not None and part.section.format == "selig" and (project.folder / part.section.file).is_file()
    assert meshing.readiness(project) is None
    job = meshing.prepare_job(project)
    est = job.inputs.estimate()
    assert job.inputs.two_d and est.two_d
    stl = pv.read(str(job.case_dir / "constant" / "triSurface" / "wing.stl"))
    b = est.background_bounds
    assert stl.bounds[2] < b[2] and stl.bounds[3] > b[3]  # the slab crosses the background's span
    assert stl.bounds[4] < -0.1  # rotated nose up about the quarter chord: the trailing edge is low
    plan = meshing.plan_layers_for(project, job.box)
    assert est.surface_size <= 220 * plan.first * (1 + 1e-9)  # the wall-resolved level (D-122)
    assert plan.total >= est.surface_size and plan.expansion == 1.2
    snappy = read_foam_file(job.case_dir / "system" / "snappyHexMeshDict")
    assert float(snappy["meshQualityControls"]["relaxed"]["minDeterminant"]) == pytest.approx(1e-5)
    assert (job.case_dir / "system" / "extrudeMeshDict").is_file()
    inp = solving.solver_input(project)
    assert inp.span == pytest.approx(est.span) and inp.far_field == ("farfield",)
    project.update_mesh(layer_sizing="relative")
    three = meshing.inputs_hash(project)
    project.set_dimension("3d")
    assert meshing.inputs_hash(project) != three  # the dimension is a mesh input


def test_import_airfoil_through_the_window(qtbot, tmp_path: Path) -> None:
    from tests.fakes import FakeDialogs
    from vortexcfd.gui.main_window import MainWindow

    folder = tmp_path / "proj"
    folder.mkdir()
    project = Project.new("a")
    project.save(folder / "p.json")
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    try:
        w.dialogs.airfoil = (write_dat(tmp_path / "naca0012.dat", 101), 0.5, "sharp")
        w.import_airfoil()
        part = w.project.sim.geometry.parts[0]
        assert part.name == "naca0012" and part.section.scale == 0.5 and part.section.te_closure == "sharp"
        w.properties.show_node("part", 0)
        assert "selig, scale 0.5, trailing edge sharp" in w.properties.section_label.text()
        w.properties.show_node("root", None)
        w.properties.dimension_combo.setCurrentIndex(1)
        assert w.project.sim.dimension == "2d"
        w.dialogs.airfoil = (_file(tmp_path, "bad\n0 x\n"), 1.0, "blunt")
        w.import_airfoil()
        assert len(w.project.sim.geometry.parts) == 1
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


# -- real mesh (marker slow) ---------------------------------------------------------------------------------


@pytest.mark.slow
def test_a_naca0012_slab_meshed_and_extruded(tmp_path: Path) -> None:
    """The TMR NACA 0012 (201 points per surface) with the "2D airfoil" preset (C-type 100 chords across,
    wall-resolved y+ 1, D-122) at 10 degrees through the app's meshing: checkMesh OK in 2D, one cell across the
    span (every point at one of two y values), the empty frontAndBack patch, the layers kept and the first cell
    at its plan (D-109), no part lost."""
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.polymesh import PolyMesh
    from vortexcfd.workflow import meshing

    project = airfoil_project(tmp_path, alpha=10.0)
    job = meshing.prepare_job(project)
    plan = meshing.plan_layers_for(project, job.box)
    run = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=(plan.first, plan.count), cores=4,
                  step_timeout_s=900)
    run.start()
    result = run.wait(1800)
    assert result is not None and result.success, result
    report = result.report
    assert report.mesh_ok and report.valid and not report.lost_parts and not report.domain_errors
    log = (job.case_dir / "logs" / "log.checkMesh").read_text()
    assert "Mesh has 2 geometric (non-empty/wedge) directions (1 0 1)" in log
    mesh = PolyMesh.read(job.case_dir)
    ys = np.unique(np.round(mesh.points[:, 1] / job.inputs.estimate().span, 6))
    assert len(ys) == 2
    from vortexcfd.foam.postprocessing import patch_face_counts

    counts = patch_face_counts(job.case_dir)
    assert counts[FRONT_AND_BACK] == 2 * report.cells and counts["wing"] > 500
    assert report.first_cell is not None and report.first_cell.warning() is None
    assert report.first_cell.mean_m == pytest.approx(plan.first, rel=0.5)
    (cov,) = report.layers
    assert cov.thickness_percent > 95
    print(f"\n{report.cells} cells, {counts['wing']} wall faces, {plan.count} layers planned, mean {cov.mesh_layers}, "
          f"first cell {report.first_cell.mean_m:.3g} m (planned {plan.first:.3g} m)")
