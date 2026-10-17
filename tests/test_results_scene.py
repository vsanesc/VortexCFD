"""Results Scene (D-053), colormaps (D-054) and Open in ParaView (D-055).

tests/data/results_case/ is a tiny REAL solved case (tests/data/README.md): a 8 x 4 x 4 box whose bottom
is the wall patch "Ball", the app's solver files, 5 simpleFoam iterations.
"""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_record import MeshRecord, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.results import FIELDS_BY_KEY, available_fields, field_values, latest_result_time, pressure_coefficient
from vortexcfd.foam.run_record import RunRecord, write_run_record
from vortexcfd.gui import paraview
from vortexcfd.gui.colormaps import COLORMAPS, lookup_table, relative_luminance
from vortexcfd.gui.meshing import inputs_hash
from vortexcfd.gui.results_scene import ResultsView, color_range, read_results
from vortexcfd.gui.theme import DARK

CASE = Path(__file__).parent / "data" / "results_case"
REAL_FIELDS = ["p", "Cp", "U_mag", "U_x", "U_y", "U_z", "k", "omega", "nut", "yPlus"]


# -- fields on disk ---------------------------------------------------------------------------------------


def test_field_list_from_the_real_results_directory(tmp_path: Path) -> None:
    assert latest_result_time(CASE) == "5"
    assert [f.key for f in available_fields(CASE)] == REAL_FIELDS  # no wallShearStress: not written
    assert [f.label for f in available_fields(CASE)][:3] == ["p (kinematic)", "Cp", "|U|"]
    # no results: only 0/ (or empty time directories)
    case = tmp_path / "c"
    shutil.copytree(CASE / "0", case / "0")
    (case / "7").mkdir()
    assert latest_result_time(case) is None and available_fields(case) == []
    assert latest_result_time(tmp_path / "missing") is None


def test_wall_shear_stress_is_listed_when_written(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CASE, case)
    text = (case / "5" / "U").read_text().replace("object      U;", "object      wallShearStress;")
    (case / "5" / "wallShearStress").write_text(text)  # a vector field file of that name
    keys = [f.key for f in available_fields(case)]
    assert keys[-1] == "wallShearStress_mag"
    (case / "5" / "k").write_text((case / "5" / "U").read_text())  # a vector named k is not a scalar k
    assert "k" not in [f.key for f in available_fields(case)]


def test_cp_from_kinematic_pressure() -> None:
    p = np.array([-200.0, 0.0, 100.0])
    assert pressure_coefficient(p, 20.0) == pytest.approx([-1.0, 0.0, 0.5])  # 0.5 U^2 = 200
    with pytest.raises(ValueError):
        pressure_coefficient(p, 0.0)
    data = read_results(CASE, "5", ["Ball"])
    wall = data.patches["Ball"]
    raw_p = np.asarray(wall.cell_data["p"])
    cp = field_values(FIELDS_BY_KEY["Cp"], {"p": raw_p}, 20.0)
    assert cp == pytest.approx(raw_p / 200.0)
    u = np.asarray(wall.cell_data["U"])
    assert field_values(FIELDS_BY_KEY["U_mag"], {"U": u}, 20.0) == pytest.approx(np.linalg.norm(u, axis=1))
    assert field_values(FIELDS_BY_KEY["U_z"], {"U": u}, 20.0) == pytest.approx(u[:, 2])


# -- colormaps and ranges ----------------------------------------------------------------------------------


def test_colormap_lookup_tables() -> None:
    assert list(COLORMAPS) == ["viridis", "plasma", "turbo", "coolwarm", "grayscale"]
    for name in COLORMAPS:
        lut = lookup_table(name)
        assert lut.shape == (256, 3) and lut.min() >= 0.0 and lut.max() <= 1.0
    for name in ("viridis", "plasma", "grayscale"):  # sequential: lightness rises monotonically
        lum = relative_luminance(lookup_table(name))
        assert np.all(np.diff(lum) >= -1e-9) and lum[-1] - lum[0] > 0.7
    cw = relative_luminance(lookup_table("coolwarm"))  # diverging: light middle, equal dark ends
    assert cw[128] > cw[0] + 0.3 and abs(cw[0] - cw[-1]) < 0.05
    assert lookup_table("grayscale")[0] == pytest.approx([0, 0, 0]) and lookup_table("grayscale")[-1] == pytest.approx([1, 1, 1])


def test_range_modes() -> None:
    v = np.array([-1.0, 0.5, 3.0, np.nan])
    assert color_range(v, "auto") == (-1.0, 3.0)
    assert color_range(v, "fixed", (2.0, -2.0)) == (-2.0, 2.0)
    assert color_range(v, "symmetric") == (-3.0, 3.0)
    lo, hi = color_range(np.array([5.0, 5.0]), "auto")
    assert lo < 5.0 < hi  # zero width widened
    with pytest.raises(ValueError):
        color_range(v, "fixed")
    with pytest.raises(ValueError):
        color_range(v, "log")


