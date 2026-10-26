"""Parallel meshing (D-111): the command sequence, decomposeParDict, stop, failures, processor*
cleanup, the mesh record, the meshing cores rule. The real 4-core sphere is the slow test at the end."""

import threading
from pathlib import Path

import pytest

from vortexcfd.core.model import Mesh
from vortexcfd.core.project import Project
from vortexcfd.foam import mesh_run
from vortexcfd.foam.mesh_case import (
    MESH_COMMANDS,
    MESH_RECORD_FILE,
    MARKER_NAME,
    MARKER_TEXT,
    mesh_commands,
    prepare_case_dir,
)
from vortexcfd.foam.mesh_record import RECORD_NAME, MeshRecord, read_mesh_record, write_mesh_record
from vortexcfd.foam.mesh_report import MeshReport
from vortexcfd.foam.mesh_run import MeshRun
from vortexcfd.foam.parallel import (
    DECOMPOSE_DICT,
    MESH_CELLS_PER_CORE,
    MESH_EFFICIENT_CORES,
    parallel_command,
    recommended_mesh_cores,
    solver_command,
)
from vortexcfd.foam.runner import RunResult

DATA = Path(__file__).parent / "data"
CHECK_LOG = (DATA / "checkMesh_sphere_snappy.log").read_text()


# -- the command sequence ---------------------------------------------------------------------------


def test_one_core_is_the_serial_pipeline_unchanged() -> None:
    assert mesh_commands(1) is MESH_COMMANDS
    assert all("mpirun" not in cmd and "-parallel" not in cmd for _, cmd in mesh_commands(1))


def test_n_cores_decompose_once_run_every_snappy_pass_in_parallel_and_reconstruct_once() -> None:
    steps = mesh_commands(4)
    assert [name for name, _ in steps] == [
        "blockMesh", "surfaceFeatureExtract", "decomposePar", "snappyHexMesh.castellate", "snappyHexMesh",
        "reconstructParMesh", "extrudeMesh", "createPatch", "checkMesh"]
    cmd = dict(steps)
    assert cmd["blockMesh"] == ["blockMesh"] and cmd["surfaceFeatureExtract"] == ["surfaceFeatureExtract"]
    assert cmd["decomposePar"] == ["decomposePar", "-force", "-no-fields"]  # the mesh only (D-130)
    assert cmd["snappyHexMesh.castellate"] == ["mpirun", "-np", "4", "snappyHexMesh", "-overwrite", "-dict",
                                               "system/snappyHexMeshDict.castellate", "-parallel"]
    assert cmd["snappyHexMesh"] == ["mpirun", "-np", "4", "snappyHexMesh", "-overwrite", "-parallel"]
    assert cmd["reconstructParMesh"] == ["reconstructParMesh", "-constant"]
    assert cmd["createPatch"] == ["createPatch", "-overwrite"] and cmd["checkMesh"] == ["checkMesh"]


def test_the_solver_command_is_the_general_parallel_command() -> None:
    assert solver_command("simpleFoam", 1) == ["simpleFoam"]
    assert solver_command("simpleFoam", 3) == parallel_command(["simpleFoam"], 3) == [
        "mpirun", "-np", "3", "simpleFoam", "-parallel"]


# -- MeshRun with a fake runner ---------------------------------------------------------------------


