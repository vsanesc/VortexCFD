"""Parallel solver runs (D-063): decomposeParDict, the mpirun command, the decomposePar summary,
the decompose -> solve -> reconstruct sequence (fake runners), the session sweep of the runner
and, on real OpenFOAM, serial against 4 cores and the clean stop in parallel."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.fake_solver import FakeRunner, iteration
from tests.test_solver_gui import make_window  # noqa: F401 (fixture)
from vortexcfd.core.model import Inflow, Physics, Solvers, StoppingCriteria
from vortexcfd.foam.parallel import (
    CELLS_PER_CORE,
    METHOD,
    decompose_par_dict,
    parse_decomposition,
    physical_cores,
    processor_dirs,
    recommended_cores,
    solver_command,
)
from vortexcfd.foam.solver_run import CRASHED, ITERATION_LIMIT, STOPPED, SolverRun

DATA = Path(__file__).parent / "data"
FOAM_SRC = Path("/usr/lib/openfoam/openfoam2606/src")


def test_decompose_par_dict_and_commands() -> None:
    spec = decompose_par_dict(4)
    assert spec.content == {"numberOfSubdomains": 4, "method": "scotch"} and spec.class_name == "dictionary"
    with pytest.raises(ValueError):
        decompose_par_dict(1)
    assert solver_command("simpleFoam", 1) == ["simpleFoam"]
    assert solver_command("simpleFoam", 4, "default") == ["mpirun", "-np", "4", "simpleFoam", "-parallel"]
    assert solver_command("simpleFoam", 4, "core") == ["mpirun", "-np", "4", "--bind-to", "core", "--map-by", "core",
                                                       "simpleFoam", "-parallel"]
    assert solver_command("simpleFoam", 1, "core") == ["simpleFoam"]


def test_recommended_cores() -> None:
    """min(physical cores, cells / 50,000 rounded down, 4), at least 1 (D-064: the measured
    efficient range ends at 4 ranks)."""
    assert recommended_cores(192_220, 12) == 3
    assert recommended_cores(1_000_000, 12) == 4
    assert recommended_cores(1_000_000, 2) == 2
    assert recommended_cores(1_000_000, 12, efficient=12) == 12
    assert recommended_cores(10_000, 12) == 1
    assert recommended_cores(0, 12) == 1
    assert CELLS_PER_CORE == 50_000
    assert solver_command("simpleFoam", 4) == ["mpirun", "-np", "4", "simpleFoam", "-parallel"]  # default binding


@pytest.mark.skipif(not FOAM_SRC.is_dir(), reason="OpenFOAM v2606 sources not installed")
def test_decompose_par_dict_uses_the_v2606_keywords() -> None:
    method = (FOAM_SRC / "parallel/decompose/decompositionMethods/decompositionMethod/decompositionMethod.C").read_text()
    for key in decompose_par_dict(2).content:
        assert f'"{key}"' in method, key
    assert f'TypeName("{METHOD}")' in (FOAM_SRC / "parallel/decompose/scotchDecomp/scotchDecomp.H").read_text()


def test_solver_files_get_a_decompose_par_dict_only_in_parallel() -> None:
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files

    def files(cores):
        return build_solver_files(SolverCaseInput(Physics(), Inflow(), Solvers(cores=cores), ("Ball",),
                                                  (-0.5, 0.5, -0.5, 0.5, -0.5, 0.5), False))

    assert "system/decomposeParDict" not in files(1)
    assert files(6)["system/decomposeParDict"].content == {"numberOfSubdomains": 6, "method": "scotch"}


def test_physical_cores_counts_cores_not_threads(tmp_path: Path) -> None:
    rows = []
    for cpu in range(8):  # 2 sockets x 2 cores x 2 threads
        rows += [f"processor\t: {cpu}", f"physical id\t: {cpu // 4}", f"core id\t\t: {(cpu // 2) % 2}", ""]
    (tmp_path / "cpuinfo").write_text("\n".join(rows))
    assert physical_cores(tmp_path / "cpuinfo") == 4
    assert physical_cores(tmp_path / "missing") == os.cpu_count()
    assert 1 <= physical_cores() <= (os.cpu_count() or 1)


def test_decomposition_summary_of_the_real_log() -> None:
    """tests/data/parallel/log.decomposePar: the coarse sphere (192220 cells) on 4 subdomains."""
    found = parse_decomposition((DATA / "parallel" / "log.decomposePar").read_text())
    assert len(found.cells) == 4 and sum(found.cells) == 192220
    assert found.processor_faces == 6396 and found.max_above_average == pytest.approx(0.994694)
    assert found.summary() == ("Decomposed into 4 subdomains (scotch): 47575-48533 cells per processor "
                               "(max 0.99% above average), 6396 faces between processors")
    assert parse_decomposition("nothing") is None


# -- sequence with fake runners -----------------------------------------------------------------------------

DECOMPOSE_LINES = (DATA / "parallel" / "log.decomposePar").read_text().splitlines(keepends=True)


class Factory:
    """Hands out one FakeRunner per command, in order."""

    def __init__(self, *runners: FakeRunner) -> None:
        self.runners = list(runners)
        self.used: list[FakeRunner] = []

    def __call__(self) -> FakeRunner:
        runner = self.runners.pop(0)
        self.used.append(runner)
        return runner


def _run(tmp_path: Path, factory: Factory, stop_after: float | None = None, **kwargs):
    lines = []
    run = SolverRun(tmp_path, on_line=lines.append, runner_factory=factory, cores=4, **kwargs)
    run.start()
    if stop_after is not None:
        time.sleep(stop_after)
        run.request_stop()
    result = run.wait(10)
    assert result is not None
    return result, lines


def test_parallel_run_decomposes_solves_and_reconstructs(tmp_path: Path) -> None:
    factory = Factory(FakeRunner(DECOMPOSE_LINES), FakeRunner(iteration(1) + iteration(2) + ["End\n"]),
                      FakeRunner(["Reconstructing\n", "End\n"]))
    result, lines = _run(tmp_path, factory)
    decompose, solve, reconstruct = factory.used
    assert decompose.command == ["decomposePar", "-force"] and decompose.log_file == tmp_path / "log.decomposePar"
    assert solve.command == ["mpirun", "-np", "4", "simpleFoam", "-parallel"] and solve.clean_stop is True
    assert reconstruct.command == ["reconstructPar", "-latestTime"]
    assert result.state == ITERATION_LIMIT and result.iterations == 2 and result.cores == 4
    assert result.reconstructed is True and result.decomposition.startswith("Decomposed into 4 subdomains")
    assert result.decomposition + "\n" in lines and "Reconstructed the latest time\n" in lines


def test_clean_stop_in_parallel_still_reconstructs(tmp_path: Path) -> None:
    solve = FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"])
    factory = Factory(FakeRunner(DECOMPOSE_LINES), solve, FakeRunner(["End\n"]))
    result, _ = _run(tmp_path, factory, stop_after=0.3)
    assert solve.stop_requested and result.state == STOPPED and result.reconstructed is True
    assert len(factory.used) == 3


def test_failed_decomposition_or_reconstruction(tmp_path: Path) -> None:
    factory = Factory(FakeRunner(["--> FOAM FATAL ERROR\n"], exit_code=1))
    result, _ = _run(tmp_path, factory)
    assert result.state == CRASHED and "decomposePar failed (exit code 1)" in result.crash
    assert len(factory.used) == 1  # the solver never ran
    factory = Factory(FakeRunner(DECOMPOSE_LINES), FakeRunner(iteration(1) + ["End\n"]), FakeRunner([], exit_code=1))
    result, lines = _run(tmp_path, factory)
    assert result.state == ITERATION_LIMIT and result.reconstructed is False
    assert "reconstructPar failed (exit code 1): see log.reconstructPar\n" in lines


def test_a_stop_during_decomposition_is_a_stop(tmp_path: Path) -> None:
    factory = Factory(FakeRunner(DECOMPOSE_LINES[:5], hold=True, stop_lines=[]))
    result, _ = _run(tmp_path, factory, stop_after=0.3)
    assert result.state == STOPPED and result.crash is None and len(factory.used) == 1


def test_a_crashed_parallel_solver_is_not_reconstructed(tmp_path: Path) -> None:
    factory = Factory(FakeRunner(DECOMPOSE_LINES), FakeRunner(iteration(1), exit_code=1))
    result, _ = _run(tmp_path, factory)
    assert result.state == CRASHED and result.reconstructed is None and len(factory.used) == 2


def test_new_results_clear_the_processor_directories(tmp_path: Path) -> None:
    from vortexcfd.foam.mesh_case import MARKER_NAME, remove_results
    from vortexcfd.workflow.solving import clear_results

    (tmp_path / MARKER_NAME).write_text("")
    for name in ("processor0/0", "processor1/constant", "processorX", "0", "constant/polyMesh", "system", "60"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "system" / "decomposeParDict").write_text("x")
    (tmp_path / "log.decomposePar").write_text("x")
    assert remove_results(tmp_path) == ["60", "processor0", "processor1"]
    assert processor_dirs(tmp_path) == [tmp_path / "processorX"]  # not a processor<N> directory name
    clear_results(tmp_path)
    assert not (tmp_path / "system" / "decomposeParDict").exists() and not (tmp_path / "log.decomposePar").exists()
    assert (tmp_path / "constant" / "polyMesh").is_dir()


def test_runner_kills_processes_left_in_its_session(tmp_path: Path) -> None:
    """A child in a process group of its own (as MPI ranks are) that outlives the main process is
    killed by FoamRun's final sweep of the session."""
    from vortexcfd.foam.runner import FoamRun

    marker = tmp_path / "pid"
    run = FoamRun()
    child = ("import os, time; os.setpgid(0, 0); open(%r, 'w').write(str(os.getpid())); time.sleep(300)"
             % str(marker))
    run.start(["bash", "-c", f"python3 -c \"{child}\" > /dev/null 2>&1 & sleep 1; echo done"],
              tmp_path, tmp_path / "log")
    try:
        assert run.wait(20)
        res = run.result()
        assert res.exit_code == 0 and res.orphans_killed >= 1
        pid = int(marker.read_text())
        time.sleep(0.2)
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
        assert state in ("", "Z")
    finally:
        if marker.is_file():
            subprocess.run(["kill", "-9", marker.read_text()], capture_output=True)


