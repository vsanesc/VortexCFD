"""Results snapshots and the Compare tab (D-149): capture, save and load (also from another project), the value and
set-up difference tables, the overlays, the exports, the report's Comparison section and the window. On the fixture
cases of tests/data (no OpenFOAM run)."""

import csv
import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_report import _check, solved_project
from vortexcfd.workflow import line_plot, report
from vortexcfd.workflow import snapshots as sm


def with_line_plots(project):
    """The fixture case with a line plot through the fluid ("axis") and one wholly outside it ("outside")."""
    project.add_scene_object("line_plot", name="axis", point1=(0.0, 0.0, 0.05), point2=(2.0, 0.0, 0.05),
                             n_samples=50, fields=["p"])
    project.add_scene_object("line_plot", name="outside", point1=(50.0, 0.0, 0.05), point2=(60.0, 0.0, 0.05))
    return project


def two_snapshots(tmp_path: Path):
    project = with_line_plots(solved_project(tmp_path))
    first = sm.capture(project, "baseline")
    sm.save(project, first)
    project.update_inflow(speed=30.0)
    project.update_mesh(background_cells_target=200_000)
    second = sm.capture(project, "faster")
    second.reports["Cd"].mean *= 1.1  # the altered values of the second run
    second.reports["Cd"].series = [(t, 1.1 * v) for t, v in second.reports["Cd"].series]
    second.mesh["cells"] = 256  # twice the fixture mesh's 128 cells
    sm.save(project, second)
    return project, first, second


def test_capture_keeps_the_run(tmp_path: Path) -> None:
    project = with_line_plots(solved_project(tmp_path))
    snap = sm.capture(project, "baseline")  # samples every line plot itself (D-160)
    assert snap.residuals and all(len(v) > 1 for v in snap.residuals.values())
    cd = snap.reports["Cd"]
    assert cd.label == "Cd" and cd.window == 50 and cd.mean is not None and cd.final == cd.series[-1][1]
    assert snap.mesh["cells"] == 128 and snap.mesh["mesh OK"] is True
    assert snap.state.startswith("Criteria met") and snap.iterations == 300
    assert snap.setup["free stream: speed"] == "20" and snap.setup["mesh: background_cells_target"] == "100000"
    line = snap.line_plots["axis"]
    assert len(line.distance) == 50 and len(line.fields["p"]) == 50
    assert "outside" not in snap.line_plots  # outside the fluid: nothing to keep
    obj = project.sim.results.objects[0]  # the same samples as the Results Scene computes
    expected = line_plot.sample_line(line_plot.case_points(project.folder / "case"), obj, 20.0)
    assert line.fields["p"] == pytest.approx([float(v) for v in expected.values["p"]], nan_ok=True)
    assert sm.capture(solved_project(tmp_path / "plain"), "none").line_plots == {}  # no line plots: none
    with pytest.raises(sm.SnapshotError, match="no solver run"):
        shutil.rmtree(project.folder / "case")
        sm.capture(project, "none")


def test_save_load_and_gitignore(tmp_path: Path) -> None:
    project, first, second = two_snapshots(tmp_path)
    folder = project.folder / "snapshots"
    assert sorted(p.name for p in folder.iterdir()) == [".gitignore", "baseline.json", "faster.json"]
    assert (folder / ".gitignore").read_text().splitlines()[-1] == "*"
    loaded = sm.saved(project.folder)
    assert [s.name for s in loaded] == ["baseline", "faster"]
    assert loaded[0].reports["Cd"].mean == pytest.approx(first.reports["Cd"].mean)
    assert loaded[1].line_plots["axis"].fields["p"] == second.line_plots["axis"].fields["p"]
    assert json.loads((folder / "baseline.json").read_text())["format"] == sm.FORMAT_VERSION
    with pytest.raises(sm.SnapshotError, match="exists"):
        sm.save(project, first)
    sm.delete(loaded[0])
    assert [s.name for s in sm.saved(project.folder)] == ["faster"]


def test_snapshots_of_another_project_are_read_only(tmp_path: Path) -> None:
    project, _first, _second = two_snapshots(tmp_path / "a")
    other = sm.from_project(project.path)
    assert [s.label for s in other] == ["baseline (demo)", "faster (demo)"] and all(s.read_only for s in other)
    with pytest.raises(sm.SnapshotError):
        sm.delete(other[0])


def test_the_difference_tables(tmp_path: Path) -> None:
    _project, first, second = two_snapshots(tmp_path)
    rows = {r.report_id: r for r in sm.value_rows([first, second])}
    cells = rows["mesh:cells"]
    assert cells.values == (128.0, 256.0) and cells.absolute(1) == 128.0 and cells.relative(1) == pytest.approx(1.0)
    cd = rows["Cd"]
    assert cd.kind == "windowed mean" and cd.relative(1) == pytest.approx(0.1)
    assert cd.absolute(1) == pytest.approx(0.1 * first.reports["Cd"].mean)
    setup = dict(sm.setup_rows([first, second]))
    assert setup == {"free stream: speed": ("20", "30"), "mesh: background_cells_target": ("100000", "200000")}