class FakeFoamRun:
    """FoamRun's interface for MeshRun: plays one step. A step named in ``block`` waits for
    request_stop (the real FoamRun then escalates SIGTERM -> SIGKILL over the run's session)."""

    calls: list[tuple[str, list[str], bool]] = []  # (step, command, processor dirs present at start)
    block: set[str] = set()
    fail: set[str] = set()
    raising: set[str] = set()  # steps whose start raises OSError (log not writable, disk full)
    started = threading.Event()

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._code = 0

    def start(self, command, case_dir, log_file, on_line=None, timeout_s=None) -> None:
        name = Path(log_file).name.removeprefix("log.")
        if name in FakeFoamRun.raising:
            raise OSError(28, "No space left on device")
        case_dir = Path(case_dir)
        FakeFoamRun.calls.append((name, list(command), any(case_dir.glob("processor*"))))
        self._log = Path(log_file)
        self._log.parent.mkdir(parents=True, exist_ok=True)
        text = CHECK_LOG if name == "checkMesh" else f"{name}\n"
        if name == "decomposePar":
            for k in range(int((case_dir / DECOMPOSE_DICT).read_text().split("numberOfSubdomains")[1]
                               .split(";")[0])):
                (case_dir / f"processor{k}" / "constant").mkdir(parents=True)
        self._log.write_text(text)
        self._code = 1 if name in FakeFoamRun.fail else 0
        self._blocking = name in FakeFoamRun.block
        FakeFoamRun.started.set()

    def wait(self, timeout=None) -> bool:
        if self._blocking:
            self._stop.wait(30)
        return True

    def request_stop(self, grace_s: float = 10.0) -> bool:
        self._stop.set()
        self._code = -15
        return True

    def result(self) -> RunResult:
        return RunResult(self._code, 0.1, self._log, stop_requested=self._stop.is_set())


@pytest.fixture
def fake(monkeypatch):
    FakeFoamRun.calls, FakeFoamRun.block, FakeFoamRun.fail, FakeFoamRun.raising = [], set(), set(), set()
    FakeFoamRun.started = threading.Event()
    monkeypatch.setattr(mesh_run, "FoamRun", FakeFoamRun)
    yield FakeFoamRun
    FakeFoamRun.block, FakeFoamRun.fail, FakeFoamRun.raising = set(), set(), set()  # class state other files reuse


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    return case


def test_parallel_run_writes_the_decomposition_and_cleans_after_reconstruction(tmp_path, fake) -> None:
    case = _case(tmp_path)
    (case / "processor7").mkdir()  # a decomposed mesh of an earlier solver run
    run = MeshRun(case, cores=3)
    run.start()
    result = run.wait(10)
    assert result.success and result.cores == 3 and result.report.mesh_ok
    names = [name for name, _, _ in fake.calls]
    assert names == ["blockMesh", "decomposePar", "snappyHexMesh", "reconstructParMesh", "checkMesh"]  # optional
    # steps without their dictionary are skipped, as in serial
    present = {name: procs for name, _, procs in fake.calls}
    assert not present["decomposePar"]  # the stale processor7 was removed first
    assert present["snappyHexMesh"] and present["reconstructParMesh"]
    assert not present["checkMesh"]  # removed right after the reconstruction
    assert not list(case.glob("processor*")) and not (case / DECOMPOSE_DICT).exists()


def test_decompose_par_dict_contents(tmp_path, fake) -> None:
    case = _case(tmp_path)
    seen = {}

    original = FakeFoamRun.start

    def spy(self, command, case_dir, log_file, **kw):
        if Path(log_file).name == "log.decomposePar":
            seen["text"] = (Path(case_dir) / DECOMPOSE_DICT).read_text()
        original(self, command, case_dir, log_file, **kw)

    FakeFoamRun.start = spy
    try:
        run = MeshRun(case, cores=4)
        run.start()
        run.wait(10)
    finally:
        FakeFoamRun.start = original
    text = seen["text"]
    assert "object      decomposeParDict;" in text or "object decomposeParDict;" in " ".join(text.split())
    assert "numberOfSubdomains 4;" in " ".join(text.split()) and "method scotch;" in " ".join(text.split())


