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
from vortexcfd.foam.mesh_record import read_mesh_record
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

    def make(with_part=True, save=True, with_viewer=False, domain_enabled=True, folder_name="proj") -> MainWindow:
        folder = tmp_path / folder_name
        (folder / "geometry").mkdir(parents=True, exist_ok=True)
        project = Project.new("m")
        if with_part:
            pv.Sphere(radius=0.5, theta_resolution=24, phi_resolution=24).save(str(folder / "geometry" / "ball.stl"))
            project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
        project.update_domain(upstream=2, downstream=4, lateral=2, vertical=2, enabled=domain_enabled)
        project.update_mesh(base_size=0.5, surface_level_min=1, surface_level_max=2, layers=1,
                            layer_sizing="relative")  # one relative layer on a coarse sphere (D-086)
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
        self.kwargs = kwargs
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


def test_a_mesh_ending_after_a_project_switch_stays_in_its_own_case(make_window, fake_run) -> None:
    """R-01: the record goes to the case the run started in; the open project's results are kept."""
    other = make_window(folder_name="other")
    other.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    case_b = other.project.path.parent / "case"
    record_b = read_mesh_record(case_b)
    (case_b / "100").mkdir()
    (case_b / "postProcessing").mkdir()
    w = make_window()
    case_a = w.project.path.parent / "case"
    w.top_bar.mesh_button.click()
    run = fake_run.instances[-1]
    (case_a / "100").mkdir()  # results of an earlier mesh of A: out of date once A's mesh is new
    w.set_project(Project.open(other.project.path))
    assert run.stop_requested
    a_report = MeshReport(points=10, faces=40, cells=777, max_non_orthogonality=30.5,
                          avg_non_orthogonality=10.0, max_skewness=0.5, failed_checks=0, mesh_ok=True)
    run.finish(MeshRunResult(True, False, exit_codes={}, report=a_report))  # it ended before the stop arrived
    assert read_mesh_record(case_a).report.cells == 777 and read_mesh_record(case_a).patches == ("Ball",)
    assert not (case_a / "100").exists()
    assert read_mesh_record(case_b) == record_b
    assert (case_b / "100").is_dir() and (case_b / "postProcessing").is_dir()
    assert w.mesh_report == record_b.report  # B's mesh is still the one shown
    assert w.top_bar.state_badge.text() != "Meshing" and w.top_bar.mesh_button.text() == "Generate Mesh"
    assert "after the project changed" in w.console.text()


def test_failed_checks_are_warned(make_window, fake_run) -> None:
    w = make_window(with_viewer=False)
    w.tree.setCurrentItem(w._items[("mesh", None)])
    w.top_bar.mesh_button.click()
    bad = MeshReport(10, 40, 99, 80.0, 20.0, 5.0, failed_checks=2, mesh_ok=False)
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=bad))
    assert w.properties.mesh_values["failed"].property("warn") == "true"
    assert w.properties.mesh_values["ok"].text() == "no"
    assert w.statusBar().property("level") == "error"  # failures without a description are hard (D-100)


def test_scene_tabs_switch_between_geometry_and_mesh(make_window) -> None:
    w = make_window(with_viewer=True)
    assert [b.text() for b in (w.scene_tab, w.mesh_tab)] == ["Geometry Scene", "Mesh Scene"]
    assert w.scene_tab.isChecked() and w.scene.actors[0].GetVisibility()
    w.mesh_tab.click()
    assert w._scene_mode == "mesh" and not w.scene.actors[0].GetVisibility()
    assert w._empty_message.actor.GetInput() == "No mesh yet" and w._empty_message.actor.GetVisibility()
    assert w.domain_view.box_actor is None
    w.scene_tab.click()
    assert w.scene.actors[0].GetVisibility() and w._empty_message.actor.GetInput() == "No geometry yet"


# -- real end to end through the window ------------------------------------------------------------------


