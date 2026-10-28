"""Results scene objects and saved views (D-132): the clip, isosurface and streamline geometry on the real solved
fixture case (tests/data/results_case: a 2 x 1 x 1 m box, 128 cells, U about 20 m/s along +x), persistence and the
v19 -> v20 migration, undo, and the Results node in the window (offscreen)."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import CURRENT_SCHEMA_VERSION, ClipObject, IsoObject, Part, StreamlinesObject
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.run_record import RunRecord, write_run_record
from vortexcfd.workflow import results_objects as ro
from vortexcfd.workflow.meshing import inputs_hash

DATA = Path(__file__).parent / "data"
CASE = DATA / "results_case"


@pytest.fixture(scope="module")
def points():
    reader = pv.OpenFOAMReader(str(CASE / "case.foam"))
    reader.set_active_time_value(5.0)
    return ro.point_fields(reader.read()["internalMesh"])


def test_clip_keeps_the_chosen_side(points) -> None:
    behind = ro.clip_geometry(points, ClipObject(id="c", name="c", origin=(1, 0, 0), normal=(2, 0, 0)))
    front = ro.clip_geometry(points, ClipObject(id="c", name="c", origin=(1, 0, 0), normal=(1, 0, 0), keep="front"))
    assert behind.n_cells and behind.bounds[0] == pytest.approx(0.0) and behind.bounds[1] == pytest.approx(1.0)
    assert front.n_cells and front.bounds[0] == pytest.approx(1.0) and front.bounds[1] == pytest.approx(2.0)
    assert "U" in behind.point_data and "p" in front.point_data


def test_isosurface_inside_and_outside_the_range(points) -> None:
    umag = np.linalg.norm(points.point_data["U"], axis=1)
    iso = ro.iso_geometry(points, IsoObject(id="i", name="i", field="U_mag", value=float(np.median(umag))), 20.0)
    assert iso.n_points > 0 and "U" in iso.point_data
    outside = ro.iso_geometry(points, IsoObject(id="i", name="i", field="U_mag", value=float(umag.max()) + 1.0), 20.0)
    assert outside.n_points == 0
    with pytest.raises(ValueError):
        ro.iso_geometry(points, IsoObject(id="i", name="i", field="Cf", value=1.0), 20.0)  # a wall field, not here


def test_streamlines_from_a_line_and_a_plane(points) -> None:
    line = StreamlinesObject(id="s", name="s", point1=(0.1, 0.0, 0.2), point2=(0.1, 0.0, 0.8), n_seeds=7,
                             max_length=5.0)
    assert ro.seed_points(line).n_points == 7
    lines = ro.streamline_geometry(points, line)
    assert lines.n_cells >= 7 and lines.bounds[1] > 1.5  # downstream along +x
    forward = ro.streamline_geometry(points, line.model_copy(update={"direction": "forward"}))
    assert forward.bounds[1] > 1.5 and forward.bounds[0] >= 0.1 - 1e-6
    short = ro.streamline_geometry(points, line.model_copy(update={"max_length": 0.3}))
    assert short.bounds[1] < 0.5  # the maximum length holds
    plane = StreamlinesObject(id="s", name="s", seed="plane", point1=(0.2, 0.0, 0.5), normal=(1, 0, 0), size=0.6,
                              n_seeds=10, max_length=5.0)
    assert ro.seed_points(plane).n_points == 10
    assert ro.streamline_geometry(points, plane).n_cells >= 10


def test_objects_and_views_persist_and_each_edit_is_one_undo_step(tmp_path: Path) -> None:
    project = Project.new("p")
    clip = project.add_scene_object("clip", origin=(1.0, 0.0, 0.0))
    iso = project.add_scene_object("isosurface", value=19.99)
    stream = project.add_scene_object("streamlines", n_seeds=5)
    assert [o.name for o in project.sim.results.objects] == ["Clip 1", "Isosurface 1", "Streamlines 1"]
    project.update_scene_object(clip, keep="front")
    assert project.undo_label == "Edit 'Clip 1' (keep)"
    project.update_scene_object(stream, direction="backward")
    project.add_view("Top", position=(1.0, 0.0, 5.0), focal_point=(1.0, 0.0, 0.0), view_up=(0.0, 1.0, 0.0))
    path = tmp_path / "p.vcfd"
    project.save(path)
    loaded = Project.open(path).sim.results
    assert loaded == project.sim.results
    assert loaded.objects[0].keep == "front" and loaded.objects[2].direction == "backward"
    assert loaded.views[0].name == "Top" and loaded.views[0].position == (1.0, 0.0, 5.0)
    before = len(project._undo)
    project.undo()
    assert project.sim.results.views == [] and len(project._undo) == before - 1
    project.undo()
    assert project.sim.results.objects[2].direction == "both"
    project.remove_scene_object(iso)
    assert [o.id for o in project.sim.results.objects] == [clip, stream]
    with pytest.raises(ValueError):
        project.update_scene_object(stream, n_seeds=0)


def test_a_v19_project_migrates_to_v20_without_objects() -> None:
    stored = json.loads((DATA / "project_v19.json").read_text())
    assert stored["schema_version"] == 19
    sim = load_simulation(DATA / "project_v19.json")
    assert sim.schema_version == CURRENT_SCHEMA_VERSION == 26
    assert sim.results.objects == [] and sim.results.views == [] and sim.name == "v19 project"


# -- the window -----------------------------------------------------------------------------------------------


@pytest.fixture
def results_window(qtbot: QtBot, tmp_path: Path):
    made = []

    def make():
        folder = tmp_path / "proj"
        (folder / "geometry").mkdir(parents=True)
        pv.Box(bounds=(0.5, 1.5, -0.5, 0.5, 0.0, 0.1)).triangulate().save(str(folder / "geometry" / "ball.stl"))
        project = Project.new("res")
        project.add_part(Part(name="Ball", source_file="geometry/ball.stl"))
        project.save(folder / "p.json")
        case = folder / "case"
        shutil.copytree(CASE, case)
        write_mesh_record(case, MeshRecord(MeshReport(10, 40, 128, 0.0, 0.0, 0.0, 0, True), inputs_hash(project),
                                           ("Ball",)))
        from vortexcfd.workflow import solving

        write_run_record(case, RunRecord("iteration_limit", 5, {"p": 0.1}, solving.results_hash(project), 0))
        from vortexcfd.gui.main_window import MainWindow

        w = MainWindow(project, FakeDialogs(), with_viewer=True)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        w.results_loader.wait(10)
        w.project.save = lambda *a, **k: None
        w.close()


def test_the_results_node_adds_draws_and_edits_objects(results_window, qtbot: QtBot) -> None:
    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    view = w.results_view
    w._select_node("results", None)
    panel = w.properties
    assert panel.sc_save_view.isEnabled() and panel.sc_image.isEnabled() and panel.sc_report.isEnabled()
    for kind in ("clip", "isosurface", "streamlines"):
        panel.sc_add_buttons[kind].click()
        w._select_node("results", None)
    objects = w.project.sim.results.objects
    assert [o.kind for o in objects] == ["clip", "isosurface", "streamlines"]
    assert [("scene_object", i) in w._items for i in range(3)] == [True] * 3
    assert len(view.object_actors) == 3 and view.object_errors == {}
    for actor in view.object_actors:
        bounds = actor.GetBounds()
        assert bounds[1] > bounds[0] and actor.GetVisibility()  # not empty
    assert view.object_actors[0].GetBounds()[1] == pytest.approx(1.0)  # clipped at the centre, upstream half kept
    # edit the clip from its rows: one undo step, the actor follows
    w._select_node("scene_object", 0)
    before = len(w.project._undo)
    keep = panel.sc_fields[("clip", "keep")]
    keep.setCurrentIndex(keep.findData("front"))
    QApplication.processEvents()  # selectors apply once the event loop runs (D-152)
    assert w.project.sim.results.objects[0].keep == "front" and len(w.project._undo) == before + 1
    assert view.object_actors[0].GetBounds()[0] == pytest.approx(1.0)
    # an isosurface outside the field's range draws nothing and says why
    w.project.update_scene_object(objects[1].id, value=1e6)
    assert len(view.object_actors) == 2 and "outside the fluid" in view.object_errors[objects[1].id]
    w._select_node("scene_object", 1)
    assert "nothing to draw" in panel.sc_status.text()
    # hidden: no actor; undo brings it back
    w.project.update_scene_object(objects[2].id, visible=False)
    assert len(view.object_actors) == 1
    w.project.undo()
    assert len(view.object_actors) == 2
    # save a view and show it again
    w._select_node("results", None)
    panel.sc_save_view.click()
    (saved,) = w.project.sim.results.views
    w.viewer.camera.position = (10.0, 10.0, 10.0)
    w._select_node("saved_view", 0)
    panel.sv_go.click()
    assert tuple(w.viewer.camera.position) == pytest.approx(saved.position)


def test_the_section_values_survive_a_scene_object(results_window, qtbot: QtBot) -> None:
    """With display "Section" a scene object used to empty the section actor's mapper input (PyVista's pipeline) and
    the telemetry's field range raised KeyError '_shown'; the view keeps the section's values itself."""
    w = results_window()
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    w.display_combo.setCurrentText("Section")
    QApplication.processEvents()  # selectors apply once the event loop runs (D-152)
    before = w.results_view.shown_values().size
    w.project.add_scene_object("clip", origin=(1.0, 0.0, 0.5))
    assert before > 0 and w.results_view.shown_values().size == before
    assert w.results_view.field_range() is not None