# -- real OpenFOAM -------------------------------------------------------------------------------------------


@pytest.fixture
def mpi_slot(tmp_path_factory):
    """One MPI test at a time across xdist workers (a file lock next to the session's temp
    directories), so 4 ranks plus the other workers stay within the 12 physical cores."""
    import fcntl

    lock = tmp_path_factory.getbasetemp().parent / "vortexcfd_mpi.lock"
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _solver_case(sphere_mesh, case: Path, iterations: int, cores: int, speed: float = 20.0) -> None:
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.dictfile import write_foam_file
    from vortexcfd.foam.physics_case import SolverCaseInput, build_solver_files

    shutil.copytree(sphere_mesh.case_dir, case)
    inp = SolverCaseInput(Physics(), Inflow(speed=speed, alpha_deg=4.0),
                          Solvers(iterations=iterations, write_interval=iterations, cores=cores,
                                  stopping=StoppingCriteria(criteria=[])),
                          sphere_mesh.inputs.parts, sphere_mesh.inputs.parts_bounds, False)
    for rel, spec in enable_clean_stop(build_solver_files(inp)).items():
        write_foam_file(case / rel, spec.content, object_name=Path(rel).name, class_name=spec.class_name)


def _run_real(case: Path, cores: int, timeout: float, stop_at: int | None = None):
    run = SolverRun(case, timeout_s=timeout, cores=cores)
    run.start()
    try:
        if stop_at is not None:
            deadline = time.monotonic() + timeout
            while (not run.parser.time_steps or run.parser.time_steps[-1].time < stop_at) and time.monotonic() < deadline:
                time.sleep(0.2)
            run.request_stop()
        result = run.wait(timeout + 60)
    finally:
        if run.is_running():
            run.request_stop()
            run.wait(60)
    return result