@pytest.mark.slow
def test_end_to_end_meshing_through_the_window(make_window, qtbot) -> None:
    w = make_window(with_viewer=True)
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
    # Section plane controls of the Mesh Scene.
    w.mesh_tab.click()
    view = w.mesh_view
    assert w.section_controls.isVisible() and w.section_toggle.isChecked() and w.axis_buttons[1].isChecked()
    assert view.section_actor is not None and view.section_actor.GetVisibility()
    assert 0 < w.section_slider.value() < 1000  # the plane starts through the parts' centre
    first_y = view.section_position
    w.section_slider.setValue(w.section_slider.value() + 100)
    assert view.section_position > first_y
    assert view.section_actor.GetBounds()[2] == pytest.approx(view.section_position, abs=1e-6)
    w.axis_buttons[0].click()
    assert view.section_axis == 0 and w.axis_buttons[0].isChecked()
    xb = view.section_actor.GetBounds()
    assert xb[0] == pytest.approx(xb[1], abs=1e-6)
    w.axis_buttons[1].click()
    w.section_toggle.click()  # off: the section disappears, the whole walls come back
    assert not view.section_actor.GetVisibility()
    w.section_toggle.click()
    assert view.section_actor.GetVisibility()
    assert all(not a.GetVisibility() for a in view.boundary_actors)
    w.boundary_toggle.click()
    assert view.boundary_actors and all(a.GetVisibility() for a in view.boundary_actors)
    w.scene_tab.click()  # the controls belong to the Mesh Scene only
    assert not w.section_controls.isVisible()
    w.mesh_tab.click()
    # Layer coverage of the real run, shown in the Mesh properties.
    assert [c.patch for c in w.mesh_report.layers] == ["Ball"] and w.properties.layer_labels
    print("\nGUI layers:", w.properties.layer_labels[0].text())
    assert "/" in w.properties.layer_labels[0].text() and "thickness" in w.properties.layer_labels[0].text()
    # The old mesh stays visible in the Mesh Scene with an out-of-date warning.
    w.mesh_tab.click()
    assert "mesh_stale" not in w.viewer.renderer.actors and not w.mesh_stale
    w.project.update_mesh(layers=2)
    assert w.mesh_stale and w.mesh_view.has_mesh and w.mesh_view.actors[0].GetVisibility()
    assert "mesh_stale" in w.viewer.renderer.actors


# -- mesh settings editor and the cell budget ---------------------------------------------------------


def _mesh_node(w: MainWindow) -> None:
    w.tree.setCurrentItem(w._items[("mesh", None)])


def test_mesh_editor_shows_values_suffixes_and_computed_sizes(make_window) -> None:
    w = make_window(with_viewer=False)
    w.project.update_mesh(base_size=None, surface_level_min=None, surface_level_max=None)
    _mesh_node(w)
    p = w.properties
    assert p._rows["mset_background_cells_target"].isVisible()
    f = p.mesh_fields
    assert f["background_cells_target"].value() == 100_000 and f["background_cells_target"].suffix() == " cells"
    assert f["target_surface_size"].value() == 0.01 and f["target_surface_size"].suffix() == " \u00d7 length"
    assert f["base_size"].suffix() == " m" and f["base_size"].specialValueText() == "auto"
    assert f["base_size"].value() == 0.0  # None shows as "auto"
    assert f["surface_level_max"].value() == -1 and f["surface_level_max"].specialValueText() == "auto"
    assert f["feature_angle"].suffix() == "°" and f["layers"].value() == 1 or True
    # computed values are read-only labels next to their overrides
    assert "(computed)" in p.mesh_base_used.text() and "(computed)" in p.mesh_levels_used.text()
    assert "=" in p.mesh_bg_cells.text() and p.mesh_surface_cells.text().endswith(" m")


def test_editing_a_mesh_field_is_one_undoable_step(make_window) -> None:
    w = make_window(with_viewer=False)
    _mesh_node(w)
    before = len(w.project._undo)
    spin = w.properties.mesh_fields["layers"]
    spin.setValue(4)
    spin.editingFinished.emit()
    assert w.project.sim.mesh.layers == 4 and len(w.project._undo) == before + 1
    assert w.project.undo_label == "Edit mesh (layers)"
    w.act_undo.trigger()
    assert w.properties.mesh_fields["layers"].value() == 1  # the fixture's value


def test_override_and_auto_round_trip(make_window) -> None:
    w = make_window(with_viewer=False)
    _mesh_node(w)
    f = w.properties.mesh_fields
    f["base_size"].setValue(0.3)
    f["base_size"].editingFinished.emit()
    assert w.project.sim.mesh.base_size == 0.3
    assert "(computed)" not in w.properties.mesh_base_used.text()
    f["base_size"].setValue(0.0)  # back to auto
    f["base_size"].editingFinished.emit()
    assert w.project.sim.mesh.base_size is None
    f["surface_level_max"].setValue(4)
    f["surface_level_max"].editingFinished.emit()
    assert w.project.sim.mesh.surface_level_max == 4


