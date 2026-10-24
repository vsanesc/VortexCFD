"""Screen layouts (D-155): at the minimum window size and at each interface size, no two visible widgets overlap and
no label's text is clipped (tests/layout_check.py)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.layout_check import clipped_buttons, clipped_labels, problems
from vortexcfd.gui.theme import DARK, INTERFACE_SIZES, apply_theme

SIZES = list(INTERFACE_SIZES.values())


@pytest.fixture
def interface_size(request):
    apply_theme(DARK, request.param)
    yield request.param
    apply_theme(DARK, INTERFACE_SIZES["Small"])


def _settle() -> None:
    for _ in range(5):
        QApplication.processEvents()


@pytest.mark.parametrize("interface_size", SIZES, indirect=True)
def test_the_status_badge_never_clips_its_text(qtbot: QtBot, tmp_path: Path, interface_size: int) -> None:
    from tests.test_boundary_types import sphere_project
    from vortexcfd.gui.main_window import MainWindow

    w = MainWindow(sphere_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.set_point_size(interface_size)
    w.show()
    w.resize(w.minimumSize())  # the narrowest top bar
    bar = w.top_bar
    try:
        states = [("Saved", None), ("Modified", None), ("Meshing", "Meshing"), ("Solving", "Solving")]
        for text, run in states:
            bar.set_project("sphere.vcfd", text == "Modified")
            bar.set_run_state(run)
            _settle()
            badge = bar.state_badge
            assert badge.text() == text
            fm = badge.fontMetrics()
            assert badge.contentsRect().height() >= fm.height()  # ascent and descent: "g", "y" not cut
            assert clipped_labels(bar) == [], text
        bar.set_mesh_stale(True)
        bar.set_results_stale(True)
        _settle()
        # at the minimum width the out-of-date badges are compact; their full text is the tooltip
        assert bar.compact_level() > 0 and bar.layout().sizeHint().width() <= bar.width()
        for badge, text in ((bar.mesh_badge, "Mesh out of date"), (bar.results_badge, "Results out of date")):
            assert badge.isVisible() and badge.text() == text and badge.toolTip() == text
            assert badge.contentsRect().height() >= badge.fontMetrics().height()
        assert clipped_labels(bar) == []
        w.resize(2400, w.height())  # wide: the full texts again
        _settle()
        assert bar.compact_level() == 0 and QLabel.text(bar.mesh_badge) == "Mesh out of date"
        assert clipped_labels(bar) == []
    finally:
        w.project.save = lambda *a, **k: None
        w.close()


# -- every screen at its minimum size (item 4) ---------------------------------------------------------------------


def _at_minimum(widget) -> None:
    hint = widget.minimumSizeHint().expandedTo(widget.minimumSize())
    widget.resize(hint)
    _settle()
    assert widget.width() <= max(hint.width(), widget.minimumWidth()) + 1  # it really is at its minimum


def _check(widget) -> None:
    assert problems(widget) == []


def test_the_checks_find_overlaps_and_clipped_text(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QWidget

    root = QWidget()
    qtbot.addWidget(root)
    a, b = QLabel("first", root), QLabel("a label with a long text", root)
    a.setGeometry(0, 0, 80, 30)
    b.setGeometry(40, 10, 30, 30)  # overlaps a, and is too narrow for its text
    root.resize(200, 100)
    root.show()
    _settle()
    found = problems(root)
    assert any("overlaps" in p for p in found) and any("wide text" in p for p in found)
    b.setGeometry(0, 40, 200, 5)  # too low for its text's descenders
    _settle()
    assert any("px of text in" in p for p in clipped_labels(root))
    from PySide6.QtWidgets import QPushButton

    button = QPushButton("Add mean stable", root)  # a button narrower than its text (D-165)
    button.setGeometry(0, 60, 30, 30)
    button.show()
    _settle()
    assert any("px button" in p for p in clipped_buttons(root))


@pytest.mark.parametrize("interface_size", SIZES, indirect=True)
def test_start_screen_and_new_simulation(qtbot: QtBot, tmp_path: Path, interface_size: int) -> None:
    from vortexcfd.core.presets import PresetStore
    from vortexcfd.gui.recent import RecentProjects
    from vortexcfd.gui.start_dialogs import NewSimulationDialog, StartDialog

    recent = RecentProjects()
    recent.add(tmp_path / "wing" / "wing.vcfd")
    start = StartDialog(recent)
    qtbot.addWidget(start)
    start.show()
    _at_minimum(start)
    _check(start)
    start.show_open_panel()
    _at_minimum(start)
    _check(start)
    new = NewSimulationDialog(PresetStore(tmp_path / "presets"), physical=8)
    qtbot.addWidget(new)
    new.show()
    _at_minimum(new)
    _check(new)


@pytest.fixture
def solved_window(qtbot: QtBot, tmp_path: Path):
    from tests.test_report import solved_project
    from vortexcfd.gui.main_window import MainWindow

    w = MainWindow(solved_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    yield w
    w.project.save = lambda *a, **k: None
    w._confirm_discard = lambda: True
    w.close()


LONG_BANNER = ("Criteria met at iteration 257: Cd: |mean of the last 100 - mean of the 100 before| / max(|mean|, "
               "0.01) <= 0.005")
LONG_WARNING = "Cd oscillates by 10% - the flow may be unsteady; a steady solution may not exist"
NODES = [("root", None), ("part", 0), ("mesh", None), ("physics", None), ("inflow", None), ("fluid_domain", None),
         ("boundary_inlet", None), ("solvers", None), ("stopping", None), ("reference_values", None),
         ("results", None)]


@pytest.mark.parametrize("interface_size", SIZES, indirect=True)
def test_main_window_at_its_minimum(solved_window, interface_size: int) -> None:
    w = solved_window
    w.set_point_size(interface_size)
    w.show()
    _at_minimum(w)
    assert w.width() >= 60 * w.fontMetrics().height() * 0.9  # a sensible minimum, not the collapsed one
    for key in NODES:
        item = w._items.get(key)
        if item is None:
            continue
        w.tree.setCurrentItem(item)
        _settle()
        assert problems(w) == [], key
    # the monitors with the longest texts a run gives (the real sphere case's banner and warning)
    from vortexcfd.gui.monitors import CHART_MIN_U

    m = w.monitors
    m.convergence.set_view(True, (LONG_BANNER, "ok"), [], [LONG_WARNING])
    m._sync_criteria_section()
    _settle()
    _check(w)
    assert m.chart.height() >= CHART_MIN_U * w.fontMetrics().height() * 0.9  # the column scrolls instead
    # rows rebuilt after an edit (the mesh's layer rows): the replaced ones never drawn over the new ones
    w.tree.setCurrentItem(w._items[("mesh", None)])
    w.project.update_mesh(curvature_levels=1)
    _settle()
    _check(w)
    w.project.undo()
    _settle()
    _check(w)
    w.compare_tab.click()  # the Compare tab
    _settle()
    _check(w)
    w.scene_tab.click()


@pytest.mark.parametrize("interface_size", SIZES, indirect=True)
def test_detached_windows_at_their_minimum(solved_window, interface_size: int) -> None:
    from vortexcfd.gui.foam_file_viewer import FoamFileViewer
    from vortexcfd.workflow import foam_entries as fe

    w = solved_window
    w.set_point_size(interface_size)
    w.show()
    w.tree.setCurrentItem(w._items[("mesh", None)])
    w.detach_properties()
    _at_minimum(w.properties_window)
    _check(w.properties_window)
    w.dock_properties()
    for key in ("residuals", "criteria"):
        window = w.detach_monitor(key)
        _at_minimum(window)
        _check(window)
        w.dock_monitor(key)
    chart = w.monitors.open_chart("Cd")  # a report chart's window (D-170)
    _at_minimum(chart)
    _check(chart)
    chart.close()
    entries = fe.entries_for(w.project, "mset_feature_angle")
    viewer = FoamFileViewer("mset_feature_angle", entries, {e: fe.case_file(w.project, e) for e in entries})
    viewer.show()
    try:
        _at_minimum(viewer)
        _check(viewer)
        from vortexcfd.gui.foam_file_viewer import MIN_TEXT_LINES

        assert viewer.text.viewport().height() >= MIN_TEXT_LINES * viewer.text.fontMetrics().lineSpacing() - 2
    finally:
        viewer.close()


def test_the_residual_legend_wraps_when_narrow(qtbot: QtBot) -> None:
    from vortexcfd.gui.monitors import ResidualChart
    from vortexcfd.gui.theme import metrics

    chart = ResidualChart()
    qtbot.addWidget(chart)
    chart.configure(metrics(), DARK)
    chart.set_series({name: [(1.0, 1.0), (2.0, 0.1)] for name in ("Ux", "Uy", "Uz", "p", "omega", "k")})
    chart.resize(1200, 400)
    chart.show()
    chart.grab()
    assert chart.legend_rows() == 1
    chart.resize(16 * metrics().u, 400)  # the monitors column at its narrowest
    chart.grab()
    assert chart.legend_rows() > 1
    right = max(x for *_, x, _row in chart._legend)
    assert right < chart.width()  # every entry starts inside the chart
    fm = chart.fontMetrics()
    for name, _c, _s, x, _row in chart._legend:  # and ends inside it
        assert x + 2 * fm.height() + fm.horizontalAdvance(name) <= chart.width()
