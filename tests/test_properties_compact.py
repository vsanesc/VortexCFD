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
    assert [sizing.text_of(v) for v in sizing.buttons] == ["Sized from a target y+",
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


# -- domain (G6) ------------------------------------------------------------------------------------------------


def test_domain_extents_in_l_or_metres(make_window) -> None:
    w = make_window()  # a 1 m sphere: L = 1 m
    p = w.properties
    select(w, "fluid_domain")
    up = p.domain_fields["upstream"]
    assert p.domain_length.text() == "1 m: the parts' largest extent" and "largest extent" in p.domain_length.toolTip()
    assert (up.unit, up.spin.value(), up.other.text()) == ("L", 5.0, "= 5 m")
    up.unit_button.click()  # L -> m: the same extent, now stored in metres (D-157)
    assert (up.unit, up.spin.value()) == ("m", 5.0) and up.other.text().startswith("= 5 L")
    assert (w.project.sim.domain.upstream, w.project.sim.domain.units) == (5.0, {"upstream": "m"})
    up.spin.setValue(3.5)
    assert up.other.text().startswith("= 3.5 L")  # live, before the edit is committed
    up.spin.editingFinished.emit()
    assert w.project.sim.domain.upstream == pytest.approx(3.5) and w.project.sim.domain.extent_unit("upstream") == "m"
    up.unit_button.click()  # m -> mm
    assert up.unit == "mm" and up.spin.value() == pytest.approx(3500.0)
    assert w.project.sim.domain.units == {"upstream": "mm"} and w.project.sim.domain.upstream == pytest.approx(3500.0)
    up.spin.setValue(2000.0)
    up.spin.editingFinished.emit()
    assert w.project.sim.domain.upstream == pytest.approx(2000.0)
    assert "x" in p._row_labels["dom_size"].full_text() and p.domain_size.text().endswith(" m")
    up.unit_button.click()  # mm -> L: 2 m with L = 1 m
    assert (up.unit, up.spin.value()) == ("L", pytest.approx(2.0)) and w.project.sim.domain.units == {}
    w.act_undo.trigger()  # one undo step per switch
    assert w.project.sim.domain.units == {"upstream": "mm"} and up.unit == "mm"
    assert p.domain_fields["downstream"].unit == "L"


# -- probes, studies (G8 - G10) ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["1.2 0 -0.5", "(1.2, 0, -0.5)", "1.2,0,-0.5", " ( 1.2 ; 0 ; -0.5 ) ", "[1.2 0 -0.5]",
                                  "1.2\t0\t-0.5"])
def test_vector_text_is_parsed(text: str) -> None:
    from vortexcfd.gui.panel_widgets import parse_vector_text

    assert parse_vector_text(text) == (1.2, 0.0, -0.5)


@pytest.mark.parametrize("text, reason", [("1 2", "three numbers"), ("1 2 x", "'x' is not a number"),
                                          ("1 2 3 4", "three numbers"), ("1 nan 2", "finite")])
def test_bad_vector_text_says_why(text: str, reason: str) -> None:
    from vortexcfd.gui.panel_widgets import parse_vector_text

    with pytest.raises(ValueError, match=reason):
        parse_vector_text(text)


def test_probe_location_is_one_vector_field(make_window) -> None:
    from vortexcfd.gui.panel_widgets import VectorField

    w = make_window()
    select(w, "probes")
    p = w.properties
    p.probe_add.click()
    location = p.probe_widgets[0]["location"]
    assert isinstance(location, VectorField) and location.unit.text() == "m" and location.text().startswith("(")
    location.setText("(1.5, 0, 0.1)")  # pasted
    location.edit.editingFinished.emit()
    assert w.project.sim.reports.probes[0].location == (1.5, 0.0, 0.1)
    location.setText("1.5 0")
    location.edit.textEdited.emit("1.5 0")
    assert location.edit.property("invalid") is True and "three numbers" in location.edit.toolTip()
    location.edit.editingFinished.emit()
    assert w.project.sim.reports.probes[0].location == (1.5, 0.0, 0.1)  # nothing committed
    assert "Enter" not in w.statusBar().currentMessage()  # the error is on the field, not a message


def test_mesh_independence_study_is_named_and_explained(make_window) -> None:
    w = make_window()
    assert w._items[("mesh_study", None)].text(0) == "Mesh independence study"
    select(w, "mesh_study")
    p = w.properties
    assert p._sections["ms_title"].text() == "MESH INDEPENDENCE STUDY" and p._sections["ms_title"].help.isVisibleTo(p)
    note = p.ms_note.text()
    for words in ("three times", "ratio r", "GCI", "monotonically", "indicative"):
        assert words in note, words
    for widget in (p.ms_ratio, p.ms_current, p.ms_quantities, p.ms_cores, p.ms_layers, p.ms_status, *p.ms_levels):
        assert widget.toolTip(), widget


def test_polar_sweep_is_opt_in(make_window, tmp_path) -> None:
    from vortexcfd.core.project_io import migrate
    from vortexcfd.workflow.polar_sweep import sweep_readiness

    w = make_window()
    assert not w.project.sim.studies.polar.enabled  # new projects: off
    assert "enable it first" in sweep_readiness(w.project)
    menu = w.tree_menu_for(("polar_sweep", None))
    assert [a.text() for a in menu.actions()][:1] == ["Enable polar sweep"]
    menu.actions()[0].trigger()
    assert w.project.sim.studies.polar.enabled
    assert "Run polar sweep" in [a.text() for a in w.tree_menu_for(("polar_sweep", None)).actions()]
    old = migrate({"schema_version": 21, "studies": {"polar": {"mode": "list"}}})
    assert old["studies"]["polar"] == {"mode": "list", "enabled": True}  # older projects keep it offered


def test_every_editable_property_has_a_tooltip(make_window) -> None:
    """No unexplained term (D-148): every visible input row of every node says what it does."""
    from PySide6.QtWidgets import QLabel

    w = make_window()
    w.project.update_study("polar", enabled=True)
    p = w.properties
    missing = []
    for key in list(w._items):
        w.tree.setCurrentItem(w._items[key])
        for row_key, row in p._rows.items():
            field = p._row_fields[row_key]
            if row.isHidden() or isinstance(field, QLabel):  # read-only values need none
                continue
            if not field.toolTip() and not p._row_labels[row_key].toolTip():
                missing.append((key, row_key))
    assert not missing, missing


def test_every_help_anchor_is_a_heading_of_the_manual() -> None:
    import re

    from vortexcfd.gui.help_texts import PROPERTIES_CHAPTER, SECTION_HELP

    text = (Path(__file__).resolve().parent.parent / "docs" / "manual" / PROPERTIES_CHAPTER).read_text()
    anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^## (.+)$", text, re.M)}
    assert set(SECTION_HELP.values()) <= anchors, set(SECTION_HELP.values()) - anchors
