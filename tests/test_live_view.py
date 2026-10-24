"""Results while the solver runs (D-172): the live view (a surfaces function object sampling the walls and the Results
Scene's planes every N iterations, shown live, only the latest sample kept) and Write fields now (SIGUSR2: the fields
written at the next iteration while the run goes on; parallel: forwarded by mpirun, the written times reconstructed at
the end). Fake runners, and a plain process for the signal."""

import threading
import time
from pathlib import Path

import pytest
import pyvista as pv
from pytestqt.qtbot import QtBot

from tests.fake_solver import FakeRunner, iteration
from tests.test_continue import _write_time
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from tests.test_two_stage import _case
from vortexcfd.foam.case_writer import WRITE_NOW_SIGNAL
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.live_view import (LIVE_VIEW, WALLS, LivePlane, LiveViewSpec, function_object, latest_sample,
                                      prune, samples)
from vortexcfd.foam.runner import FoamRun
from vortexcfd.foam.solver_run import SolverRun
from vortexcfd.workflow import solving


def test_the_function_object() -> None:
    spec = LiveViewSpec(("Ball",), (LivePlane("section_y", (0.0, 0.5, 0.0), (0.0, 1.0, 0.0)),), 25)
    fo = function_object(spec)
    assert fo["type"] == "surfaces" and fo["libs"] == ["sampling"] and fo["surfaceFormat"] == "vtk"
    assert fo["writeControl"] == "timeStep" and fo["writeInterval"] == 25
    assert fo["fields"] == ["p", "U", "k", "omega", "nut"] and fo["sampleScheme"] == "cell"
    assert fo["surfaces"][WALLS] == {"type": "patch", "patches": ["Ball"], "interpolate": False}
    assert fo["surfaces"]["section_y"] == {"type": "cuttingPlane", "point": [0.0, 0.5, 0.0], "normal": [0.0, 1.0, 0.0],
                                           "interpolate": False}
    assert spec.surface_names() == (WALLS, "section_y")


def test_only_runs_from_the_app_get_the_live_view_and_write_now(make_window) -> None:
    """The benchmark and validation drivers write the plain files (prepare_solver_case(project)): their dictionaries
    do not change; a run from the app gets the live view and writeNowSignal 12 (SIGUSR2, the stop keeps SIGUSR1)."""
    w = make_window()
    w.project.add_scene_object("clip")
    case = solving.prepare_solver_case(w.project)
    plain = read_foam_file(case / "system" / "controlDict")
    assert LIVE_VIEW not in plain["functions"] and "writeNowSignal" not in plain["OptimisationSwitches"]
    planes = w._live_planes()
    case = solving.prepare_solver_case(w.project, interactive=True, planes=planes)
    control = read_foam_file(case / "system" / "controlDict")
    assert control["OptimisationSwitches"] == {"stopAtWriteNowSignal": 10, "writeNowSignal": WRITE_NOW_SIGNAL == 12
                                               and 12}
    live = control["functions"][LIVE_VIEW]
    assert live["writeInterval"] == 50 and list(live["surfaces"])[:2] == [WALLS, "section_y"]
    assert live["surfaces"]["section_y"]["normal"] == [0.0, 1.0, 0.0]
    clip = w.project.sim.results.objects[0]
    assert [k for k in live["surfaces"] if k.startswith("clip_")] == [f"clip_{clip.id}"]
    w.project.update_solver(live_view=False)  # the project setting off: no live view, Write fields now still there
    control = read_foam_file(solving.prepare_solver_case(w.project, interactive=True) / "system" / "controlDict")
    assert LIVE_VIEW not in control["functions"] and control["OptimisationSwitches"]["writeNowSignal"] == 12
    before = solving.results_hash(w.project)
    w.project.update_solver(live_view=True, live_view_interval=10)
    assert solving.results_hash(w.project) == before  # never a results input


def _sample(case: Path, it: int, names=(WALLS, "section_y")) -> None:
    folder = case / "postProcessing" / LIVE_VIEW / str(it)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        surface = pv.Sphere(radius=0.5) if name == WALLS else pv.Plane(i_resolution=4, j_resolution=4)
        surface.cell_data["p"] = [float(it)] * surface.n_cells
        surface.cell_data["U"] = [[20.0, 0.0, 0.0]] * surface.n_cells
        surface.save(str(folder / f"{name}.vtp"))


def test_the_latest_complete_sample_and_pruning(tmp_path: Path) -> None:
    assert latest_sample(tmp_path) is None
    _sample(tmp_path, 50)
    _sample(tmp_path, 100, names=(WALLS,))  # still being written: the plane not yet there
    sample = latest_sample(tmp_path, expected=(WALLS, "section_y"))
    assert sample.iteration == 50 and set(sample.files) == {WALLS, "section_y"}
    settled: dict = {}
    assert latest_sample(tmp_path, settled=settled).iteration == 50  # 100 seen once: wait for it to settle
    assert latest_sample(tmp_path, settled=settled).iteration == 100
    assert prune(tmp_path, 100) == [50] and [it for it, _p in samples(tmp_path)] == [100]