def _no_ranks_left(root: Path) -> str:
    """simpleFoam / mpirun processes still running in a case under ``root`` (other xdist workers
    run their own solvers elsewhere)."""
    found = subprocess.run(["pgrep", "-a", "simpleFoam|mpirun|orted"], capture_output=True, text=True).stdout
    left = []
    for line in found.splitlines():
        try:
            cwd = os.readlink(f"/proc/{line.split()[0]}/cwd")
        except OSError:
            continue
        if cwd.startswith(str(root)):
            left.append(line)
    return "\n".join(left)


# Re = U D / nu = 0.003 * 1 / 1.5e-5 = 200: the coarse sphere's flow is steady and the solution
# converges (Cd changes by less than 1e-5 relative after iteration 300). At 20 m/s it oscillates
# and never converges, and a serial and a parallel run follow different paths from iteration 2
# (the linear solves stop at relTol 0.01 and the partition changes them): their instantaneous
# coefficients do not agree (D-063).
STEADY_SPEED = 0.003


@pytest.mark.slow
@pytest.mark.long  # real run above 60 s (D-043)
def test_serial_and_four_cores_agree_on_the_sphere(sphere_mesh, mpi_slot, tmp_path: Path) -> None:
    """The same 300 iterations of the coarse sphere at alpha 4 deg and Re 200 (steady, converged)
    in serial and on 4 cores (scotch): Cd and Cl of the last iteration agree within 0.5 %; the
    parallel case is reconstructed (the latest time has U and p in the case directory) and no
    rank is left. The wall times are printed (the speedup)."""
    from vortexcfd.foam.postprocessing import ReportMonitor

    n = 300
    out = {}
    for cores in (1, 4):
        case = tmp_path / f"c{cores}"
        _solver_case(sphere_mesh, case, n, cores, speed=STEADY_SPEED)
        result = _run_real(case, cores, timeout=500)
        assert result is not None and result.exit_code == 0 and result.state == ITERATION_LIMIT, result
        assert result.iterations == n
        monitor = ReportMonitor(case)
        monitor.poll()
        out[cores] = (monitor.series("Cd")[-1][1], monitor.series("Cl")[-1][1], result.duration_s)
        for field in ("U", "p"):
            assert (case / str(n) / field).is_file()
        if cores > 1:
            assert result.reconstructed is True and len(processor_dirs(case)) == 4
            assert result.decomposition.startswith("Decomposed into 4 subdomains")
    assert _no_ranks_left(tmp_path) == ""
    (cd1, cl1, t1), (cd4, cl4, t4) = out[1], out[4]
    print(f"\nserial Cd {cd1:.7g} Cl {cl1:.7g} in {t1:.1f} s; 4 cores Cd {cd4:.7g} Cl {cl4:.7g} in {t4:.1f} s; "
          f"dCd {100 * (cd4 - cd1) / cd1:.3g}% dCl {100 * (cl4 - cl1) / cl1:.3g}%; speedup {t1 / t4:.2f}")
    assert cd4 == pytest.approx(cd1, rel=5e-3) and cl4 == pytest.approx(cl1, rel=5e-3)