# -- view and scalar bar ---------------------------------------------------------------------------------------


@pytest.fixture
def plotter(qtbot: QtBot):
    from pyvistaqt import QtInteractor

    qi = QtInteractor(auto_update=False)
    qtbot.addWidget(qi)
    yield qi
    qi.close()


def test_view_draws_the_field_with_the_scalar_bar_in_the_text_token(plotter) -> None:
    view = ResultsView(plotter, DARK)
    view.u_ref = 20.0
    view.font_size = 14
    view.set_data(read_results(CASE, "5", ["Ball"]))
    assert view.field_key == "Cp" and len(view.actors) == 1 and view.section_actor is None
    bar = view.scalar_bar
    assert bar.GetTitle() == "Cp"
    for prop in (bar.GetTitleTextProperty(), bar.GetLabelTextProperty()):
        assert QColor.fromRgbF(*prop.GetColor()) == QColor(DARK.text)
    assert bar.GetLabelTextProperty().GetFontSize() >= 14 and bar.GetTitleTextProperty().GetFontSize() >= 16
    lo, hi = view.field_range()
    raw = np.asarray(view.data.patches["Ball"].cell_data["p"]) / 200.0
    assert (lo, hi) == pytest.approx((raw.min(), raw.max()))
    view.configure(field_key="U_mag", colormap="turbo", range_mode="symmetric", display="Both")
    assert view.section_actor is not None and view.scalar_bar.GetTitle() == "|U| [m/s]"
    assert view.clim()[0] == pytest.approx(-view.clim()[1])
    view.configure(display="Section", range_mode="fixed", fixed_range=(0.0, 25.0))
    assert view.actors == [] and view.section_actor is not None and view.clim() == (0.0, 25.0)
    mapper_range = view.section_actor.mapper.scalar_range
    assert tuple(mapper_range) == pytest.approx((0.0, 25.0))
    before = view.section_actor
    view.set_section(axis=0)
    assert view.section_axis == 0 and view.section_actor is not before
    view.set_visible(False)
    assert not view.scalar_bar.GetVisibility()


# -- ParaView -----------------------------------------------------------------------------------------------------


def _fake_install(root: Path, folder: str) -> Path:
    exe = root / folder / "bin" / "paraview.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return exe


def test_paraview_detection_picks_the_newest(tmp_path: Path) -> None:
    assert paraview.detect(tmp_path) is None
    _fake_install(tmp_path, "ParaView 5.9.1")
    newest = _fake_install(tmp_path, "ParaView 5.13.2")
    _fake_install(tmp_path, "ParaView 5.11.0-RC1")
    assert paraview.detect(tmp_path) == newest
    # a configured path wins, if it exists; a configured path that does not exist gives None
    other = _fake_install(tmp_path / "x", "Custom")
    paraview.set_configured(str(other))
    assert paraview.executable(tmp_path) == other
    paraview.set_configured(str(tmp_path / "nope.exe"))
    assert paraview.executable(tmp_path) is None
    paraview.set_configured("")
    assert paraview.executable(tmp_path) == newest


def test_wslpath_conversion_and_detached_launch(tmp_path: Path) -> None:
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="C:\\\\wsl\\\\case\\\\case.foam\n", stderr="")

    assert paraview.windows_path(tmp_path / "case.foam", run) == "C:\\\\wsl\\\\case\\\\case.foam"
    assert calls[0][0] == ["wslpath", "-w", str(tmp_path / "case.foam")] and calls[0][1]["check"]
    started = []
    paraview.launch(Path("/mnt/c/P/paraview.exe"), tmp_path, run=run,
                    popen=lambda args, **kw: started.append((args, kw)))
    assert (tmp_path / "case.foam").is_file()  # written for the reader
    args, kw = started[0]
    assert args == ["/mnt/c/P/paraview.exe", "C:\\\\wsl\\\\case\\\\case.foam"]
    assert kw["start_new_session"] and kw["stdout"] == subprocess.DEVNULL