def test_overlays_and_exports(tmp_path: Path) -> None:
    from matplotlib.figure import Figure

    _project, first, second = two_snapshots(tmp_path)
    snaps = [first, second]
    choices = dict(sm.plot_choices(snaps))
    assert "residuals" in choices and "report:Cd" in choices and "line:axis:p" in choices
    figure = Figure()
    sm.draw(figure, snaps, "report:Cd")
    ax = figure.axes[0]
    assert [line.get_label() for line in ax.get_lines()] == ["baseline", "faster"]
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["baseline", "faster"]
    sm.draw(figure, snaps, "line:axis:p")
    assert len(figure.axes[0].get_lines()) == 2
    sm.draw(figure, snaps, "residuals")
    labels = [line.get_label() for line in figure.axes[0].get_lines()]
    assert any(lab.startswith("baseline: ") for lab in labels) and any(lab.startswith("faster: ") for lab in labels)
    with Image.open(io.BytesIO(sm.png_bytes(snaps, "report:Cd"))) as png:
        assert png.format == "PNG"
    sm.write_values_csv(snaps, tmp_path / "values.csv")
    rows = list(csv.reader(open(tmp_path / "values.csv", encoding="utf-8")))
    assert rows[0] == ["quantity", "value", "baseline", "faster", "faster - baseline",
                       "faster vs baseline (relative)"]
    cd = next(r for r in rows if r[0] == "Cd")
    assert float(cd[5]) == pytest.approx(0.1)
    sm.write_setup_csv(snaps, tmp_path / "setup.csv")
    setup = list(csv.reader(open(tmp_path / "setup.csv", encoding="utf-8")))
    assert setup[0] == ["input", "baseline", "faster"] and ["free stream: speed", "20", "30"] in setup


def test_the_report_has_a_comparison_only_with_two_runs(tmp_path: Path) -> None:
    project, first, second = two_snapshots(tmp_path)
    assert "Comparison" not in _check(report.build_report(project)).h2
    assert "Comparison" not in _check(report.build_report(project, comparison=[first])).h2
    text = report.build_report(project, comparison=[first, second])
    checker = _check(text)
    assert checker.h2[-2:] == ["Comparison", "Saved views"]
    assert "Set-up differences" in text and "+10 %" in text and "free stream: speed" in text
    assert "Comparison" not in _check(report.build_report(project, omit=["comparison"],
                                                          comparison=[first, second])).h2


def test_the_compare_tab(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.main_window import MainWindow

    project, _first, _second = two_snapshots(tmp_path / "other")
    mine = with_line_plots(solved_project(tmp_path / "mine"))
    w = MainWindow(mine, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    try:
        w.compare_tab.click()
        view = w.compare_view
        assert w.compare_shown() and not w.results_controls.isVisible()
        assert view.keys() == ["current"] and view.hint.isVisible()
        w.dialogs.snapshot_name = "first try"
        view.save_button.click()
        assert (mine.folder / "snapshots" / "first_try.json").is_file()
        # the Results Scene was never shown (no viewer): the snapshot sampled the line plot itself (D-160)
        assert list(sm.load(mine.folder / "snapshots" / "first_try.json").line_plots) == ["axis"]
        assert view.keys()[0] == "current" and len(view.keys()) == 2
        w.dialogs.open_path = project.path
        view.load_button.click()
        assert len(view.keys()) == 4 and "baseline (demo) (read-only)" in view.list.item(2).text()
        view.check(view.keys()[1:3])  # my snapshot against the other project's baseline
        assert not view.hint.isVisible() and view.values_table.rowCount() > 1
        headers = [view.values_table.horizontalHeaderItem(c).text() for c in range(view.values_table.columnCount())]
        assert headers[:4] == ["Quantity", "Value", "first try", "baseline (demo)"]
        assert view.setup_table.rowCount() == 0  # the same set-up
        assert view.plot_choice.count() >= 2 and view.figure.axes
        w.dialogs.line_export_path = tmp_path / "cmp.csv"
        view.values_csv.click()
        assert (tmp_path / "cmp.csv").read_text().startswith("quantity,value")
        w.dialogs.line_export_path = tmp_path / "cmp.png"
        view.png_button.click()
        assert (tmp_path / "cmp.png").read_bytes()[:4] == b"\x89PNG"
        view.list.setCurrentRow(1)
        view.delete_button.click()
        assert not (mine.folder / "snapshots" / "first_try.json").exists()
        w.scene_tab.click()  # back to the viewer
        assert not w.compare_shown() and not w.compare_tab.isChecked()
    finally:
        w.project.save = lambda *a, **k: None
        w.close()
