"""Save As carries the mesh and results (D-174, amending D-079): the size shown, the copy on a background worker with
progress, the skipped folders, the duplicate's mesh and results current (they open and Continue works), today's
behaviour unticked, Cancel mid-copy removing the partial target, and the original untouched."""

import hashlib
import threading
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_continue import _stopped_at, _write_time
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from vortexcfd.foam.live_view import LIVE_VIEW
from vortexcfd.workflow import duplicate as dup
from vortexcfd.workflow import solving


def _tree(folder: Path) -> dict[str, str]:
    """Every file of a folder and its content's hash (the original must stay byte-identical)."""
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _with_extras(w) -> Path:
    """The project's folder with what a duplicate copies or leaves out besides the case."""
    folder = w.project.folder
    case = folder / "case"
    for rank in (0, 1):
        _write_time(case / f"processor{rank}", 4)  # skipped: a decomposed copy
    (case / "postProcessing" / LIVE_VIEW / "50").mkdir(parents=True)
    (case / "postProcessing" / LIVE_VIEW / "50" / "walls.vtp").write_text("sample")  # skipped: the live view
    (case / "postProcessing" / "forceCoeffs1" / "0").mkdir(parents=True)
    (case / "postProcessing" / "forceCoeffs1" / "0" / "coefficient.dat").write_text("# Time Cd\n1 0.5\n")
    (folder / "case_preview" / "system").mkdir(parents=True)
    (folder / "case_preview" / "system" / "controlDict").write_text("preview")  # skipped: scratch
    (folder / "case_study" / "level_1" / "processor0").mkdir(parents=True)
    (folder / "case_study" / "level_1" / "processor0" / "x").write_text("x")  # skipped
    (folder / "case_study" / "study.json").write_text("{}")
    (folder / "case_sweep").mkdir()
    (folder / "case_sweep" / "sweep.json").write_text("{}")
    (folder / "snapshots").mkdir()
    (folder / "snapshots" / "run_1.json").write_text("{}")
    (folder / "reports").mkdir()
    (folder / "reports" / "r.html").write_text("<html></html>")
    return folder


def test_the_copy_plan_skips_scratch(make_window, qtbot: QtBot) -> None:
    w = make_window()
    _stopped_at(w, qtbot)
    folder = _with_extras(w)
    plan = dup.copy_plan(folder)
    names = [item.relative for item in plan]
    assert "case/4/U" in names and "case/log.simpleFoam" in names and "case/vortexcfd_run.json" in names
    assert "case/vortexcfd_mesh.json" in names and "case/constant/polyMesh/points" in names
    assert "case/postProcessing/forceCoeffs1/0/coefficient.dat" in names
    assert {"case_study/study.json", "case_sweep/sweep.json", "snapshots/run_1.json", "reports/r.html"} <= set(names)
    assert not any("processor" in n or LIVE_VIEW in n or n.startswith("case_preview") for n in names)
    assert not any(n.startswith("geometry/") or n.endswith(".vcfd") for n in names)  # Project.duplicate's part
    assert dup.plan_size(plan) == sum((folder / n).stat().st_size for n in names)
    assert dup.format_size(2_300_000_000) == "2.3 GB" and dup.format_size(640_000_000) == "640 MB"
    assert dup.format_size(12_000) == "12 kB" and dup.format_size(500) == "500 bytes"


def test_save_as_with_results(make_window, qtbot: QtBot, tmp_path: Path) -> None:
    w = make_window()
    _stopped_at(w, qtbot)
    folder = _with_extras(w)
    before = _tree(folder)
    w.dialogs.duplicate_target = ("copy", tmp_path / "copies", True)
    (tmp_path / "copies").mkdir()
    assert w.save_as()
    assert w.dialogs.duplicate_sizes[-1] == dup.plan_size(dup.copy_plan(folder))  # the size shown
    qtbot.waitUntil(lambda: w.project.folder == tmp_path / "copies" / "copy", timeout=20000)
    target = tmp_path / "copies" / "copy"
    assert w.copy_progress is None  # the progress closed
    copied = _tree(target)
    assert copied["case/4/U"] == before["case/4/U"] and "case/postProcessing/forceCoeffs1/0/coefficient.dat" in copied
    assert not any("processor" in n or LIVE_VIEW in n or n.startswith("case_preview") for n in copied)
    assert not (target / "case" / "4" / "U").samefile(folder / "case" / "4" / "U")
    assert (target / "case" / "4" / "U").stat().st_nlink == 1  # a plain copy, never a hard link
    # the duplicate's mesh and results are current, and they open
    assert not w.mesh_stale and not w.results_stale and w.run_record is not None
    assert w.run_record.iterations == 4 and w.results_time() == "4"
    assert w.solver_mode() == "continue" and w.top_bar.run_button.text() == "Continue Solver"
    runner = use_runner(w, FakeRunner(iteration(5) + ["End\n"]))
    w.run_solver()  # Continue works in the duplicate
    wait_done(qtbot, w)
    assert runner.case_dir == target / "case" and w.run_record.iterations == 5
    assert [(s["first"], s["last"]) for s in w.run_record.segments] == [(1, 4), (5, 5)]
    assert _tree(folder) == before  # the original byte-identical


