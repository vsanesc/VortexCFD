"""The properties panel stays readable: rows keep their height, labels never overlap fields,
every field shows its value, and the scroll area reaches the last row."""

from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QLineEdit, QSpinBox
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from vortexcfd.core.model import Part
from vortexcfd.core.project import Project
from vortexcfd.foam.mesh_report import LayerCoverage, MeshReport
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.theme import metrics


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def make_window(qtbot: QtBot, tmp_path: Path):
    made: list[MainWindow] = []

    def make(font: int, width: int = 1400, height: int = 850) -> MainWindow:
        folder = tmp_path / f"proj{len(made)}"
        (folder / "geometry").mkdir(parents=True)
        pv.Sphere(radius=0.5, theta_resolution=16, phi_resolution=16).save(str(folder / "geometry" / "ball.stl"))
        project = Project.new("layout")
        project.add_part(Part(name="Ball", source_file="geometry/ball.stl", units="m"))
        project.save(folder / "p.json")
        w = MainWindow(project, FakeDialogs(), with_viewer=False)
        qtbot.addWidget(w)
        w.set_point_size(font)
        w.resize(width, height)
        w.show()
        qtbot.waitUntil(w.isVisible)
        qtbot.wait(50)
        made.append(w)
        return w

    yield make
    for w in made:
        assert not w.project.observer_errors
        w.project.save = lambda *a, **k: None
        w.close()


def _report() -> MeshReport:
    return MeshReport(
        points=222040, faces=603889, cells=192220, max_non_orthogonality=40.2,
        avg_non_orthogonality=7.2, max_skewness=0.6, failed_checks=0, mesh_ok=True,
        layers=(LayerCoverage("Ball", 9460, 3, 2.4, 0.0211, 72.5),
                LayerCoverage("A_very_long_patch_name_that_needs_eliding", 100, 3, 3.0, 0.02, 100.0)),
        extruded_percent=96.0,
    )


NODES = ["mesh", "fluid_domain"]


def _select(w: MainWindow, kind: str) -> None:
    if kind == "mesh":
        w.properties.set_mesh_report(_report())
    w.tree.setCurrentItem(w._items[(kind, None)])
    QApplication.processEvents()  # let the scroll area lay out its scrollbars


def _visible_rows(p):
    return [(key, row) for key, row in p._rows.items() if not row.isHidden() and row.isVisible()]


def _rect(widget, panel) -> QRect:
    return QRect(widget.mapTo(panel, QPoint(0, 0)), widget.size())


@pytest.mark.parametrize("font", [11, 14])
@pytest.mark.parametrize("kind", NODES)
def test_inputs_keep_their_height_and_rows_are_not_squeezed(make_window, font: int, kind: str) -> None:
    w = make_window(font)
    _select(w, kind)
    u = metrics().u
    p = w.properties
    rows = _visible_rows(p)
    assert rows
    for key, row in rows:
        field = p._row_fields[key]
        if isinstance(field, (QLineEdit, QComboBox, QAbstractSpinBox, QCheckBox)):
            assert field.height() >= 1.5 * u, (key, field.height(), u)  # compact rows (D-148): 1.6u fields
        assert row.height() >= 2.0 * u, (key, row.height(), u)


@pytest.mark.parametrize("font", [11, 14])
@pytest.mark.parametrize("kind", NODES)
def test_no_label_overlaps_its_field(make_window, font: int, kind: str) -> None:
    w = make_window(font)
    _select(w, kind)
    p = w.properties
    for key, row in _visible_rows(p):
        label, field = p._row_labels[key], p._row_fields[key]
        lr, fr = _rect(label, p), _rect(field, p)
        assert not lr.intersects(fr), (key, lr, fr)
        assert lr.width() > 0 and fr.width() > 0
        assert label.text() and (label.text() == label.full_text() or label.text().endswith("…"))


