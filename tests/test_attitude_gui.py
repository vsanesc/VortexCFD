"""The angle of attack is easy to find (D-167): said and linked in the Free stream, shown on the Geometry node, and the
Body attitude group says what it turns."""

from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_internal_flow import pipe_project
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.properties_panel import ALPHA_LINK


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path):
    (tmp_path / "geometry").mkdir()
    pv.Sphere(radius=0.5).save(str(tmp_path / "geometry" / "ball.stl"))
    project = Project.new("s")
    project.add_part(Part(name="ball", source_file="geometry/ball.stl"))
    project.update_domain(enabled=True)
    project.save(tmp_path / "s.vcfd")
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.show()
    yield w
    w.project.save = lambda *a, **k: None
    w.close()


def _select(w: MainWindow, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


def test_the_free_stream_says_where_the_angle_is_set_and_links_to_it(window: MainWindow) -> None:
    w, p = window, window.properties
    _select(w, "inflow")
    assert p._rows["inflow_alpha"].isVisibleTo(p)
    assert p.inflow_alpha.text() == f"α = 0° (set in <a href=\"{ALPHA_LINK}\">Geometry → Body attitude</a>)"
    assert "Geometry > Body attitude" in p.inflow_alpha.toolTip()
    p.inflow_alpha.linkActivated.emit(ALPHA_LINK)  # the link selects the Geometry node and its Body attitude
    assert w._selection == ("geometry", None)
    assert p._rows["geometry_alpha_deg"].isVisibleTo(p) and p._sections["body_attitude"].isVisibleTo(p)
    w.project.update_inflow(alpha_deg=4.0)
    _select(w, "inflow")
    assert p.inflow_alpha.text().startswith("α = 4° (set in")


def test_the_geometry_node_shows_a_non_zero_angle(window: MainWindow) -> None:
    w = window
    assert w._items[("geometry", None)].text(0) == "Geometry"
    w.project.update_inflow(alpha_deg=4.0)
    assert w._items[("geometry", None)].text(0) == "Geometry · α 4°"
    w.project.update_inflow(alpha_deg=-2.5)
    assert w._items[("geometry", None)].text(0) == "Geometry · α -2.5°"
    w.project.update_inflow(alpha_deg=0.0)
    assert w._items[("geometry", None)].text(0) == "Geometry"


def test_the_body_attitude_group_says_all_parts_rotate_about_the_centre(window: MainWindow) -> None:
    w, p = window, window.properties
    for kind in ("geometry", "parts"):
        _select(w, kind)
        header = p._sections["body_attitude"]
        assert header.title.text() == "BODY ATTITUDE (ALL PARTS)"
        assert "every part" in header.toolTip() and "centre of rotation" in header.toolTip()
        assert p.attitude_note.isVisibleTo(p) and "rotate together" in p.attitude_note.text()
        assert p._rows["geometry_centre"].isVisibleTo(p)
    _select(w, "inflow")
    assert not p.attitude_note.isVisibleTo(p)


def test_internal_flow_has_no_angle_of_attack(qtbot: QtBot, tmp_path: Path) -> None:
    w = MainWindow(pipe_project(tmp_path), FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.project.update_inflow(alpha_deg=3.0)  # left from an external set-up: never shown for internal flow
    assert w._items[("geometry", None)].text(0) == "Geometry"
    _select(w, "geometry")
    assert not w.properties.attitude_note.isVisibleTo(w.properties)
    w.project.save = lambda *a, **k: None
    w.close()