def test_save_as_without_results_keeps_todays_behaviour(make_window, qtbot: QtBot, tmp_path: Path) -> None:
    w = make_window()
    _stopped_at(w, qtbot)
    folder = w.project.folder
    before = _tree(folder)
    w.dialogs.duplicate_target = ("plain", tmp_path, False)
    assert w.save_as()
    target = tmp_path / "plain"
    assert w.project.folder == target and sorted(p.name for p in (target / "case").iterdir()) == []
    assert w.run_record is None and w.mesh_report is None
    assert _tree(folder) == before


def test_cancel_mid_copy_removes_the_partial_target(make_window, qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    w = make_window()
    _stopped_at(w, qtbot)
    folder = _with_extras(w)
    before = _tree(folder)
    original_path = w.project.path
    halfway = threading.Event()
    real_copy = dup.copy_files

    def slow_copy(plan, target, progress=None, cancelled=None):
        def gate():  # the first file copied, then wait until the user has cancelled
            halfway.set()
            for _ in range(500):
                if cancelled():
                    return True
                threading.Event().wait(0.01)
            return cancelled()
        return real_copy(plan, target, progress, gate)

    monkeypatch.setattr(dup, "copy_files", slow_copy)
    w.dialogs.duplicate_target = ("half", tmp_path, True)
    assert w.save_as()
    assert halfway.wait(10) and w.copy_progress is not None
    assert (tmp_path / "half").is_dir()  # being written
    from PySide6.QtWidgets import QPushButton

    next(b for b in w.copy_progress.findChildren(QPushButton) if b.text() == "Cancel").click()  # the user's Cancel
    qtbot.waitUntil(lambda: not w.copy_worker.is_running() and w.copy_progress is None, timeout=10000)
    assert not (tmp_path / "half").exists()  # the partial target removed
    assert w.project.path == original_path and "cancelled" in w.statusBar().currentMessage()
    assert _tree(folder) == before


def test_a_failed_copy_removes_the_partial_target(make_window, qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    w = make_window()
    _stopped_at(w, qtbot)
    original_path = w.project.path

    def failing(plan, target, progress=None, cancelled=None):
        (Path(target) / "case" / "partial").write_text("x")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(dup, "copy_files", failing)
    w.dialogs.duplicate_target = ("full", tmp_path, True)
    w.save_as()
    qtbot.waitUntil(lambda: w.copy_progress is None, timeout=10000)
    assert not (tmp_path / "full").exists() and w.project.path == original_path
    assert "No space left on device" in w.statusBar().currentMessage()


def test_no_copy_while_a_run_writes_into_the_case(make_window, qtbot: QtBot, tmp_path: Path) -> None:
    w = make_window()
    use_runner(w, FakeRunner(iteration(1), hold=True))
    w.run_solver()
    w.dialogs.duplicate_target = ("busy", tmp_path, True)
    assert not w.save_as()
    assert not (tmp_path / "busy").exists() and "stop it before copying" in w.statusBar().currentMessage()


def test_nothing_to_copy_disables_the_box(qtbot: QtBot, tmp_path: Path) -> None:
    from vortexcfd.gui.start_dialogs import DuplicateProjectDialog

    dialog = DuplicateProjectDialog("p", tmp_path, None, None)
    qtbot.addWidget(dialog)
    assert not dialog.copy_check.isEnabled() and not dialog.copy_check.isChecked()
    dialog = DuplicateProjectDialog("p", tmp_path, None, 2_300_000_000)
    qtbot.addWidget(dialog)
    assert dialog.copy_check.isChecked() and dialog.copy_check.text() == "Copy mesh and results (2.3 GB)"
    dialog.name_edit.setText("new_one")
    dialog.create_button.click()
    assert dialog.result_target == ("new_one", tmp_path, True)
