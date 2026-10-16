"""Tests for running the mesher from the GUI: button states, Stop, console signal, results."""

import threading
from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.mesh_run import MeshRunResult
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui import mesh_worker
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(with_part=True, save=True, with_viewer=True, domain_enabled=True) -> MainWindow:
        folder = tmp_path / "proj"
        (folder / "geometry").mkdir(parents=True, exist_ok=True)
        project = Project.new("m")
        if with_part:
            pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "ball.stl"))
            project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
        project.update_domain(upstream=2, downstream=4, lateral=2, vertical=2, enabled=domain_enabled)
        project.update_mesh(base_size=0.5, surface_level_min=1, surface_level_max=2, layers=1)
        if save:
            project.save(folder / "p.json")
        w = MainWindow(project, FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for run in FakeRun.instances:  # fake runs never end by themselves
        run.alive = False
    for w in made:
        if w.mesh_worker.is_running():
            w.mesh_worker.request_stop()
            qtbot.waitUntil(lambda w=w: not w.mesh_worker.is_running(), timeout=30000)
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


class FakeRun:
    """Stands in for MeshRun: records calls; the test drives lines and completion."""

    instances: list["FakeRun"] = []

    def __init__(self, case_dir, *, on_line=None, on_step=None, on_done=None, **kwargs) -> None:
        self.case_dir, self.on_line, self.on_step, self.on_done = case_dir, on_line, on_step, on_done
        self.started = False
        self.stop_requested = False
        self.alive = False
        FakeRun.instances.append(self)

    def start(self) -> None:
        self.started = self.alive = True

    def request_stop(self) -> None:
        self.stop_requested = True

    def is_running(self) -> bool:
        return self.alive

    def finish(self, result: MeshRunResult) -> None:
        self.alive = False
        self.on_done(result)


@pytest.fixture
def fake_run(monkeypatch):
    FakeRun.instances = []
    monkeypatch.setattr(mesh_worker, "MeshRun", FakeRun)
    return FakeRun


def _ready_report() -> MeshReport:
    return MeshReport(points=10, faces=40, cells=1234, max_non_orthogonality=30.5,
                      avg_non_orthogonality=10.0, max_skewness=0.5, failed_checks=0, mesh_ok=True)


# -- button states ---------------------------------------------------------------------------------


def test_button_disabled_with_a_reason_for_each_missing_precondition(make_window) -> None:
    w = make_window(save=False)
    b = w.top_bar.mesh_button
    assert not b.isEnabled() and "Save the project" in b.toolTip()
    w2 = make_window(with_part=False)
    assert not w2.top_bar.mesh_button.isEnabled()
    assert "Import at least one part" in w2.top_bar.mesh_button.toolTip()
    w3 = make_window(domain_enabled=False)
    assert not w3.top_bar.mesh_button.isEnabled()
    assert "Enable the fluid domain" in w3.top_bar.mesh_button.toolTip()


def test_button_enabled_when_ready_and_follows_the_project(make_window) -> None:
    w = make_window()
    b = w.top_bar.mesh_button
    assert b.isEnabled() and b.text() == "Generate Mesh" and "snappyHexMesh" in b.toolTip()
    w.project.update_domain(enabled=False)
    assert not b.isEnabled() and "Enable the fluid domain" in b.toolTip()
    w.act_undo.trigger()
    assert b.isEnabled()
    w.project.remove_part(0)
    assert not b.isEnabled() and "Import at least one part" in b.toolTip()


# -- Stop path ----------------------------------------------------------------------------------------


def test_generate_then_stop(make_window, fake_run) -> None:
    w = make_window()
    b = w.top_bar.mesh_button
    b.click()
    run = fake_run.instances[-1]
    assert run.started and run.case_dir == w.project.path.parent / "case"
    assert b.text() == "Stop" and b.isEnabled()
    assert w.top_bar.state_badge.text() == "Meshing"
    assert (run.case_dir / "system" / "snappyHexMeshDict").is_file()  # the case was written
    b.click()  # Stop: request_stop, not a new run
    assert run.stop_requested and len(fake_run.instances) == 1
    run.finish(MeshRunResult(success=False, stopped=True))
    assert b.text() == "Generate Mesh" and b.isEnabled()
    assert w.top_bar.state_badge.text() in ("Saved", "Modified")
    assert "stopped" in w.console.text().lower()
    assert w.mesh_report is None


def test_failure_is_reported_and_button_resets(make_window, fake_run) -> None:
    w = make_window()
    w.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(False, False, "snappyHexMesh", {"snappyHexMesh": 1}))
    assert "Meshing failed in snappyHexMesh" in w.statusBar().currentMessage()
    assert w.statusBar().property("level") == "error"
    assert "Meshing failed in snappyHexMesh" in w.console.text()
    assert w.top_bar.mesh_button.text() == "Generate Mesh"


def test_not_ready_click_shows_the_reason(make_window, fake_run) -> None:
    w = make_window()
    w.project.update_domain(enabled=False)
    w.generate_mesh()  # e.g. triggered while the project changed under us
    assert not fake_run.instances
    assert "Enable the fluid domain" in w.statusBar().currentMessage()


