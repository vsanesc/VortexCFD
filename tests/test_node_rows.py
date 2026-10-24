"""Stopping criteria removed by the user and the rows of the properties panel (D-165).

a) A removed criterion leaves the project, the saved file, the panel and the monitors; the monitors show a run's own
   criteria as "Criteria of the last run", apart from the project's current ones.
b) Only the selected node's rows are visible, whichever node was shown before, even when a part of the refresh fails.
"""

import json
import logging
from pathlib import Path

import pytest
import pyvista as pv
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.fakes import FakeDialogs
from tests.test_internal_flow import pipe_project
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.core.model import AsymptoticCriterion, MeanStableCriterion, Part, Probe, ResidualCriterion
from vortexcfd.core.project import Project
from vortexcfd.foam.run_record import read_run_record, record_stopping, write_run_record
from vortexcfd.geometry.loader import clear_cache
from vortexcfd.gui.main_window import MainWindow
from vortexcfd.gui.monitors import BANNER_NO_RUN, CAPTION_LAST_RUN, CAPTION_RUNNING, CAPTION_UNRECORDED
from vortexcfd.gui.properties_panel import STOPPING_ROWS


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def _flush() -> None:
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _select(w: MainWindow, key) -> None:
    w.tree.setCurrentItem(w._items[key])
    _flush()


# -- a) removed criteria -------------------------------------------------------------------------------------


def test_removing_criteria_one_by_one_reaches_the_project_the_file_the_panel_and_the_monitors(make_window) -> None:
    w = make_window()
    p, box = w.properties, w.monitors.convergence
    _select(w, ("stopping", None))
    p.stop_add_asymptotic.click()
    names = ["p residual", "U residual", "k residual", "omega residual", "Cd asymptotic"]
    path = w.project.path
    while names:
        p.criterion_widgets[0]["remove"].click()
        _flush()
        names.pop(0)
        stop = w.project.sim.solvers.stopping
        assert len(stop.criteria) == len(names) == len(p.criterion_widgets)
        assert sum(r.isVisibleTo(p) for r in p._criteria_rows) == len(p._criteria_rows) > 0 or not names
        assert w.monitors.project_stopping == stop  # the monitors follow the project at once
        assert w.save()
        saved = json.loads(Path(w.project.path).read_text())["solvers"]["stopping"]["criteria"]
        assert len(saved) == len(names)
        if names:  # no run yet: the project's criteria, said to be the project's
            assert box.note.text() == ("The project's stopping criteria (they apply to the next run): "
                                       + "; ".join(names) + ".")
        assert box.banner.text() == BANNER_NO_RUN or not names
    assert p.stop_empty.isVisibleTo(p) and not p._criteria_rows
    assert not box.isVisible()  # nothing to show: no run and no criteria
    reopened = Project.open(w.project.path)
    assert reopened.sim.solvers.stopping.criteria == []
    assert path.parent == w.project.path.parent


def test_the_monitors_keep_the_last_runs_criteria_apart_from_the_projects(make_window, qtbot: QtBot) -> None:
    w = make_window()
    box = w.monitors.convergence
    stop = w.project.sim.solvers.stopping.model_dump()
    stop["criteria"] = [ResidualCriterion(field="p", threshold=1e-3).model_dump(),
                        AsymptoticCriterion(quantity="Cd", window=20).model_dump()]
    w.project.update_solver(stopping=stop)
    runner = use_runner(w, FakeRunner(iteration(1) + iteration(2), hold=True, stop_lines=iteration(3) + ["End\n"]))
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == 2, timeout=20000)
    w.monitors.refresh()
    assert box.caption.text() == CAPTION_RUNNING and box.note.text() == ""
    _select(w, ("stopping", None))
    w.properties.criterion_widgets[1]["remove"].click()  # removed during the run: the run keeps its criteria
    _flush()
    assert [r[0] for r in box.statuses_text] == ["p residual", "Cd asymptotic"]
    assert box.note.text() == ("The project's stopping criteria have changed during this run: now p residual. They "
                               "apply to the next run.")
    w.run_solver()  # Stop
    wait_done(qtbot, w)
    assert runner.stop_requested
    assert box.caption.text() == CAPTION_LAST_RUN
    assert [r[0] for r in box.statuses_text] == ["p residual", "Cd asymptotic"]
    assert "since this run: now p residual" in box.note.text()
    record = read_run_record(w.project.path.parent / "case")
    assert [c.kind for c in record_stopping(record).criteria] == ["residual", "asymptotic"]
    _select(w, ("solvers", None))  # the Solvers node says which criteria the last run used
    assert w.properties.run_criteria.text().splitlines() == list(record.criteria)
    # reopened: still the last run's criteria, apart from the project's
    w._load_run_record(w.project)
    assert box.caption.text() == CAPTION_LAST_RUN
    assert [r[0] for r in box.statuses_text] == ["p residual", "Cd asymptotic"]
    assert "now p residual" in box.note.text()
    # the project's criteria back to the run's: no note
    w._undo()
    _flush()
    assert box.note.text() == "" and not box.note.isVisible()