def test_stop_ends_the_ranks_leaves_no_mesh_and_cleans_processors(tmp_path, fake) -> None:
    case = _case(tmp_path)
    fake.block = {"snappyHexMesh"}
    done = []
    run = MeshRun(case, cores=4, on_done=done.append)
    run.start()
    for _ in range(100):
        if any(name == "snappyHexMesh" for name, _, _ in fake.calls):
            break
        threading.Event().wait(0.05)
    assert list(case.glob("processor*"))  # decomposed while snappyHexMesh runs
    run.request_stop()
    result = run.wait(10)
    assert result.stopped and not result.success and result.report is None
    assert [name for name, _, _ in fake.calls][-1] == "snappyHexMesh"  # nothing ran after the stop
    assert not list(case.glob("processor*")) and not (case / DECOMPOSE_DICT).exists()
    assert done == [result]  # the GUI hears of it after the cleanup


@pytest.mark.parametrize("step", ["decomposePar", "reconstructParMesh"])
def test_a_failed_decomposition_or_reconstruction_is_reported_with_its_log(tmp_path, fake, step) -> None:
    case = _case(tmp_path)
    fake.fail = {step}
    run = MeshRun(case, cores=2)
    run.start()
    result = run.wait(10)
    assert not result.success and result.failed_step == step and result.report is None
    assert result.error == f"{step} failed (exit code 1): see {case / 'logs' / f'log.{step}'}"
    assert "checkMesh" not in [name for name, _, _ in fake.calls]
    assert not list(case.glob("processor*"))


@pytest.mark.parametrize("cores", [1, 3])
def test_an_exception_in_a_step_is_reported_and_cleaned(tmp_path, fake, cores) -> None:
    """R-02: a step that cannot start ends the run with a failed result through on_done."""
    case = _case(tmp_path)
    fake.raising = {"snappyHexMesh"}
    done = []
    run = MeshRun(case, cores=cores, on_done=done.append)
    run.start()
    result = run.wait(10)
    assert done == [result] and not run.is_running()
    assert not result.success and not result.stopped and result.failed_step == "snappyHexMesh"
    assert result.error == "snappyHexMesh failed: OSError: [Errno 28] No space left on device"
    assert result.report is None and result.cores == cores
    assert not list(case.glob("processor*")) and not (case / DECOMPOSE_DICT).exists()


def test_serial_run_writes_no_decomposition(tmp_path, fake) -> None:
    case = _case(tmp_path)
    (case / "processor0").mkdir()  # a parallel solver run's: serial meshing leaves it to remove_results
    run = MeshRun(case)
    run.start()
    result = run.wait(10)
    assert result.success and result.cores == 1
    assert [name for name, _, _ in fake.calls] == ["blockMesh", "snappyHexMesh", "checkMesh"]
    assert all("mpirun" not in cmd for _, cmd, _ in fake.calls) and not (case / DECOMPOSE_DICT).exists()
    assert (case / "processor0").is_dir()


def test_a_real_stop_during_a_parallel_step_cleans_processors(tmp_path) -> None:
    """The real FoamRun: the step's process is ended (SIGTERM to its session) and processor* removed."""
    case = _case(tmp_path)
    (case / "processor0").mkdir()
    steps = (("decomposePar", ["mkdir", "-p", "processor0", "processor1"]), ("snappyHexMesh", ["sleep", "30"]))
    run = MeshRun(case, steps=steps, cores=2, step_timeout_s=50)
    run.start()
    for _ in range(100):
        if (case / "processor1").is_dir():
            break
        threading.Event().wait(0.05)
    threading.Event().wait(0.5)
    run.request_stop()
    result = run.wait(30)
    assert result is not None and result.stopped and not result.success
    assert not run.is_running() and not list(case.glob("processor*"))


# -- the mesh record and the case directory ---------------------------------------------------------


def _report() -> MeshReport:
    return MeshReport(points=10, faces=40, cells=1234, max_non_orthogonality=30.5, avg_non_orthogonality=10.0,
                      max_skewness=0.5, failed_checks=0, mesh_ok=True)


