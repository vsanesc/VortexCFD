"""Screen layouts (D-155): at the minimum window size and at each interface size, no two visible widgets overlap and
no label's text is clipped (tests/layout_check.py)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.layout_check import clipped_labels
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