def test_the_results_scene_follows_the_live_samples(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    runner = use_runner(w, FakeRunner(iteration(1), hold=True))
    w.run_solver()
    qtbot.waitUntil(lambda: "Time = 1" in w.console.text(), timeout=5000)
    assert not w.live_badge.isVisible()
    _sample(case, 50)
    w.poll_live()  # seen once (it may still be written)
    w.poll_live()
    assert w._live_data is not None and w._live_data.live == 50 and w.live_badge.text() == "Live · iteration 50"
    assert set(w._live_data.patches) == {WALLS} and len(w._live_data.planes) == 1
    assert [f.key for f in w._live_data.fields][:2] == ["p", "Cp"] and w.results_tab.isVisibleTo(w)
    _sample(case, 100)
    w.poll_live()
    w.poll_live()
    assert w._live_data.live == 100 and w.live_badge.text() == "Live · iteration 100"
    assert [it for it, _p in samples(case)] == [100]  # only the latest sample is kept
    w.live_toggle.setChecked(False)  # not following: the badge keeps its sample
    _sample(case, 150)
    w.poll_live()
    w.poll_live()
    assert w._live_data.live == 150 and w._results_shown_time == "100"
    w.live_toggle.setChecked(True)
    assert w._results_shown_time == "150"
    runner.release(["End\n"])
    wait_done(qtbot, w)
    assert not w.live_badge.isVisible() and w._live_data is None  # the run ended: the final results take over


def test_write_fields_now_while_the_run_goes_on(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    w.write_fields_now()  # not running: nothing
    assert "not running" in w.statusBar().currentMessage()
    runner = use_runner(w, FakeRunner(iteration(1) + iteration(2), hold=True))
    runner.on_write_now = lambda: _write_time(case, 3)  # OpenFOAM writes the next iteration
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == 2, timeout=5000)
    w.write_fields_now()
    assert runner.write_now_requests == 1 and not runner.stop_requested
    w.poll_live()
    assert w._written_now == [3] and not w.live_toggle.isChecked()
    assert w.live_badge.text() == "Iteration 3 (written while running)" and w._written_decomposed is False
    assert w.solver_worker.is_running()  # the run goes on
    runner.release(iteration(3) + iteration(4) + ["End\n"])
    wait_done(qtbot, w)
    assert w.run_record.iterations == 4


def test_a_parallel_run_reads_the_written_time_decomposed(make_window, qtbot: QtBot) -> None:
    w = make_window()
    case = w.project.path.parent / "case"
    w.project.update_solver(cores=2)
    decompose, solver, reconstruct, new_times = (FakeRunner([]), FakeRunner(iteration(1), hold=True),
                                                 FakeRunner([]), FakeRunner([]))
    queue = [decompose, solver, reconstruct, new_times]
    w.solver_worker.runner_factory = lambda: queue.pop(0)
    FakeRunner.instances.extend([decompose, solver, reconstruct, new_times])
    solver.on_write_now = lambda: [_write_time(case / f"processor{r}", 2) for r in (0, 1)]  # in the ranks only
    w.run_solver()
    qtbot.waitUntil(lambda: len(w.monitors.history.series.get("p", [])) == 1, timeout=5000)
    w.write_fields_now()
    w.poll_live()
    assert w._written_now == [2] and w._written_decomposed is True  # read from the decomposed case
    solver.release(iteration(2) + ["End\n"])
    wait_done(qtbot, w)
    assert reconstruct.command == ["reconstructPar", "-latestTime"]
    assert new_times.command == ["reconstructPar", "-newTimes"]  # the written time reconstructed for ParaView
    assert new_times.append  # appended to log.reconstructPar


def test_no_write_now_no_extra_reconstruction(tmp_path: Path) -> None:
    case = _case(tmp_path / "case", two_stage=False)
    decompose, solver, reconstruct = FakeRunner([]), FakeRunner(iteration(1) + ["End\n"]), FakeRunner([])
    queue = [decompose, solver, reconstruct]
    run = SolverRun(case, runner_factory=lambda: queue.pop(0), cores=2)
    run.start()
    run.wait(10)
    assert queue == [] and reconstruct.command == ["reconstructPar", "-latestTime"]


def test_foam_run_sends_sigusr2_once_the_time_loop_runs(tmp_path: Path) -> None:
    runner = FoamRun()
    got = threading.Event()
    lines = []

    def on_line(line: str) -> None:
        lines.append(line)
        if "GOT_USR2" in line:
            got.set()

    script = 'trap "echo GOT_USR2" USR2; echo READY; sleep 0.3; echo "Time = 1"; for i in $(seq 1 100); do sleep 0.05; done'
    runner.start(["bash", "-c", script], case_dir=tmp_path, log_file=tmp_path / "log.test", on_line=on_line,
                 clean_stop=False, timeout_s=30)
    try:
        deadline = time.monotonic() + 10
        while not any("READY" in line for line in lines) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runner.request_write_now() is False  # before the time loop: not sent
        while not any(line.startswith("Time = ") for line in lines) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runner.request_write_now() is True
        assert got.wait(5) and runner.is_running()  # the process got it and goes on
    finally:
        runner.request_stop(grace_s=1.0)
        runner.wait(10)
    assert runner.request_write_now() is False  # finished