def test_the_mesh_record_stores_the_cores(tmp_path) -> None:
    write_mesh_record(tmp_path, MeshRecord(_report(), "h", ("Ball",), 4))
    assert read_mesh_record(tmp_path).cores == 4
    import json

    data = json.loads((tmp_path / RECORD_NAME).read_text())
    del data["cores"]  # a record written before D-111
    (tmp_path / RECORD_NAME).write_text(json.dumps(data))
    assert read_mesh_record(tmp_path).cores == 1


def test_a_new_meshing_case_drops_the_previous_mesh_record(tmp_path) -> None:
    assert MESH_RECORD_FILE == RECORD_NAME
    case = tmp_path / "case"
    case.mkdir()
    (case / MARKER_NAME).write_text(MARKER_TEXT)
    write_mesh_record(case, MeshRecord(_report(), "h", ("Ball",)))
    prepare_case_dir(case, {})
    assert read_mesh_record(case) is None  # a stopped or failed run leaves no generated mesh


# -- the meshing cores (P2) -------------------------------------------------------------------------


def test_recommended_mesh_cores() -> None:
    assert recommended_mesh_cores(10, 12) == 1
    assert recommended_mesh_cores(MESH_CELLS_PER_CORE * 3, 12) == min(3, MESH_EFFICIENT_CORES)
    assert recommended_mesh_cores(10**9, 12) == MESH_EFFICIENT_CORES
    assert recommended_mesh_cores(10**9, 2) == 2  # never more than the physical cores


class _Estimate:
    def __init__(self, cells: int) -> None:
        self.budget_cells = cells


@pytest.mark.parametrize("solver, chosen, cells, physical, used, automatic", [
    (1, None, 10**7, 12, MESH_EFFICIENT_CORES, True),  # the Solvers cores do not cap it (owner review)
    (4, None, 100_000, 12, 8, True),  # the default background: 100,000 / 12,500
    (8, None, MESH_CELLS_PER_CORE * 2, 12, 2, True),
    (1, None, 10, 12, 1, True),
    (1, 6, 10, 12, 6, False),  # the user's number, beyond the recommendation
    (1, 16, 10, 12, 12, False),  # never more than the physical cores
    (16, None, 10**7, 2, 2, True),
])
def test_mesh_cores_rule(monkeypatch, solver, chosen, cells, physical, used, automatic) -> None:
    from vortexcfd.workflow import meshing

    monkeypatch.setattr(meshing, "estimate_with_volumes", lambda project, box: _Estimate(cells))
    project = Project.new("c")
    project.update_solver(cores=solver)
    project.update_mesh(cores=chosen)
    info = meshing.mesh_cores(project, box=None, physical=physical)
    assert (info.used, info.automatic, info.cells) == (used, automatic, cells)
    assert info.recommended == recommended_mesh_cores(cells, physical)


def test_the_mesh_cores_are_not_a_meshing_input(tmp_path) -> None:
    from vortexcfd.workflow.meshing import inputs_hash

    project = Project.new("h")
    before = inputs_hash(project)
    project.update_mesh(cores=4)
    assert inputs_hash(project) == before
    assert Mesh().cores is None


def test_a_v14_project_meshes_with_automatic_cores() -> None:
    from vortexcfd.core.project_io import migrate
    from vortexcfd.core.model import Simulation

    sim = Simulation.model_validate(migrate({"schema_version": 14, "name": "x", "mesh": {}}))
    assert sim.schema_version == 25 and sim.mesh.cores is None


def test_a_preset_never_carries_the_mesh_cores() -> None:
    from vortexcfd.core.model import Simulation
    from vortexcfd.core.presets import apply_preset, preset_from_simulation

    sim = Simulation(name="x", mesh=Mesh(cores=6))
    preset = preset_from_simulation(sim, "Mine")
    assert "cores" not in preset.model_dump()["mesh"] and "cores" not in preset.model_dump_json()
    assert apply_preset(sim, preset).mesh.cores is None


