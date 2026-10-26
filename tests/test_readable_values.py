"""Readable values and units everywhere (D-166): no internal identifier (snake_case or camelCase) among the values the
properties panel, the tree, the report and the snapshot comparisons show, and every numeric field with its unit unless
it is on the dimensionless list below."""

import html
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from pytestqt.qtbot import QtBot

from tests.fakes import FakeDialogs
from tests.test_internal_flow import pipe_project
from tests.test_report import solved_project
from tests.value_check import identifiers, numeric_inputs, shown_values
from vortexcfd.core.labels import VALUE_LABELS, setup_label, setup_value, value_label
from vortexcfd.core.model import (AsymptoticCriterion, BoxShape, MeanStableCriterion, Probe, RefinementVolume,
                                  ResidualCriterion)
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow

# Symbols the app and the manual use for named quantities (not identifiers of the code).
SYMBOLS = {"l_ref", "A_ref", "U_ref", "x_cp", "Cf_x", "y_min"}
# Rows that show what is written to OpenFOAM, in OpenFOAM's own words (the boundary conditions, locationInMesh).
OPENFOAM_ROWS = {"Conditions written", "Boundary conditions", "Kept side"}
OPENFOAM_WORDS = {"checkMesh", "snappyHexMesh", "simpleFoam", "locationInMesh"}
# The numeric fields that have no unit, and why.
DIMENSIONLESS = {
    "Threshold": "a residual criterion's threshold on the normalised initial residual",
    "Tolerance": "a relative tolerance (a share of the mean)",
    "Scale floor": "dimensionless for a force or moment coefficient (a probe's floor shows its unit)",
    "Value": "an isosurface of a dimensionless field (Cp); other fields show their unit",
    "Range minimum": "the colour range of a dimensionless field",
    "Range maximum": "the colour range of a dimensionless field",
    "Target y+": "y+ is dimensionless",
    "Expansion ratio": "a ratio of layer thicknesses",
    "Refinement ratio r": "a ratio of cell sizes",
    "Ratio r": "a ratio of cell sizes",
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def _flush() -> None:
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _rich_project(tmp_path: Path):
    """An external project with every kind of node: results, criteria of each kind, a probe, a refinement volume,
    the results scene objects and a saved view."""
    project = solved_project(tmp_path)
    project.update_domain(enabled=True)
    stop = project.sim.solvers.stopping.model_dump()
    stop["criteria"] += [ResidualCriterion(field="p", threshold=1e-4).model_dump(),
                         AsymptoticCriterion(quantity="CmPitch").model_dump(),
                         MeanStableCriterion(quantity="probe:wake:p", floor=1.0).model_dump()]
    project.update_reports(probes=[Probe(name="wake", location=(2.0, 0.0, 0.0)).model_dump()])
    project.update_solver(stopping=stop)
    project.add_refinement_volume(RefinementVolume(id="v1", name="box_1", shape=BoxShape(), target_size=0.01))
    for kind in ("clip", "isosurface", "streamlines", "line_plot"):
        project.add_scene_object(kind)
    project.add_view("front", position=(1.0, 0.0, 0.0), focal_point=(0.0, 0.0, 0.0), view_up=(0.0, 0.0, 1.0))
    project.save()
    return project


def _names(project) -> set[str]:
    """The user's own names (parts, patches, volumes, probes, scene objects), which may be snake_case."""
    sim = project.sim
    names = {p.name for p in sim.geometry.parts} | {v.name for v in sim.refinement_volumes}
    names |= {p.name for p in sim.reports.probes} | {o.name for o in sim.results.objects}
    names |= {b.patch for b in sim.boundaries}
    return names


@pytest.mark.parametrize("kind", ["external", "internal"])
def test_every_node_shows_readable_values_with_units(qtbot: QtBot, tmp_path: Path, kind: str) -> None:
    project = _rich_project(tmp_path) if kind == "external" else pipe_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    allowed = SYMBOLS | OPENFOAM_WORDS | _names(project)
    problems = []
    for key, item in list(w._items.items()):
        w.tree.setCurrentItem(item)
        _flush()
        node = f"{key[0]}"
        for word in identifiers(item.text(0), allowed):  # the tree's own label
            problems.append(f"tree {node}: {word!r} in {item.text(0)!r}")
        for shown in shown_values(w.properties, node):
            if shown.row in OPENFOAM_ROWS:
                continue
            for word in identifiers(shown.text, allowed):
                problems.append(f"{node} / {shown.row or '(no row)'} ({shown.kind}): {word!r} in {shown.text!r}")
        for row, widget, unit in numeric_inputs(w.properties):
            if not unit and row not in DIMENSIONLESS:
                problems.append(f"{node} / {row}: a number without a unit ({type(widget).__name__})")
    assert problems == []
    w.project.save = lambda *a, **k: None
    w.close()


def test_the_choice_boxes_show_labels_and_keep_the_model_values(qtbot: QtBot, tmp_path: Path) -> None:
    project = _rich_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    p = w.properties
    w.tree.setCurrentItem(w._items[("physics", None)])
    fields = p.group_fields["physics"]
    flow, model = fields["flow"], fields["turbulence_model"]  # choices since transient flow (D-181)
    assert flow.text_of(flow.value()) == "Incompressible, steady" and flow.value() == "incompressible_steady"
    assert model.text_of(model.value()) == "k-ω SST"
    w.tree.setCurrentItem(w._items[("physics", None)])
    nu = fields["nu"]
    assert nu.unit() == "m²/s" and nu._unit.isVisibleTo(p)  # the kinematic viscosity shows its unit
    assert nu.textMargins().right() > 0  # the typed text never runs under the unit
    w.tree.setCurrentItem(w._items[("stopping", None)])
    assert p.stop_combine.currentText() == "All" and p.stop_combine.currentData() == "all"
    floors = [row["floor"].unit() for row in p.criterion_widgets if "floor" in row]
    assert floors == ["", "", "m²/s²"]  # Cd, Cm: dimensionless; a probe's p: kinematic pressure
    w.project.save = lambda *a, **k: None
    w.close()


def test_the_report_and_the_comparisons_show_labels(tmp_path: Path) -> None:
    from vortexcfd.workflow import report

    project = _rich_project(tmp_path)
    text = report.build_report(project, [])
    body = re.sub(r"<style.*?</style>|src=\"data:[^\"]*\"", "", text, flags=re.S)
    plain = html.unescape(re.sub(r"<[^>]+>", "\n", body))
    found = [w for line in plain.splitlines() for w in identifiers(line, SYMBOLS | OPENFOAM_WORDS | _names(project))]
    assert found == []
    assert "Incompressible, steady RANS, k-ω SST" in plain
    # the set-up comparison: the snapshots keep the identifiers, the rows show labels
    assert setup_label("physics: turbulence_model") == "Physics: Turbulence model"
    assert setup_value("physics: turbulence_model", "kOmegaSST") == "k-ω SST"
    assert setup_value("solver: stopping", "residual p; mean_stable Cd") == "p residual; Cd mean stable"
    assert setup_value("analysis", "external, 2d") == "External flow, 2D section (x-z plane)"
    assert setup_value("domain: inlet type", "velocity_inlet") == "Velocity inlet"
    assert setup_label("mesh: background_cells_target") == "Mesh: Background cells"


def test_every_value_label_is_readable() -> None:
    for field, labels in VALUE_LABELS.items():
        for value, label in labels.items():
            assert identifiers(label, SYMBOLS) == [], (field, value, label)
            assert value_label(field, value) == label
