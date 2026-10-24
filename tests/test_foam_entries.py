"""Show in OpenFOAM file (D-150): the property-to-entry map found with the writers themselves, every mapped entry in a
written case, the viewer scrolled to the entry, the not-yet-written case (a preview) and the window's actions."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_boundary_types import sphere_project
from vortexcfd.core.model import BoxShape, RefinementVolume
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
from vortexcfd.foam.physics_case import build_solver_files
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.workflow import foam_entries as fe
from vortexcfd.workflow import meshing, solving

# A property of each kind: mesh, physics and free stream, a boundary condition, the solver, reference values,
# the ground, a refinement volume.
COVERED = ["mset_feature_angle", "mset_curvature_levels", "mset_min_thickness", "mset_target_yplus", "mset_layers",
           "mset_surface_level_min", "physics_nu", "physics_rho_ref", "inflow_speed", "inflow_turbulence_intensity",
           "geometry_alpha_deg", "face_type:top", "face_type:outlet", "solvers_iterations", "solvers_write_interval",
           "ref_cofr", "ref_length", "dom_upstream", "dom_ground_enabled", "dom_ground_layers", "volume:0:target_size"]


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def project_with_volume(tmp_path: Path):
    project = sphere_project(tmp_path)
    project.add_refinement_volume(RefinementVolume(id="x", name="box", shape=BoxShape(centre=(1.5, 0, 0), size=(1, 1, 1)),
                                                   target_size=0.05))
    project.update_mesh(cores=None)
    return project


def write_case(project) -> Path:
    """The case as Generate Mesh and Run Solver write it (the dictionaries only; no OpenFOAM run)."""
    job = meshing.prepare_job(project)
    for rel, spec in build_solver_files(solving.solver_input(project)).items():
        write_foam_file(job.case_dir / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)
    return job.case_dir


def lookup(content: dict, keys: tuple[str, ...]):
    for key in keys:
        content = content[key]
    return content


def test_the_map_covers_every_kind_of_property_and_every_entry_is_written(tmp_path: Path) -> None:
    project = project_with_volume(tmp_path)
    project.update_solver(cores=2)  # the decomposeParDict is written too
    case = write_case(project)
    for key in COVERED:
        if key.startswith(("dom_ground_", "mset_layers")):
            continue  # these change the written set themselves: checked on their own project below
        entries = fe.entries_for(project, key)
        assert entries, key
        for entry in entries:
            content = read_foam_file(case / entry.file)
            lookup(content, entry.keys)  # KeyError if the writers' entry is not in the written file
            text = (case / entry.file).read_text()
            assert fe.locate(text, entry.keys) is not None, (key, entry)


def test_entries_follow_the_writers(tmp_path: Path) -> None:
    project = project_with_volume(tmp_path)
    assert fe.entries_for(project, "physics_nu")[0] == fe.Entry("constant/transportProperties", ("nu",))
    assert fe.entries_for(project, "inflow_speed")[0] == fe.Entry("0/U", ("internalField",))
    assert fe.entries_for(project, "solvers_iterations") == [fe.Entry("system/controlDict", ("endTime",))]
    feature = [e.text() for e in fe.entries_for(project, "mset_feature_angle")]
    assert feature == ["system/snappyHexMeshDict: castellatedMeshControls/resolveFeatureAngle",
                       "system/surfaceFeatureExtractDict: Ball.stl/includedAngle"]
    top = fe.entries_for(project, "face_type:top")
    assert fe.Entry("0/U", ("boundaryField", "top", "type")) in top
    assert fe.entries_for(project, "volume:0:target_size") == [
        fe.Entry("system/snappyHexMeshDict", ("castellatedMeshControls", "refinementRegions", "volume_box", "levels"))]
    assert fe.entries_for(project, "dom_radius") == []  # a box domain: the radius is not written
    layers = fe.entries_for(project, "mset_layers")  # compared with relative sizing, where the count is written
    assert any(e.keys[-1] == "nSurfaceLayers" for e in layers)
    ground = fe.entries_for(project, "dom_ground_layers")  # the ground's entry appears in the layers dictionary
    assert ground == [fe.Entry("system/snappyHexMeshDict", ("addLayersControls", "layers"))]


def test_locate_finds_nested_and_quoted_keys() -> None:
    text = "\n".join(["FoamFile", "{", "}", "a 1;", "castellatedMeshControls", "{", "    features ();",
                      "    refinementRegions", "    {", '        "volume_box"', "        {", "            mode inside;",
                      "            levels ((1e15 3));", "        }", "    }", "}"])
    assert fe.locate(text, ("castellatedMeshControls", "refinementRegions", "volume_box", "levels")) == 12
    assert fe.locate(text, ("a",)) == 3
    assert fe.locate(text, ("missing",)) is None


def test_the_viewer_scrolls_to_and_highlights_the_entry(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.foam_file_viewer import FoamFileViewer

    project = project_with_volume(tmp_path)
    write_case(project)
    entries = fe.entries_for(project, "mset_feature_angle")
    files = {e: fe.case_file(project, e) for e in entries}
    opened = []
    viewer = FoamFileViewer("feature angle", entries, files, opener=lambda url: opened.append(url) or True)
    qtbot.addWidget(viewer)
    viewer.show()
    assert viewer.text.isReadOnly() and not viewer.preview_label.isVisibleTo(viewer)
    assert viewer.highlighted_text().strip().startswith("resolveFeatureAngle")
    assert viewer.text.textCursor().blockNumber() == viewer.line and viewer.text.extraSelections()
    viewer.entry_combo.setCurrentIndex(1)
    assert viewer.path.name == "surfaceFeatureExtractDict" and "includedAngle" in viewer.highlighted_text()
    assert viewer.open_external() and opened[0].toLocalFile() == str(viewer.path)
    assert "overwritten" in viewer.external_button.toolTip()


def test_a_case_not_yet_written_is_previewed(tmp_path: Path) -> None:
    project = project_with_volume(tmp_path)
    assert not (project.folder / "case").exists()
    entry = fe.entries_for(project, "physics_nu")[0]
    path, real = fe.case_file(project, entry)
    assert not real and path == project.folder / fe.PREVIEW_DIR / "constant" / "transportProperties"
    assert read_foam_file(path)["nu"] == pytest.approx(1.5e-5)
    assert not (project.folder / "case").exists()  # nothing meshed, nothing written to the case


def test_the_row_menu_and_the_window(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import MainWindow

    project = project_with_volume(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.tree.setCurrentItem(w._items[("mesh", None)])
        p = w.properties
        menu = p.row_menu("mset_feature_angle")
        assert [a.text() for a in menu.actions()] == ["Show in OpenFOAM file"]
        menu.actions()[0].trigger()
        title, entries, files = w.dialogs.foam_files[-1]
        assert title == "mset_feature_angle" and entries[0].keys == ("castellatedMeshControls", "resolveFeatureAngle")
        assert all(not real for _path, real in files.values())  # no case yet: the preview
        w.tree.setCurrentItem(w._items[("boundary_top", None)])
        p.row_menu("face_type").actions()[0].trigger()
        assert w.dialogs.foam_files[-1][0] == "face_type:top"
        w.tree.setCurrentItem(w._items[("refinement_volume", 0)])
        p.row_menu("vol_target").actions()[0].trigger()
        assert w.dialogs.foam_files[-1][0] == "volume:0:target_size"
        assert p._rows["mset_feature_angle"].contextMenuPolicy().name == "CustomContextMenu"
        before = len(w.dialogs.foam_files)
        w.show_in_openfoam_file("dom_radius")  # not written for a box: a message, no viewer
        assert len(w.dialogs.foam_files) == before and "not written" in w.statusBar().currentMessage()
    finally:
        w.project.save = lambda *a, **k: None
        w.close()