@pytest.mark.slow
def test_clean_stop_in_parallel_leaves_a_reconstructed_latest_time(sphere_mesh, mpi_slot, tmp_path: Path) -> None:
    """SIGUSR1 to mpirun (Open MPI forwards it to the ranks): every rank writes the current
    iteration and ends, exit code 0; reconstructPar -latestTime puts U and p of that iteration in
    the case directory; no rank is left."""
    case = tmp_path / "case"
    _solver_case(sphere_mesh, case, 200, 4)
    result = _run_real(case, 4, timeout=200, stop_at=8)
    assert result is not None and result.state == STOPPED and result.exit_code == 0, result
    it = result.iterations
    assert 8 <= it < 200 and result.reconstructed is True
    for field in ("U", "p"):
        assert (case / str(it) / field).is_file()
        for proc in processor_dirs(case):
            assert (proc / str(it) / field).is_file()
    assert "End" in (case / "log.simpleFoam").read_text()
    assert _no_ranks_left(tmp_path) == ""


@pytest.mark.slow
def test_timeout_in_parallel_kills_every_rank(sphere_mesh, mpi_slot, tmp_path: Path) -> None:
    """The timeout escalation (SIGTERM, then SIGKILL, to the process group and the whole session)
    leaves no MPI rank behind; the run is "stopped" and nothing is reconstructed."""
    case = tmp_path / "case"
    _solver_case(sphere_mesh, case, 500, 4)
    result = _run_real(case, 4, timeout=20)
    assert result is not None and result.state == STOPPED and result.exit_code != 0
    assert result.reconstructed is None
    time.sleep(1)
    assert _no_ranks_left(tmp_path) == ""