# -- main window ----------------------------------------------------------------------------------------------------


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paraview, "PROGRAM_FILES", tmp_path / "ProgramFiles")
    made = []

    def make(results=True, with_viewer=False, stale=False, dialogs=None):
        folder = tmp_path / f"proj{len(made)}"
        (folder / "geometry").mkdir(parents=True)
        pv.Box(bounds=(0.5, 1.5, -0.5, 0.5, 0.0, 0.1)).triangulate().save(str(folder / "geometry" / "ball.stl"))
        project = Project.new("res")
        project.add_part(Part(name="Ball", source_file="geometry/ball.stl"))
        project.save(folder / "p.json")
        case = folder / "case"
        if results:
            shutil.copytree(CASE, case)
        else:
            shutil.copytree(CASE / "constant", case / "constant")
        report = MeshReport(10, 40, 128, 0.0, 0.0, 0.0, 0, True)
        write_mesh_record(case, MeshRecord(report, inputs_hash(project), ("Ball",)))
        from vortexcfd.gui import solving

        if results:
            h = "old" if stale else solving.results_hash(project)
            write_run_record(case, RunRecord("iteration_limit", 5, {"p": 0.1}, h, 0))
        from vortexcfd.gui.main_window import MainWindow

        w = MainWindow(project, dialogs or FakeDialogs(), with_viewer=with_viewer)
        qtbot.addWidget(w)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        w.results_loader.wait(10)
        w.project.save = lambda *a, **k: None
        w.close()


def test_results_tab_hidden_without_results(make_window) -> None:
    w = make_window(results=False)
    assert w.results_time() is None and not w.results_tab.isVisible()


def test_results_tab_fields_and_stale_strip(make_window) -> None:
    w = make_window(stale=True)
    assert w.results_time() == "5" and w.results_tab.isVisible()
    assert w.field_list() == ["p (kinematic)", "Cp", "|U|", "Ux", "Uy", "Uz", "k", "omega", "nut", "y+"]
    assert w.field_combo.currentText() == "Cp"
    w.results_tab.click()
    assert w._scene_mode == "results" and w.results_controls.isVisible()
    assert w.results_stale and w.results_stale_label.isVisible()
    assert w.results_stale_label.text() == "Results out of date: run the solver again"
    w.scene_tab.click()
    assert not w.results_controls.isVisible()
    fresh = make_window()
    fresh.results_tab.click()
    assert not fresh.results_stale_label.isVisible()


def test_new_mesh_removes_results_and_the_tab(make_window) -> None:
    w = make_window()
    w.results_tab.click()
    w._clear_results_after_meshing()
    assert not w.results_tab.isVisible() and w._scene_mode == "geometry"


def test_paraview_button_and_preferences(make_window, tmp_path: Path, monkeypatch) -> None:
    exe = _fake_install(tmp_path / "PV", "ParaView 5.13.2")
    dialogs = FakeDialogs(paraview_path=str(exe))
    w = make_window(dialogs=dialogs)
    w.results_tab.click()
    b = w.paraview_button
    assert not b.isEnabled() and "Edit > Preferences" in b.toolTip()  # nothing under Program Files
    w.act_preferences.trigger()
    assert paraview.configured() == str(exe)
    assert b.isEnabled() and str(exe) in b.toolTip()
    launched = []
    monkeypatch.setattr(paraview, "launch", lambda e, case: launched.append((e, case)))
    b.click()
    assert launched == [(exe, w.project.path.parent / "case")]  # never a real launch in tests
    dialogs.paraview_path = ""  # back to detection: an install under Program Files is found
    newest = _fake_install(tmp_path / "ProgramFiles", "ParaView 5.12.0")
    w.act_preferences.trigger()
    assert paraview.configured() == "" and b.isEnabled() and str(newest) in b.toolTip()


def test_results_scene_with_viewer(make_window, qtbot: QtBot) -> None:
    w = make_window(with_viewer=True)
    w.results_tab.click()
    qtbot.waitUntil(lambda: w.results_view.has_results, timeout=15000)
    view = w.results_view
    assert view.field_key == "Cp" and view.u_ref == 20.0 and view.scalar_bar.GetTitle() == "Cp"
    rows = dict(w.telemetry_rows)
    lo, hi = view.field_range()
    assert rows["Field range"] == f"{lo:.4g} \u2013 {hi:.4g}"
    w.field_combo.setCurrentText("|U|")
    assert view.field_key == "U_mag" and dict(w.telemetry_rows)["Field range"].endswith(" m/s")
    w.colormap_combo.setCurrentText("plasma")
    assert view.colormap == "plasma"
    w.range_combo.setCurrentText("fixed")
    assert w.range_min.isVisible() and w.range_max.isVisible()
    w.range_min.setValue(1.0)
    w.range_max.setValue(30.0)
    w.range_max.editingFinished.emit()
    assert view.clim() == (1.0, 30.0)
    assert not w.section_controls.isVisible()  # walls only
    w.display_combo.setCurrentText("Both")
    assert view.section_actor is not None and w.section_controls.isVisible()
    assert not w.section_toggle.isVisible() and not w.boundary_toggle.isVisible()
    w.section_slider.setValue(200)
    assert view.section_position == pytest.approx(
        view.volume_bounds()[2] + 0.2 * (view.volume_bounds()[3] - view.volume_bounds()[2]))
    w.mesh_tab.click()
    assert not view.scalar_bar.GetVisibility() and "Field range" not in dict(w.telemetry_rows)
