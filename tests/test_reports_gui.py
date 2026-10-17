"""Reports & Monitors node (Forces table, mass balance, y+ histogram), Probes node, report slot
options and the separation highlight (D-060, D-061), on real fixtures."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.test_solver_gui import fake_mesh, make_window  # noqa: F401 (fixture)
from vortexcfd.core.model import Part, Probe
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.wall_fields import skin_friction_along
from vortexcfd.gui.monitors import mass_warning
from vortexcfd.gui.theme import DARK

DATA = Path(__file__).parent / "data"


def _select(w, kind: str) -> None:
    w.tree.setCurrentItem(w._items[(kind, None)])


def _load(w, source: Path) -> Path:
    """Put a real run's postProcessing (and time) files into the window's case and show the run."""
    case = w.project.path.parent / "case"
    for child in source.iterdir():
        if child.name in ("postProcessing", "300", "system"):
            shutil.copytree(child, case / child.name, dirs_exist_ok=True)
    w.monitors.load_run(case, [], ("iteration_limit", (), 300))
    return case


def test_reports_node_shows_forces_mass_balance_and_yplus(make_window) -> None:
    w = make_window()
    _select(w, "reports")
    p = w.properties
    assert p.reports_empty.isVisible() and not p._forces_host.isVisible()  # no run yet
    _load(w, DATA / "breakdown_run")
    t = p.forces_table
    assert [r.name for r in t.rows] == ["All walls"]
    assert t.text("cd", "All walls") == "0.1721" and t.text("cd_pressure", "All walls") == "0.1604"
    assert t.text("cd_viscous", "All walls") == "0.01165" and t.text("x_cp", "All walls") == "-0.004023 m"
    assert p.mass_imbalance.text() == "0 % of the inlet flux" and p.mass_imbalance.property("warn") == "false"
    assert p.mass_inlet.text() == "-2419.49 m³/s"
    assert not p.reports_empty.isVisible() and p._forces_host.isVisible()


def test_yplus_histogram_on_the_reports_node(make_window) -> None:
    w = make_window()
    w.project.update_part(0, name="Sphere")  # the fixture's wall patch
    _select(w, "reports")
    _load(w, DATA / "breakdown_run")
    p = w.properties
    assert p.yplus_chart.bar_texts() == ["0.0%", "0.0%", "3.5%", "96.5%", "0.0%"]
    assert p.yplus_faces.text() == "9,460 at time 300"


def test_two_parts_columns_and_slot_options(make_window) -> None:
    w = make_window()
    w.project.add_part(Part(name="Pod", source_file="geometry/ball.stl"))
    _select(w, "reports")
    _load(w, DATA / "two_parts_run")
    t = w.properties.forces_table
    assert [r.name for r in t.rows] == ["All walls", "Ball", "Pod"]
    assert t.text("cd", "Pod") == "0.0179" and t.text("x_cp", "Ball") == "undefined"
    labels = [a.text() for a in w.monitors.kpis.slot_actions(1)]
    assert "Cd (Pod)" in labels and "x_cp (m) (Ball)" in labels
    next(a for a in w.monitors.kpis.slot_actions(1) if a.text() == "Cd viscous (Ball)").trigger()
    assert w.project.sim.reports.slots[0] == "Cd_viscous@Ball"
    assert w.monitors.kpis.values[1].text() == "0.004405"
    w.project.remove_part(1)  # Pod removed: the Ball slot stays, flagged as not available
    labels = [a.text() for a in w.monitors.kpis.slot_actions(1)]
    assert "Cd viscous (Ball) (not available)" in labels and "Cd (Pod)" not in labels


def test_probes_node_add_edit_remove_and_slots(make_window) -> None:
    w = make_window()
    _select(w, "probes")
    p = w.properties
    assert p.probes_empty.isVisible()
    p.probe_add.click()
    (probe,) = w.project.sim.reports.probes
    assert probe.name == "probe1" and probe.location[0] > 0.5  # downstream of the part
    assert w.project.undo_label == "Edit reports (probes)"
    row = p.probe_widgets[0]
    row["name"].setText("wake")
    row["name"].editingFinished.emit()
    p.probe_widgets[0]["location"].setText("1.5, 0, 0.1")
    p.probe_widgets[0]["location"].editingFinished.emit()
    assert w.project.sim.reports.probes == [Probe(name="wake", location=(1.5, 0.0, 0.1))]
    p.probe_widgets[0]["name"].setText("1bad")  # rejected: reverted with a message
    p.probe_widgets[0]["name"].editingFinished.emit()
    assert w.project.sim.reports.probes[0].name == "wake" and p.probe_widgets[0]["name"].text() == "wake"
    assert "probe name" in w.statusBar().currentMessage()
    p.probe_widgets[0]["location"].setText("1 2")
    p.probe_widgets[0]["location"].editingFinished.emit()
    assert w.project.sim.reports.probes[0].location == (1.5, 0.0, 0.1)
    labels = [a.text() for a in w.monitors.kpis.slot_actions(2)]
    assert "Probe wake p" in labels and "Probe wake |U|" in labels
    _select(w, "stopping")
    p.stop_add_asymptotic.click()
    combo = p.criterion_widgets[-1]["quantity"]
    assert "Probe wake U" in [combo.itemText(i) for i in range(combo.count())]
    _select(w, "probes")
    p.probe_add.click()
    assert [x.name for x in w.project.sim.reports.probes] == ["wake", "probe1"]
    p.probe_widgets[0]["remove"].click()
    assert [x.name for x in w.project.sim.reports.probes] == ["probe1"]


def test_probe_values_reach_a_slot(make_window) -> None:
    w = make_window()
    w.project.update_reports(probes=[Probe(name="wake", location=(1.5, 0, 0)).model_dump()],
                             slots=["probe:wake:p", "probe:wake:Ux", "mass_imbalance"])
    _load(w, DATA / "breakdown_run")
    values = w.monitors.kpis.values
    assert (values[1].text(), values[2].text(), values[3].text()) == ("20.41", "13.97", "0")


def test_mass_imbalance_warning_in_the_monitors(make_window) -> None:
    w = make_window()
    case = _load(w, DATA / "breakdown_run")
    assert not any("Mass" in label.text() for label in w.monitors.convergence.warnings)  # 0 %
    outlet = case / "postProcessing/massFlow_outlet/0/surfaceFieldValue.dat"
    with open(outlet, "a") as fh:  # a later iteration that loses 0.2 % of the inflow
        fh.write("301\t2.414648e+03\n")
    with open(case / "postProcessing/massFlow_inlet/0/surfaceFieldValue.dat", "a") as fh:
        fh.write("301\t-2.419487e+03\n")
    w.monitors._dirty = True
    w.monitors.refresh()
    texts = [label.text() for label in w.monitors.convergence.warnings]
    assert mass_warning(100 * (-2419.487 + 2414.648) / 2419.487) in texts
    assert texts[-1].startswith("Mass imbalance -0.2% of the inlet flux (above 0.1%)")


@pytest.fixture
def plotter(qtbot: QtBot):
    from pyvistaqt import QtInteractor

    qi = QtInteractor(auto_update=False)
    qtbot.addWidget(qi)
    yield qi
    qi.close()


def test_separation_highlight_draws_the_cf_x_negative_faces(plotter) -> None:
    from vortexcfd.foam.results import FIELDS_BY_KEY
    from vortexcfd.gui.results_scene import ResultsData, ResultsView

    wall = pv.read(str(DATA / "breakdown_run" / "sphere_wall.vtp"))
    view = ResultsView(plotter, DARK)
    view.u_ref = 20.0
    view.set_data(ResultsData(Path("."), "300", [FIELDS_BY_KEY[k] for k in ("p", "Cp", "Cf", "Cf_x")],
                              {"Sphere": wall}))
    assert view.can_show_separation and view.separated_fraction() == pytest.approx(2200 / 9460)
    assert view.separation_actors == []
    view.configure(highlight_separation=True, field_key="Cf_x")
    (actor,) = view.separation_actors
    assert actor.GetMapper().GetInput().GetNumberOfCells() == 2200
    assert np.allclose(actor.GetProperty().GetColor(), pv.Color(DARK.error).float_rgb)
    cfx = skin_friction_along(wall.cell_data["wallShearStress"], (1, 0, 0), 20.0)
    assert view.field_range() == pytest.approx((cfx.min(), cfx.max()))
    view.configure(highlight_separation=False)
    assert view.separation_actors == []