def test_console_shows_the_decomposition_and_run_states_are_unchanged(make_window, qtbot) -> None:
    """GUI: a 4-core run writes decomposeParDict, streams decomposePar's output and its summary
    into the console; Run Solver reads Stop while it runs and Run Solver after."""
    from vortexcfd.foam.dictfile import read_foam_file

    w = make_window()
    w.project.update_solver(cores=min(4, physical_cores()))
    cores = w.project.sim.solvers.cores
    solve = FakeRunner(iteration(1), hold=True, stop_lines=iteration(2) + ["End\n"])
    factory = Factory(FakeRunner(DECOMPOSE_LINES), solve, FakeRunner(["End\n"]))
    FakeRunner.instances.extend(factory.runners)
    w.solver_worker.runner_factory = factory
    w.run_solver()
    qtbot.waitUntil(lambda: "Decomposed into 4 subdomains" in w.console.text(), timeout=20000)
    case = w.project.path.parent / "case"
    if cores > 1:
        assert read_foam_file(case / "system" / "decomposeParDict")["numberOfSubdomains"] == cores
    assert "Number of processor faces = 6396" in w.console.text()
    assert w.top_bar.run_button.text() == "Stop" and w.top_bar.state_badge.text() == "Solving"
    w.run_solver()  # Stop
    qtbot.waitUntil(lambda: w.run_record is not None and not w.solver_worker.is_running(), timeout=30000)
    assert w.run_record.state == "stopped" and "Reconstructed the latest time" in w.console.text()
    assert w.top_bar.run_button.text() == "Run Solver"
    assert factory.used[1].command == ["mpirun", "-np", str(cores), "simpleFoam", "-parallel"]


def test_solvers_node_shows_the_recommended_cores(make_window) -> None:
    """The Solvers node shows min(physical cores, cells / 50,000) for the current mesh (D-064)."""
    w = make_window()  # fake mesh record: 1234 cells
    w.tree.setCurrentItem(w._items[("solvers", None)])
    row = w.properties._rows["solvers_recommended"]
    assert row.isVisibleTo(w.properties)
    assert w.properties.solvers_recommended.text() == "1 (1,234 cells, 50,000 per core)"
    w.tree.setCurrentItem(w._items[("inflow", None)])
    assert row.isHidden()
    unmeshed = make_window(mesh=False)
    unmeshed.tree.setCurrentItem(unmeshed._items[("solvers", None)])
    assert unmeshed.properties.solvers_recommended.text() == "— (generate the mesh first)"
