"""Editable boundary types of the domain faces (D-147) [NUMERICS-REVIEW]: the model, the project edit, the meshing and
solver dictionaries, the hashes, the readiness and the GUI. No OpenFOAM run."""

from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import DEFAULT_FACE_KINDS, Domain, Part
from vortexcfd.core.project import Project
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.physics_case import build_solver_files
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow import meshing, solving


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def sphere_project(tmp_path: Path, **domain) -> Project:
    folder = tmp_path / "proj"
    (folder / "geometry").mkdir(parents=True, exist_ok=True)
    pv.Sphere(radius=0.5, theta_resolution=16, phi_resolution=16).save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("p")
    project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
    project.update_reports(reference_length=1.0)
    if domain:
        project.update_domain(**domain)
    project.save(folder / "p.vcfd")
    return project


def solver_fields(project: Project) -> dict:
    files = build_solver_files(solving.solver_input(project))
    return {rel: spec.content["boundaryField"] for rel, spec in files.items() if rel.startswith("0/")}


def block_patch_types(project: Project) -> dict[str, str]:
    job = meshing.prepare_job(project)
    block = read_foam_file(job.case_dir / "system" / "blockMeshDict")
    return {name: entry["type"] for name, entry in block["boundary"]}


# -- model and edit ---------------------------------------------------------------------------------------


def test_domain_boundary_types_are_validated_and_defaults_dropped() -> None:
    domain = Domain(boundary_types={"top": "wall", "inlet": "velocity_inlet", "sides": "slip"})
    assert domain.boundary_types == {"top": "wall"}  # the defaults are not stored
    assert domain.face_kind("top") == "wall" and domain.face_kind("outlet") == "pressure_outlet"
    assert set(DEFAULT_FACE_KINDS) == {"inlet", "outlet", "sides", "top", "bottom", "farfield"}
    with pytest.raises(ValueError, match="unknown domain face"):
        Domain(boundary_types={"roof": "wall"})
    with pytest.raises(ValueError, match="unknown boundary type"):
        Domain(boundary_types={"top": "porous"})
    assert Domain().model_dump()["boundary_types"] == {}