def test_a_record_without_its_criteria_shows_the_projects_labelled_so(make_window) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    old = {"state": "iteration_limit", "iterations": 2, "final_residuals": {}, "inputs_hash": "x", "exit_code": 0,
           "criteria": ["p initial residual < 0.0001"]}
    (case / "vortexcfd_run.json").write_text(json.dumps(old))
    w._load_run_record(w.project)
    box = w.monitors.convergence
    assert w.run_record.stopping is None
    assert box.caption.text() == CAPTION_UNRECORDED
    assert [r[0] for r in box.statuses_text][0] == "p residual"


def test_a_run_without_criteria_says_so_when_the_project_has_some(make_window, qtbot: QtBot) -> None:
    w = make_window()
    w.project.update_solver(stopping={"criteria": []})
    use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.run_solver()
    wait_done(qtbot, w)
    w.project.update_solver(stopping={"criteria": [ResidualCriterion(field="p", threshold=1e-4).model_dump()]})
    box = w.monitors.convergence
    assert box.banner.text() == "Iteration limit reached; this run had no stopping criteria"
    assert box.note.text() == ("The project's stopping criteria have changed since this run: now p residual. They "
                               "apply to the next run.")


def test_run_solver_saves_the_project_first(make_window, qtbot: QtBot) -> None:
    """The results on disk belong to the saved set-up (D-165): an unsaved edit is saved before the run starts."""
    w = make_window()
    w.project.update_solver(write_interval=50)
    assert w.project.dirty
    use_runner(w, FakeRunner(iteration(1) + ["End\n"]))
    w.run_solver()
    assert not w.project.dirty
    assert json.loads(Path(w.project.path).read_text())["solvers"]["write_interval"] == 50
    wait_done(qtbot, w)


# -- b) only the selected node's rows ----------------------------------------------------------------------------


def visible_rows(p) -> list[str]:
    """The panel's visible rows in order: row keys, section keys, label texts and other widgets by type."""
    keys = {id(r): k for k, r in p._rows.items()}
    sections = {id(s): k for k, s in p._sections.items()}
    out = []
    for widget in p._layout_widgets():
        if not widget.isVisibleTo(p._content):
            continue
        if id(widget) in keys:
            out.append(f"row:{keys[id(widget)]}")
        elif id(widget) in sections:
            out.append(f"section:{sections[id(widget)]}")
        elif isinstance(widget, QLabel):
            out.append(f"label:{widget.text()}")
        else:
            labels = [lab for lab in widget.findChildren(QLabel) if lab.isVisibleTo(widget)]
            first = labels[0] if labels else None
            text = "" if first is None else first.full_text if isinstance(first.full_text, str) else first.text()
            out.append(f"{type(widget).__name__}:{text}")
    return out