@pytest.mark.parametrize("font", [11, 14])
def test_long_labels_are_elided_with_a_tooltip_in_the_side_by_side_layout(make_window, qtbot: QtBot, font: int) -> None:
    """With a wide panel the rows sit side by side; a label wider than the column is elided."""
    w = make_window(font, width=2600)
    w._left.setMaximumWidth(5000)  # lift the 22u cap: the column is normally too narrow for this
    w._outer.setSizes([w._outer.width() // 2, w._outer.width() // 2])
    qtbot.wait(50)
    _select(w, "mesh")
    p = w.properties
    assert not p.stacked
    u = metrics().u
    assert 9 * u <= p._label_column <= 0.55 * p.width()
    lab = p._row_labels["mset_background_cells_target"]
    assert lab.width() == p._label_column
    # Force a narrow column: the label is elided and the full text is the tooltip.
    lab.set_column_width(5 * u)
    assert lab.text().endswith("…") and lab.toolTip() == "Background cells target"
    lab.set_column_width(p._label_column)
    assert lab.text() == "Background cells target" and lab.toolTip() == ""


@pytest.mark.parametrize("font", [11, 14])
def test_default_18u_column_is_side_by_side(make_window, font: int) -> None:
    """The real space needed is 8u + 7u + margins and gap (about 17u): the default 18u fits it."""
    w = make_window(font)
    _select(w, "mesh")
    p = w.properties
    u = metrics().u
    assert abs(w._left.width() - 18 * u) <= 0.5 * u and not p.stacked
    for key, row in _visible_rows(p):
        lr, fr = _rect(p._row_labels[key], p), _rect(p._row_fields[key], p)
        assert not lr.intersects(fr) and lr.right() < fr.left(), key
        assert fr.width() >= 7 * u - 2, (key, fr.width(), u)  # the field keeps 7u
        assert lr.width() >= 8 * u - 2


@pytest.mark.parametrize("font", [11, 14])
def test_narrow_panel_stacks_label_above_field(make_window, qtbot: QtBot, font: int) -> None:
    w = make_window(font)
    u = metrics().u
    w._outer.setSizes([15 * u, w._outer.width() - 15 * u])  # below the space a row needs
    qtbot.wait(60)
    _select(w, "mesh")
    p = w.properties
    assert p.stacked
    for key, row in _visible_rows(p):
        assert _rect(p._row_labels[key], p).bottom() <= _rect(p._row_fields[key], p).top()


def _displayed(field) -> str:
    if isinstance(field, QComboBox):
        return field.currentText()
    if isinstance(field, QAbstractSpinBox):
        return field.text()
    return field.text()


@pytest.mark.parametrize("font", [11, 14])
def test_every_mesh_field_shows_its_value(make_window, font: int) -> None:
    w = make_window(font)
    _select(w, "mesh")
    p = w.properties
    mesh = w.project.sim.mesh
    for key, widget in p.mesh_fields.items():
        shown = _displayed(widget)
        assert shown, key
        model = getattr(mesh, key)
        if isinstance(widget, QComboBox):
            assert shown == model, key
        elif model is None:
            assert shown == "auto", key
        elif key == "layers" and mesh.layer_sizing == "absolute_yplus":
            # absolute sizing shows the computed count in the disabled field (D-089)
            assert not widget.isEnabled() and shown == p.mesh_layer_count.text().split()[0], (key, shown)
        else:
            assert float(widget.cleanText()) == pytest.approx(float(model)), (key, shown, model)
        assert widget.isVisible() and widget.width() >= 3 * metrics().u
        # the whole text fits inside the box
        assert widget.fontMetrics().horizontalAdvance(shown) <= widget.width(), (key, shown, widget.width())


@pytest.mark.parametrize("font", [11, 14])
def test_every_domain_field_shows_its_value(make_window, font: int) -> None:
    w = make_window(font)
    _select(w, "fluid_domain")
    p = w.properties
    domain = w.project.sim.domain
    for key, spin in p.domain_fields.items():
        assert spin.text() and float(spin.cleanText()) == pytest.approx(getattr(domain, key)), key
        assert spin.fontMetrics().horizontalAdvance(spin.text()) <= spin.width()
    assert _displayed(p.domain_symmetry) == domain.symmetry
    for ro in (p.domain_length, p.domain_size):
        assert ro.text() and ro.fontMetrics().horizontalAdvance(ro.text()) <= ro.width()


@pytest.mark.parametrize("font", [11, 14])
@pytest.mark.parametrize("kind", NODES)
def test_scrollbar_appears_and_reaches_the_last_row(make_window, font: int, kind: str) -> None:
    w = make_window(font)
    _select(w, kind)
    p = w.properties
    scroll = p._scroll
    content_h = p._content.sizeHint().height()
    viewport_h = scroll.viewport().height()
    bar = scroll.verticalScrollBar()
    assert scroll.horizontalScrollBar().maximum() == 0  # never scrolls sideways
    if content_h > viewport_h:
        assert bar.isVisible() and bar.maximum() > 0
        bar.setValue(bar.maximum())
        last = max(_visible_rows(p), key=lambda kr: kr[1].mapTo(p._content, QPoint(0, 0)).y())[1]
        bottom = last.mapTo(scroll.viewport(), QPoint(0, last.height())).y()
        assert bottom <= viewport_h + 1 and last.mapTo(scroll.viewport(), QPoint(0, 0)).y() >= 0
    else:
        assert not bar.isVisible()


def test_mesh_content_is_taller_than_the_viewport_so_scrolling_is_exercised(make_window) -> None:
    w = make_window(14)
    _select(w, "mesh")
    p = w.properties
    assert p._content.sizeHint().height() > p._scroll.viewport().height()
    assert p._scroll.verticalScrollBar().isVisible()


def test_tree_properties_split_defaults_to_40_60_and_is_restored(make_window, qtbot: QtBot) -> None:
    from PySide6.QtCore import QSettings

    w = make_window(11)
    column = w._left.height()
    tree = w._left_split.sizes()[0]
    assert abs(tree / column - 0.40) < 0.03
    # The user drags the handle: the split is saved and used by the next window.
    target = int(0.55 * column)
    w._left_split.moveSplitter(target, 1)
    w._save_left_split()
    saved = float(QSettings("VortexCFD", "VortexCFD").value("layout/left_tree_fraction"))
    assert saved == pytest.approx(w._left_split.sizes()[0] / column, abs=0.01) and saved > 0.5
    w2 = make_window(11)
    assert abs(w2._left_split.sizes()[0] / w2._left.height() - saved) < 0.03


@pytest.mark.parametrize("font", [11, 14])
@pytest.mark.parametrize("kind", NODES)
def test_side_by_side_at_24u_with_clamped_label_column_and_7u_fields(make_window, qtbot: QtBot, font: int, kind: str) -> None:
    w = make_window(font)
    u = metrics().u
    w._outer.setSizes([24 * u, w._outer.width() - 24 * u])  # a left column of 24u
    qtbot.wait(60)
    _select(w, kind)
    p = w.properties
    assert not p.stacked
    assert 8 * u <= p._label_column <= 0.5 * p.width()
    for key, row in _visible_rows(p):
        label, field = p._row_labels[key], p._row_fields[key]
        lr, fr = _rect(label, p), _rect(field, p)
        assert not lr.intersects(fr) and lr.right() < fr.left(), key  # side by side, no overlap
        assert fr.width() >= 7 * u - 1, (key, fr.width(), u)
        assert label.width() == p._label_column
        assert label.text() == label.full_text() or (label.text().endswith("…") and label.toolTip())


@pytest.mark.parametrize("font", [11, 14])
def test_threshold_is_the_real_space_a_row_needs(make_window, qtbot: QtBot, font: int) -> None:
    w = make_window(font)
    m = metrics()
    needed = (8 + 7) * m.u + 3 * m.s3  # label min + field min + row margins and gap
    _select(w, "mesh")
    p = w.properties
    for column, stacked in ((needed - 2 * m.s3, True), (needed + m.s3, False)):
        w._outer.setSizes([round(column), w._outer.width() - round(column)])
        qtbot.wait(60)
        assert p.stacked is stacked, (column, p.width(), needed)
