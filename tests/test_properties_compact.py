"""The properties panel after the GUI overhaul (D-148): collapsible sections remembered per node type, the "?" help,
the detachable panel, and the field widgets (Auto checkbox, vector field, L / physical length)."""

from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made = []

    def make() -> MainWindow:
        folder = tmp_path / f"proj{len(made)}"
        (folder / "geometry").mkdir(parents=True)
        pv.Sphere(radius=0.5).save(str(folder / "geometry" / "ball.stl"))
        project = Project.new("Demo")
        project.add_part(Part(name="ball", source_file="geometry/ball.stl", units="m"))
        project.update_domain(enabled=True)
        project.save(folder / "p.vcfd")
        w = MainWindow(project, FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.resize(1400, 900)
        w.show()
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def select(w: MainWindow, kind: str, index=None) -> None:
    w.tree.setCurrentItem(w._items[(kind, index)])


def test_sections_collapse_and_are_remembered_per_node_type(make_window) -> None:
    w = make_window()
    p = w.properties
    select(w, "mesh")
    sizing = p._sections["mesh_sizing"]
    assert p._rows["mset_background_cells_target"].isVisibleTo(p)
    sizing.toggle()
    assert sizing.collapsed and not p._rows["mset_background_cells_target"].isVisibleTo(p)
    assert p._rows["mset_surface_level_min"].isVisibleTo(p) or p._sections["mesh_refinement"].collapsed
    select(w, "fluid_domain")  # another node type keeps its own sections open
    assert p._rows["dom_upstream"].isVisibleTo(p)
    select(w, "mesh")
    assert p._sections["mesh_sizing"].collapsed and not p._rows["mset_background_cells_target"].isVisibleTo(p)
    w2 = make_window()  # remembered (QSettings)
    select(w2, "mesh")
    assert w2.properties._sections["mesh_sizing"].collapsed
    w2.properties._sections["mesh_sizing"].toggle()
    assert w2.properties._rows["mset_background_cells_target"].isVisibleTo(w2.properties)


def test_help_opens_the_manual_section(make_window) -> None:
    w = make_window()
    select(w, "mesh")
    header = w.properties._sections["mesh_layers"]
    assert header.help.isVisibleTo(w.properties)
    targets = []
    w.properties.help_requested.connect(targets.append)
    header.help.click()
    assert targets == ["09_properties_reference.md#prism-layers"]
    urls = []
    path = w.open_manual(opener=lambda url: urls.append(url) or True, section=targets[0])
    assert path.name == "09_properties_reference.md" and urls[0].fragment() == "prism-layers"


def test_the_panel_detaches_and_docks_back(make_window, qtbot: QtBot) -> None:
    w = make_window()
    section = w._props_section
    w.detach_button.click()
    assert w.properties_window is not None and section.window() is w.properties_window
    assert w.properties_window.isVisible() and w._left_split.count() == 1
    select(w, "mesh")  # still follows the selection
    assert w.properties._kind == "mesh"
    w.properties_window.close()  # closing the window docks the panel back
    assert w.properties_window is None and section.window() is w and w._left_split.count() == 2
    w.toggle_properties_window()
    w.toggle_properties_window()
    assert section.window() is w