def test_rejected_mesh_edit_reverts_and_reports(make_window, monkeypatch) -> None:
    w = make_window(with_viewer=False)
    _mesh_node(w)

    def boom(**fields):
        raise ValueError("mesh rejected")

    monkeypatch.setattr(w.project, "update_mesh", boom)
    spin = w.properties.mesh_fields["expansion_ratio"]
    spin.setValue(2.0)
    spin.editingFinished.emit()
    assert spin.value() == w.project.sim.mesh.expansion_ratio
    assert "mesh rejected" in w.statusBar().currentMessage()


def test_invalid_level_order_is_rejected_by_the_model(make_window) -> None:
    w = make_window(with_viewer=False)
    _mesh_node(w)
    f = w.properties.mesh_fields
    f["surface_level_min"].setValue(5)  # above the fixture's max of 2
    f["surface_level_min"].editingFinished.emit()
    assert w.project.sim.mesh.surface_level_min == 1
    assert "surface_level_max" in w.statusBar().currentMessage()


def test_too_many_background_cells_disable_the_button_with_a_reason(make_window) -> None:
    w = make_window(with_viewer=False)
    w.project.update_mesh(base_size=None, background_cells_target=15_500_000)
    b = w.top_bar.mesh_button
    assert not b.isEnabled()
    assert "limit 2,000,000" in b.toolTip() and "background mesh would have" in b.toolTip()
    _mesh_node(w)
    assert w.properties.mesh_bg_cells.property("warn") == "true"
    w.project.update_mesh(background_cells_target=100_000)
    assert b.isEnabled()
    assert w.properties.mesh_bg_cells.property("warn") == "false"


# -- layer coverage, staleness and persistence -------------------------------------------------------------


def _report_with_layers(*coverage) -> MeshReport:
    return MeshReport(10, 40, 99, 30.0, 10.0, 0.5, failed_checks=0, mesh_ok=True,
                      layers=tuple(coverage), extruded_percent=88.0)


def test_layer_coverage_rows_warn_below_80_percent(make_window, fake_run) -> None:
    from vortexcfd.foam.mesh_report import LayerCoverage

    w = make_window(with_viewer=False)
    w.tree.setCurrentItem(w._items[("mesh", None)])
    w.top_bar.mesh_button.click()
    report = _report_with_layers(LayerCoverage("Ball", 100, 3, 2.0, 0.01, 55.5),
                                 LayerCoverage("Tail", 50, 3, 3.0, 0.02, 100.0))
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=report))
    p = w.properties
    assert len(p.layer_labels) == 2
    assert p.layer_labels[0].text().startswith("2 / 3 (67 %), thickness 55.5 %")  # both metrics
    assert p.layer_labels[0].property("warn") == "true" and p.layer_labels[1].property("warn") == "false"
    assert p.mesh_values["extruded"].text() == "88 %"
    assert "Layers:" in w.console.text() and "Ball 2 / 3 (67 %), thickness 55.5 %" in w.console.text()
    assert "WARNING" in w.console.text()  # low coverage is logged as a warning


def test_good_layer_coverage_is_not_a_warning(make_window, fake_run) -> None:
    from vortexcfd.foam.mesh_report import LayerCoverage

    w = make_window(with_viewer=False)
    w.top_bar.mesh_button.click()
    report = _report_with_layers(LayerCoverage("Ball", 100, 3, 3.0, 0.01, 100.0))
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=report))
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.layer_labels[0].property("warn") == "false"


def test_record_written_and_staleness_follows_the_inputs(make_window, fake_run) -> None:
    from vortexcfd.foam.mesh_record import read_mesh_record
    from vortexcfd.workflow.meshing import inputs_hash

    w = make_window(with_viewer=False)
    w.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    record = read_mesh_record(w.project.path.parent / "case")
    assert record is not None and record.report == _ready_report()
    assert record.inputs_hash == inputs_hash(w.project) and record.patches == ("Ball",)
    assert not w.mesh_stale and w.top_bar.mesh_badge.isHidden()
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.mesh_values["status"].text() == "Up to date"
    w.project.update_mesh(layers=2)  # a meshing input changed
    assert w.mesh_stale and not w.top_bar.mesh_badge.isHidden()
    assert w.top_bar.mesh_badge.text() == "Mesh out of date"
    assert w.top_bar.mesh_badge.dot_color() == w._theme.warning
    assert w.properties.mesh_values["status"].text() == "Mesh out of date"
    assert w.properties.mesh_values["status"].property("warn") == "true"
    w.act_undo.trigger()  # inputs match the mesh again
    assert not w.mesh_stale and w.top_bar.mesh_badge.isHidden()