# -- logs -------------------------------------------------------------------------------------------


def test_the_layer_table_and_stage_times_parse_from_the_parallel_master_log() -> None:
    """tests/data/snappyHexMesh_sphere_parallel.log: the master rank's log of a 4-core run."""
    from vortexcfd.bench import metrics
    from vortexcfd.foam.mesh_report import LayerCoverage, parse_layer_table

    text = (DATA / "snappyHexMesh_sphere_parallel.log").read_text()
    assert "nProcs : 4" in text
    layers, extruded = parse_layer_table(text)
    assert layers == (LayerCoverage("sphere", 10636, 6, 6.0, 0.0179, 100.0),) and extruded == 100.0
    stages = metrics.snappy_stage_times(text)
    assert all(stages[k] is not None and stages[k] > 0 for k in ("castellation", "snap", "layers", "snappy_total"))
    diag = metrics.layer_log_diagnostics(text)
    assert diag["extruded_faces"] == diag["total_faces"] == 10636


# -- the real run (slow) ----------------------------------------------------------------------------


@pytest.mark.slow
def test_sphere_meshed_on_four_cores_matches_the_serial_patches(tmp_path, sphere_mesh) -> None:
    """The shared serial sphere (conftest) meshed again on 4 cores: decomposed, reconstructed, checkMesh
    OK on the serial mesh, the same patches, about the same cells, no processor* left."""
    import shutil

    from vortexcfd.foam.postprocessing import patch_face_counts

    case = tmp_path / "case"
    shutil.copytree(sphere_mesh.case_dir, case, ignore=shutil.ignore_patterns("polyMesh", "logs", "processor*"))
    steps: list[str] = []
    run = MeshRun(case, cores=4, on_step=steps.append, step_timeout_s=100, parts=sphere_mesh.inputs.parts)
    run.start()
    result = run.wait(300)
    assert result is not None and result.success, result and result.error
    assert steps == ["blockMesh", "surfaceFeatureExtract", "decomposePar", "snappyHexMesh", "reconstructParMesh",
                     "checkMesh"]
    report = result.report
    assert report.mesh_ok and report.valid and result.cores == 4
    assert "nProcs : 4" in (case / "logs" / "log.snappyHexMesh").read_text()
    serial, parallel = patch_face_counts(sphere_mesh.case_dir), patch_face_counts(case)
    assert set(parallel) == set(serial) and all(parallel[p] > 0 for p in serial)
    assert report.layers and {c.patch for c in report.layers} == {c.patch for c in sphere_mesh.result.report.layers}
    assert abs(report.cells - sphere_mesh.result.report.cells) <= 0.02 * sphere_mesh.result.report.cells
    assert not list(case.glob("processor*")) and not (case / DECOMPOSE_DICT).exists()


# -- the benchmark's memory of all ranks ------------------------------------------------------------


def test_descendant_memory_adds_up_every_rank(tmp_path) -> None:
    from vortexcfd.bench.runner import PAGE_BYTES, descendants_rss_mb

    def proc(pid: int, ppid: int, pages: int, name: str = "x y") -> None:
        (tmp_path / str(pid)).mkdir()
        rest = ["S", str(ppid)] + ["0"] * 19 + [str(pages)] + ["0"] * 5  # rss is field 24
        (tmp_path / str(pid) / "stat").write_text(f"{pid} ({name}) " + " ".join(rest) + "\n")

    proc(10, 1, 100)  # the benchmark worker
    proc(11, 10, 5)  # bash
    proc(12, 11, 7, "mpirun")
    for rank in (13, 14, 15):
        proc(rank, 12, 1000, "snappy Hex)Mesh")  # a ")" in the command does not confuse the parser
    proc(20, 1, 99999)  # not ours
    (tmp_path / "self").mkdir()
    assert descendants_rss_mb(10, tmp_path) == (5 + 7 + 3000) * PAGE_BYTES / 2**20