def test_set_face_type_and_the_ground_option(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    project.set_face_type("top", "wall")
    assert project.sim.domain.boundary_types == {"top": "wall"}
    assert project.undo_label == "Boundary type of top: wall"
    project.set_face_type("bottom", "ground")  # the bottom face as the ground plane (D-116)
    assert project.sim.domain.ground.enabled and project.sim.domain.boundary_types == {"top": "wall"}
    project.set_face_type("ground", "moving_wall")  # back to a bottom face, now a moving wall
    assert not project.sim.domain.ground.enabled
    assert project.sim.domain.boundary_types == {"top": "wall", "bottom": "moving_wall"}
    project.undo()
    assert project.sim.domain.ground.enabled


# -- dictionaries ----------------------------------------------------------------------------------------


def test_defaults_write_the_same_dictionaries(tmp_path: Path) -> None:
    plain = sphere_project(tmp_path / "a")
    explicit = sphere_project(tmp_path / "b", boundary_types=dict(DEFAULT_FACE_KINDS))
    assert meshing.face_kinds(explicit) == () and explicit.sim.domain.boundary_types == {}
    assert solver_fields(plain) == solver_fields(explicit)
    assert block_patch_types(plain) == block_patch_types(explicit) == {
        "inlet": "patch", "outlet": "patch", "sides": "patch", "top": "patch", "bottom": "patch"}
    assert meshing.inputs_hash(plain) == meshing.inputs_hash(explicit)


def test_wall_and_symmetry_faces_in_the_mesh_and_the_fields(tmp_path: Path) -> None:
    project = sphere_project(tmp_path, boundary_types={"top": "wall", "sides": "symmetry", "bottom": "moving_wall"})
    assert block_patch_types(project) == {"inlet": "patch", "outlet": "patch", "sides": "symmetryPlane",
                                          "top": "wall", "bottom": "wall"}
    f = solver_fields(project)
    assert f["0/U"]["top"] == {"type": "noSlip"}
    assert f["0/U"]["bottom"] == {"type": "fixedValue", "value": [20.0, 0.0, 0.0]}  # moves with the free stream
    assert f["0/U"]["sides"] == {"type": "symmetryPlane"} and f["0/p"]["sides"] == {"type": "symmetryPlane"}
    assert f["0/nut"]["top"]["type"] == "nutUSpaldingWallFunction" and f["0/k"]["top"]["type"] == "kqRWallFunction"
    assert f["0/omega"]["bottom"]["type"] == "omegaWallFunction" and f["0/p"]["top"] == {"type": "zeroGradient"}
    assert f["0/U"]["inlet"]["type"] == "fixedValue" and f["0/p"]["outlet"]["type"] == "fixedValue"


def test_inlet_and_outlet_on_other_faces(tmp_path: Path) -> None:
    project = sphere_project(tmp_path, boundary_types={"outlet": "slip", "top": "pressure_outlet"})
    f = solver_fields(project)
    assert f["0/U"]["outlet"] == {"type": "slip"} and f["0/p"]["top"] == {"type": "fixedValue", "value": 0.0}
    assert f["0/k"]["top"]["type"] == "inletOutlet"
    assert solving.boundary_problem(project) is None


def test_a_rounded_domain_symmetry_face_is_generic_symmetry(tmp_path: Path) -> None:
    project = sphere_project(tmp_path, shape="bullet", boundary_types={"farfield": "symmetry"})
    assert meshing.face_kinds(project) == (("farfield", "symmetry"),)
    job = meshing.prepare_job(project)
    snappy = read_foam_file(job.case_dir / "system" / "snappyHexMeshDict")
    regions = snappy["castellatedMeshControls"]["refinementSurfaces"]["domain"]["regions"]
    assert regions["farfield"]["patchInfo"]["type"] == "symmetry"
    assert regions["inlet"]["patchInfo"]["type"] == "patch"
    assert solver_fields(project)["0/U"]["farfield"] == {"type": "symmetry"}


# -- readiness and hashes ------------------------------------------------------------------------------------------


def test_readiness_needs_an_inlet_and_an_outlet(tmp_path: Path) -> None:
    project = sphere_project(tmp_path, boundary_types={"inlet": "wall"})
    assert "no inlet" in solving.boundary_problem(project)
    project.update_domain(boundary_types={"outlet": "symmetry"})
    assert "no outlet" in solving.boundary_problem(project)
    assert "no outlet" in solving.readiness(project, has_mesh=True, mesh_stale=False, meshing=False)


def test_hashes_follow_the_types(tmp_path: Path) -> None:
    project = sphere_project(tmp_path)
    mesh0, results0 = meshing.inputs_hash(project), solving.results_hash(project)
    project.set_face_type("top", "wall")
    mesh1, results1 = meshing.inputs_hash(project), solving.results_hash(project)
    assert mesh1 != mesh0 and results1 != results0
    project.set_face_type("top", "moving_wall")  # the same patch type: the mesh stays up to date
    assert meshing.inputs_hash(project) == mesh1 and solving.results_hash(project) != results1
    project.set_face_type("top", "slip")
    assert meshing.inputs_hash(project) == mesh0 and solving.results_hash(project) == results0


# -- GUI ---------------------------------------------------------------------------------------------------


def test_the_face_node_edits_its_type(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import MainWindow

    w = MainWindow(sphere_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.tree.setCurrentItem(w._items[("boundary_top", None)])
        p = w.properties
        combo = p.face_type
        assert combo.currentData() == "slip" and "slip for U" in p.face_bcs.text()
        assert [combo.itemData(i) for i in range(combo.count())] == [
            "velocity_inlet", "pressure_outlet", "slip", "symmetry", "wall", "moving_wall"]
        combo.setCurrentIndex(combo.findData("wall"))
        combo.activated.emit(combo.currentIndex())
        assert w.project.sim.domain.boundary_types == {"top": "wall"}
        assert w._items[("boundary_top", None)].text(0) == "top (wall (no-slip, stationary))"
        assert "noSlip" in p.face_bcs.text()
        # the bottom face offers the ground plane; choosing it selects the ground node
        w.tree.setCurrentItem(w._items[("boundary_bottom", None)])
        assert combo.findData("ground") >= 0
        w.set_boundary_type("bottom", "ground")
        assert w.project.sim.domain.ground.enabled and w._selection == ("boundary_ground", None)
        menu = w.tree_menu_for(("boundary_ground", None))
        types = next(a.menu() for a in menu.actions() if a.text() == "Boundary type")
        assert [a.text() for a in types.actions() if a.isChecked()] == [
            "Ground plane (D-116: its position, motion and layers)"]
    finally:
        w.project.save = lambda *a, **k: None
        w.close()