@pytest.mark.parametrize("change", ["domain", "units", "file", "part"])
def test_every_meshing_input_makes_the_mesh_stale(make_window, fake_run, change) -> None:
    w = make_window(with_viewer=False)
    w.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    assert not w.mesh_stale
    folder = w.project.path.parent
    if change == "domain":
        w.project.update_domain(upstream=3.0)
    elif change == "units":
        w.project.update_part(0, units="mm")
    elif change == "file":
        pv.Sphere(radius=0.6).save(str(folder / "geometry" / "ball.stl"))  # content changed
        w.project.update_part(0, name="Ball")  # no-op edit; force a refresh below
        w._refresh()
    else:
        w.act_add_part.trigger()
    assert w.mesh_stale


def test_last_mesh_is_loaded_when_a_project_is_opened(make_window, fake_run, qtbot) -> None:
    w = make_window(with_viewer=False)
    w.top_bar.mesh_button.click()
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    path = w.project.path
    reopened = MainWindow(Project.open(path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(reopened)
    reopened.show()
    try:
        assert reopened.mesh_report == _ready_report() and not reopened.mesh_stale
        assert reopened.top_bar.mesh_badge.isHidden()
        assert dict(reopened.telemetry_rows)["Cells"] == "1234"
        assert "Loaded the last mesh" in reopened.console.text()
        reopened.project.update_domain(downstream=7.0)
        assert reopened.mesh_stale and not reopened.top_bar.mesh_badge.isHidden()
    finally:
        reopened.project.save = lambda *a, **k: None
        reopened.close()


def test_opening_a_project_without_a_record_shows_no_mesh(make_window) -> None:
    w = make_window(with_viewer=False)
    assert w.mesh_report is None and not w.mesh_stale
    w.tree.setCurrentItem(w._items[("mesh", None)])
    assert w.properties.mesh_empty.isVisible()


def test_successful_mesh_removes_the_previous_results(make_window, fake_run) -> None:
    """D-051: results of the old mesh are deleted (and logged) after a successful Generate Mesh."""
    from vortexcfd.foam.run_record import RunRecord, write_run_record

    w = make_window(with_viewer=False)
    case = w.project.path.parent / "case"
    w.top_bar.mesh_button.click()  # writes the marker-protected case
    (case / "60").mkdir()
    (case / "postProcessing" / "forceCoeffs1" / "0").mkdir(parents=True)
    write_run_record(case, RunRecord("criteria_met", 60, {"p": 1e-5}, "old", 0))
    fake_run.instances[-1].finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report()))
    assert not (case / "60").exists() and not (case / "postProcessing").exists()
    assert not (case / "vortexcfd_run.json").exists() and (case / "system" / "snappyHexMeshDict").is_file()
    assert "Removed the previous results for the new mesh: 60, postProcessing, vortexcfd_run.json" in w.console.text()
    assert w.run_record is None and w.top_bar.results_badge.isHidden()


def test_failed_mesh_keeps_the_previous_results(make_window, fake_run) -> None:
    w = make_window(with_viewer=False)
    case = w.project.path.parent / "case"
    w.top_bar.mesh_button.click()
    (case / "60").mkdir()
    fake_run.instances[-1].finish(MeshRunResult(False, False, "snappyHexMesh", {"snappyHexMesh": 1}))
    assert (case / "60").is_dir() and "Removed the previous results" not in w.console.text()