# -- console through the signal -------------------------------------------------------------------------


def test_console_receives_lines_from_a_reader_thread_through_the_signal(make_window, fake_run, qtbot) -> None:
    w = make_window()
    w.top_bar.mesh_button.click()
    run = fake_run.instances[-1]
    reader_thread: list[threading.Thread] = []

    def reader() -> None:  # plays the FoamRun reader thread
        reader_thread.append(threading.current_thread())
        run.on_step("blockMesh")
        run.on_line("Create time")
        run.on_line("End")

    t = threading.Thread(target=reader)
    t.start()
    t.join()
    qtbot.waitUntil(lambda: "End" in w.console.text(), timeout=5000)
    assert "Create time" in w.console.text() and "Running blockMesh" in w.console.text()
    assert reader_thread[0] is not threading.main_thread()


def test_slots_run_in_the_gui_thread(make_window, fake_run, qtbot) -> None:
    w = make_window()
    where: list[bool] = []
    original = w.console.append_output

    def spy(text: str) -> None:
        where.append(QThread.currentThread() == QApplication.instance().thread())
        original(text)

    w.console.append_output = spy
    w.top_bar.mesh_button.click()
    run = fake_run.instances[-1]
    t = threading.Thread(target=lambda: run.on_line("from the reader thread"))
    t.start()
    t.join()
    qtbot.waitUntil(lambda: bool(where), timeout=5000)
    assert where == [True]  # widget access happened in the GUI thread only


# -- results ---------------------------------------------------------------------------------------------


def test_report_shown_on_the_mesh_node_and_telemetry(make_window, fake_run) -> None:
    w = make_window(with_viewer=False)
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.mesh_empty.isVisible() and w.properties.mesh_empty.text() == "No mesh"
    assert dict(w.telemetry_rows)["Cells"] == "—"
    w.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    p = w.properties
    assert not p.mesh_empty.isVisible()
    v = {k: lab.text() for k, lab in p.mesh_values.items()}
    assert v["cells"] == "1234" and v["faces"] == "40" and v["ok"] == "yes" and v["failed"] == "0"
    assert v["non_ortho"].startswith("30.5") and v["skewness"] == "0.5"
    assert dict(w.telemetry_rows)["Cells"] == "1234"
    assert "1234 cells" in w.console.text() and "Mesh OK" in w.console.text()


def test_failed_checks_are_warned(make_window, fake_run) -> None:
    w = make_window(with_viewer=False)
    w.tree.setCurrentItem(w._items[("mesh", None)])
    w.top_bar.mesh_button.click()
    bad = MeshReport(10, 40, 99, 80.0, 20.0, 5.0, failed_checks=2, mesh_ok=False)
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=bad))
    assert w.properties.mesh_values["failed"].property("warn") == "true"
    assert w.properties.mesh_values["ok"].text() == "no"
    assert w.statusBar().property("level") == "warning"


def test_scene_tabs_switch_between_geometry_and_mesh(make_window) -> None:
    w = make_window()
    assert [b.text() for b in (w.scene_tab, w.mesh_tab)] == ["Geometry Scene", "Mesh Scene"]
    assert w.scene_tab.isChecked() and w.scene.actors[0].GetVisibility()
    w.mesh_tab.click()
    assert w._scene_mode == "mesh" and not w.scene.actors[0].GetVisibility()
    assert w._empty_message.actor.GetInput() == "No mesh yet" and w._empty_message.actor.GetVisibility()
    assert w.domain_view.box_actor is None
    w.scene_tab.click()
    assert w.scene.actors[0].GetVisibility() and w._empty_message.actor.GetInput() == "No geometry yet"


# -- real end to end through the window ------------------------------------------------------------------


def test_end_to_end_meshing_through_the_window(make_window, qtbot) -> None:
    w = make_window()
    w.top_bar.mesh_button.click()  # real MeshRun: blockMesh .. checkMesh on a coarse sphere
    assert w.top_bar.mesh_button.text() == "Stop"
    # The report arrives through the queued `finished` signal, after the worker thread ended.
    qtbot.waitUntil(lambda: w.mesh_report is not None, timeout=110000)
    qtbot.waitUntil(lambda: not w.mesh_worker.is_running(), timeout=10000)
    assert w.mesh_report is not None and w.mesh_report.mesh_ok and w.mesh_report.cells > 0
    assert w.top_bar.mesh_button.text() == "Generate Mesh"
    assert "Mesh OK" in w.console.text() and "blockMesh" in w.console.text()
    assert w._scene_mode == "mesh" and w.mesh_view.has_mesh  # the part patch is shown with edges
    assert len(w.mesh_view.actors) == 1 and w.mesh_view.actors[0].prop.show_edges
    assert w.mesh_view.n_faces > 0
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.mesh_values["cells"].text() == str(w.mesh_report.cells)
    assert dict(w.telemetry_rows)["Cells"] == str(w.mesh_report.cells)
    w.scene_tab.click()
    assert not w.mesh_view.actors[0].GetVisibility()