def _sphere_project(tmp_path: Path) -> Project:
    folder = tmp_path / "sphere"
    (folder / "geometry").mkdir(parents=True)
    pv.Sphere(radius=0.5, theta_resolution=12, phi_resolution=12).save(str(folder / "geometry" / "ball.stl"))
    project = Project.new("Demo")
    project.add_part(Part(name="ball", source_file="geometry/ball.stl", units="m"))
    project.update_domain(enabled=True)
    stop = project.sim.solvers.stopping.model_dump()
    stop["criteria"] += [AsymptoticCriterion(quantity="Cd").model_dump(),
                         MeanStableCriterion(quantity="Cl").model_dump()]
    project.update_solver(stopping=stop)
    project.update_reports(probes=[Probe(name="wake", location=(2.0, 0.0, 0.0)).model_dump()])
    project.save(folder / "p.vcfd")
    return project


@pytest.mark.parametrize("kind", ["external", "internal"])
def test_every_node_shows_only_its_own_rows_whichever_node_came_before(qtbot: QtBot, tmp_path: Path, kind) -> None:
    project = _sphere_project(tmp_path) if kind == "external" else pipe_project(tmp_path)
    w = MainWindow(project, FakeDialogs(), with_viewer=False)
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    nodes = list(w._items)
    p = w.properties
    own = {}
    for key in nodes:  # each node reached from the project node
        _select(w, ("root", None))
        _select(w, key)
        own[key] = visible_rows(p)
    stopping = [k for k in nodes if k[0] == "stopping"]
    heavy = stopping + [k for k in nodes if k[0] in ("mesh", "reports", "probes", "internal_reports", "fluid_domain",
                                                        "mesh_study", "part", "internal_patch")]
    for before in heavy:
        for key in nodes:
            _select(w, before)
            _select(w, key)
            assert visible_rows(p) == own[key], f"{key} after {before}"
    for key in nodes:  # the tree walked in order and back
        _select(w, key)
        assert visible_rows(p) == own[key], key
    for key in reversed(nodes):
        _select(w, key)
        assert visible_rows(p) == own[key], key
    for key in (k for k in nodes if k[0] in ("physics", "inflow")):  # the owner's report: none of the stopping rows
        _select(w, ("stopping", None))
        _select(w, key)
        assert not any(p._rows[r].isVisibleTo(p) for r in STOPPING_ROWS)
        assert not any(row.isVisibleTo(p) for row in p._criteria_rows)
        assert not p._sections["stop_criteria"].isVisibleTo(p) and not p.stop_add.isVisibleTo(p)
    w.project.save = lambda *a, **k: None
    w.close()


def test_a_failing_part_of_the_refresh_leaves_no_rows_of_the_previous_node(make_window, monkeypatch,
                                                                            caplog) -> None:
    w = make_window()
    p = w.properties
    _select(w, ("stopping", None))
    assert p._rows["stop_combine"].isVisibleTo(p) and p._criteria_rows

    def broken(*_args):
        raise RuntimeError("broken refresher")

    monkeypatch.setattr(p, "_refresh_stopping", broken)  # it would have hidden the stopping rows
    with caplog.at_level(logging.ERROR):
        _select(w, ("physics", None))
    assert not any(p._rows[r].isVisibleTo(p) for r in STOPPING_ROWS)
    assert not any(row.isVisibleTo(p) for row in p._criteria_rows)
    assert p._rows["physics_nu"].isVisibleTo(p)  # the rest of the node is shown
    assert "broken failed on the physics node" in caplog.text


def test_a_recorded_run_keeps_its_criteria_in_the_record(tmp_path: Path) -> None:
    from vortexcfd.foam.run_record import RunRecord
    from vortexcfd.core.model import StoppingCriteria

    stop = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-3)])
    write_run_record(tmp_path, RunRecord("iteration_limit", 5, stopping=stop.model_dump()))
    assert record_stopping(read_run_record(tmp_path)) == stop
    write_run_record(tmp_path, RunRecord("iteration_limit", 5))
    assert "stopping" not in json.loads((tmp_path / "vortexcfd_run.json").read_text())
    assert record_stopping(read_run_record(tmp_path)) is None