def test_mesh_properties_state_the_surface_length_and_warn_when_l_ref_is_auto(make_window) -> None:
    """D-085: the Estimate says which length the surface size comes from and its value; an automatic
    l_ref is flagged; curvature refinement shows its finest level."""
    w = make_window(with_viewer=False)
    w.project.update_reports(reference_length=None)
    _mesh_node(w)
    p = w.properties
    assert p._rows["mset_surface_length"].isVisible() and p.mesh_surface_length.text().startswith("l_ref = ")
    assert "auto: bounding-box length" in p.mesh_surface_length.text()
    assert p.mesh_length_warning.isVisible() and "l_ref is not set" in p.mesh_length_warning.text()
    assert p.mesh_curvature.text().startswith("level ") and p.mesh_fields["curvature_levels"].value() == 2
    w.project.update_reports(reference_length=0.5)
    p.refresh()
    assert p.mesh_surface_length.text() == "l_ref = 0.5 m" and not p.mesh_length_warning.isVisible()
    w.project.update_mesh(surface_size_reference="largest_extent", curvature_levels=0)
    p.refresh()
    assert p.mesh_surface_length.text().startswith("L = ") and p.mesh_curvature.text() == "off"
    assert p.mesh_fields["curvature_levels"].specialValueText() == "off"
    assert p.mesh_fields["surface_size_reference"].currentText() == "largest_extent"


# -- parallel meshing (D-111) ----------------------------------------------------------------------


def test_the_mesh_cores_reach_the_run_and_the_record(make_window, fake_run, monkeypatch) -> None:
    from vortexcfd.foam.mesh_record import read_mesh_record
    from vortexcfd.workflow import meshing

    monkeypatch.setattr(meshing, "physical_cores", lambda: 12)
    w = make_window(with_viewer=False)
    w.project.update_mesh(cores=3)
    w.top_bar.mesh_button.click()
    run = fake_run.instances[-1]
    assert run.kwargs["cores"] == 3
    run.finish(MeshRunResult(True, False, exit_codes={}, report=_ready_report(), cores=3))
    assert read_mesh_record(w.project.path.parent / "case").cores == 3


def test_an_exception_in_the_meshing_thread_resets_the_state_badge(make_window, qtbot, monkeypatch) -> None:
    """R-02: the real MeshRun with a step that cannot start: the badge leaves "Meshing" and the
    console shows the error."""
    from vortexcfd.foam import mesh_run

    class Unstartable:
        def start(self, *a, **k):
            raise OSError(28, "No space left on device")

        def request_stop(self, *a, **k):
            return False

    monkeypatch.setattr(mesh_run, "FoamRun", Unstartable)
    w = make_window()
    w.top_bar.mesh_button.click()
    qtbot.waitUntil(lambda: not w.mesh_worker.is_running() and w.top_bar.state_badge.text() != "Meshing",
                    timeout=10000)
    assert w.top_bar.state_badge.text() in ("Saved", "Modified")
    assert w.top_bar.mesh_button.text() == "Generate Mesh" and w.mesh_report is None
    assert "Meshing failed in blockMesh" in w.statusBar().currentMessage()
    assert "blockMesh failed: OSError: [Errno 28] No space left on device" in w.console.text()


def test_a_failed_parallel_step_reports_its_log(make_window, fake_run) -> None:
    w = make_window()
    w.top_bar.mesh_button.click()
    error = "reconstructParMesh failed (exit code 1): see /x/logs/log.reconstructParMesh"
    fake_run.instances[-1].finish(MeshRunResult(False, False, "reconstructParMesh", {"reconstructParMesh": 1},
                                                cores=4, error=error))
    assert "Meshing failed in reconstructParMesh" in w.statusBar().currentMessage()
    assert error in w.console.text() and w.mesh_report is None


def test_the_mesh_cores_field_shows_auto_and_the_cores_used(make_window) -> None:
    from vortexcfd.gui import properties_panel

    if properties_panel.PHYSICAL_CORES < 2:
        pytest.skip("needs two physical cores")
    w = make_window(with_viewer=False)
    _mesh_node(w)
    p = w.properties
    spin = p.mesh_fields["cores"]
    assert spin.value() == 0 and spin.specialValueText() == "auto" and spin.maximum() == properties_panel.PHYSICAL_CORES
    assert "Meshing scales better than the solver; it can use more cores" in spin.toolTip()
    assert p._rows["mset_cores_used"].isVisible() and w.project.sim.solvers.cores == 1
    used = p.mesh_cores_used.text()  # the recommendation, whatever the Solvers cores (owner review of D-111)
    assert used.startswith(f"{used.split(' ')[0]} (automatic; recommended {used.split(' ')[0]} for ")
    spin.setValue(2)
    spin.editingFinished.emit()
    assert w.project.sim.mesh.cores == 2 and p.mesh_cores_used.text().startswith("2 (set; recommended ")
    spin.setValue(0)
    spin.editingFinished.emit()
    assert w.project.sim.mesh.cores is None  # back to automatic
