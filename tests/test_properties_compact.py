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


# -- mesh (G3) ------------------------------------------------------------------------------------------


def test_mesh_fields_have_units_tooltips_and_auto_boxes(make_window) -> None:
    from PySide6.QtWidgets import QAbstractSpinBox

    from vortexcfd.gui.panel_widgets import AutoField, ChoiceField

    w = make_window()
    select(w, "mesh")
    p = w.properties
    for key, widget in p.mesh_fields.items():
        assert widget.toolTip(), key  # what it does, its default and why
        spin = widget.spin if isinstance(widget, AutoField) else widget
        if isinstance(spin, QAbstractSpinBox):
            assert spin.suffix().strip(), key  # every number has its unit
    for key in ("base_size", "surface_level_min", "surface_level_max", "cores"):
        assert isinstance(p.mesh_fields[key], AutoField), key
    sizing = p.mesh_fields["layer_sizing"]
    assert isinstance(sizing, ChoiceField)
    assert [b.text() for b in sizing.buttons.values()] == ["Sized from a target y+",
                                                           "Thickness relative to the surface cell size"]
    assert p._sections["mesh_layers"].text() == "PRISM LAYERS (WALLS)"
    assert "Prism layers are thin cells" in p.mesh_layers_note.text() and p.mesh_layers_note.isVisibleTo(p)
    for row in ("mset_first_layer", "mset_layer_count", "mset_layer_expansion", "mset_layer_stack"):
        assert p._rows[row].isVisibleTo(p), row
    assert p.mesh_first_layer.text().endswith("(for y+ 50)") and " m " in p.mesh_first_layer.text()
    assert p.mesh_layer_stack.text().endswith(" m") and p.mesh_layer_expansion.text().startswith("1.")


def test_curvature_levels_are_explained_editable_and_update_the_estimate_live(make_window) -> None:
    w = make_window()
    select(w, "mesh")
    p = w.properties
    spin = p.mesh_fields["curvature_levels"]
    assert spin.value() == 2 and w.project.sim.mesh.curvature_levels == 2  # the default is kept
    assert "multiply the cells" in spin.toolTip() and "Default 2" in spin.toolTip()
    assert "bends" in p.mesh_curvature_note.text() and p.mesh_curvature_note.isVisibleTo(p)
    before = p.mesh_curvature.text()
    spin.setValue(3)  # an arrow or the wheel: committed at once, the estimate follows
    assert w.project.sim.mesh.curvature_levels == 3 and p.mesh_curvature.text() != before
    spin.setValue(0)
    assert p.mesh_curvature.text() == "off"


# -- free stream and body attitude (G4, G5) ----------------------------------------------------------------------


def test_group_fields_have_units_and_tooltips(make_window) -> None:
    from PySide6.QtWidgets import QAbstractSpinBox

    w = make_window()
    p = w.properties
    for gkind, fields in p.group_fields.items():
        for key, widget in fields.items():
            assert widget.toolTip(), (gkind, key)
            if isinstance(widget, QAbstractSpinBox) and key not in ("iterations", "write_interval"):
                assert widget.suffix().strip(), (gkind, key)
    assert w._items[("inflow", None)].text(0) == "Free stream"
    select(w, "inflow")
    labels = [p._row_labels[f"inflow_{k}"].full_text() for k in ("speed", "turbulence_intensity", "viscosity_ratio")]
    assert labels == ["Free-stream speed", "Turbulence intensity", "Viscosity ratio"]


def test_body_attitude_on_the_geometry_node(make_window) -> None:
    w = make_window()
    p = w.properties
    select(w, "geometry")
    assert p._sections["body_attitude"].isVisibleTo(p) and p._row_labels["geometry_alpha_deg"].full_text() == \
        "Angle of attack α"
    tip = p.group_fields["geometry"]["alpha_deg"].toolTip()
    assert "rotation of the parts about the y axis, nose up positive, relative to the free stream" in tip
    assert p.attitude_centre.text().startswith("(0 0 0) m \u2014 auto")  # the sphere's box centre
    w.project.update_reports(center_of_rotation=(0.25, 0.0, 0.0))
    p.refresh()
    assert p.attitude_centre.text() == "(0.25 0 0) m (set)"
    select(w, "inflow")
    assert "inflow_alpha_deg" not in p._rows  # moved out of the free stream
