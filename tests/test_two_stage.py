"""The two-stage turbulence scheme of the wall-resolved mode (D-126): the switch from first-order to second-order
k and omega inside one solver run (fake runners), a stop in either stage, the record, and the case files."""

from pathlib import Path

import pytest

from tests.fake_solver import FakeRunner, iteration
from vortexcfd.core.model import AsymptoticCriterion, MeanStableCriterion, ResidualCriterion, StoppingCriteria
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file
from vortexcfd.foam.physics_case import STAGES_FILE, TURBULENCE_STAGE2, fv_schemes, turbulence_stages
from vortexcfd.foam.run_record import RunRecord, read_run_record, write_run_record
from vortexcfd.foam.solver_run import (
    CRITERIA_MET,
    LOG_NAME,
    STAGE1_SCHEME,
    STAGE2_SCHEME,
    STOPPED,
    SWITCH_CRITERIA,
    SWITCH_HALF_LIMIT,
    SolverRun,
    read_stages,
    stage2_criteria,
)


def _case(case: Path, end_time: int = 100, two_stage: bool = True) -> Path:
    write_foam_file(case / "system" / "fvSchemes", fv_schemes().content, object_name="fvSchemes")
    write_foam_file(case / "system" / "controlDict", {"application": "simpleFoam", "startFrom": "startTime",
                                                     "endTime": end_time}, object_name="controlDict")
    if two_stage:
        write_foam_file(case / STAGES_FILE, turbulence_stages().content, object_name="turbulenceStages")
    return case


def _cd(case: Path, start: int, rows: dict[int, float]) -> None:
    """forceCoeffs1's coefficient.dat in the start-time directory ``start`` (a restart writes a new one)."""
    folder = case / "postProcessing" / "forceCoeffs1" / str(start)
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{i}\t{v}\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\n" for i, v in rows.items())
    (folder / "coefficient.dat").write_text("# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\t"
                                            "Cs\tCs(f)\tCs(r)\n" + body)


def _run(case: Path, runners: list[FakeRunner], stopping=None, stop_in: int | None = None):
    lines, stages, queue = [], [], list(runners)
    run = SolverRun(case, on_line=lines.append, on_stage=lambda *a: stages.append(a),
                    runner_factory=lambda: queue.pop(0), stopping=stopping)
    run.start()
    if stop_in is not None:  # a user stop once runner ``stop_in`` (0 or 1) has started
        import time

        for _ in range(500):
            if runners[stop_in].on_line is not None if hasattr(runners[stop_in], "on_line") else False:
                break
            time.sleep(0.01)
        run.request_stop()
    result = run.wait(10)
    assert result is not None and not run.is_running()
    return result, lines, stages


ASYMPTOTIC = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=2)])


def test_the_switch_at_the_criteria_then_stage_2_to_the_criteria(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _cd(case, 0, {1: 0.5, 2: 0.3, 3: 0.3, 4: 0.3})  # stage 1: Cd settles at iteration 3
    _cd(case, 4, {5: 0.25, 6: 0.2, 7: 0.2, 8: 0.2})  # stage 2 (restart from 4): settles at 7
    stage1 = FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["Time = 4\n"], hold=True,
                        stop_lines=iteration(4)[1:] + ["End\n"])
    stage2 = FakeRunner(iteration(5) + iteration(6) + iteration(7) + ["Time = 8\n"], hold=True,
                        stop_lines=iteration(8)[1:] + ["End\n"])
    result, lines, stages = _run(case, [stage1, stage2], ASYMPTOTIC)
    assert stage1.stop_requested and stage1.clean_stop and not stage1.append  # the switch: the D-058 clean stop
    assert stage2.append and stage2.clean_stop and stage2.command == stage1.command
    assert result.state == CRITERIA_MET and result.met_iteration == 7 and result.iterations == 8
    assert result.switch_iteration == 4 and stages == [(2, 4, SWITCH_CRITERIA)]
    assert result.stages == (
        {"stage": 1, "k_omega": STAGE1_SCHEME, "first": 1, "last": 4, "switch": SWITCH_CRITERIA,
         "condition_met_at": 3},
        {"stage": 2, "k_omega": STAGE2_SCHEME, "first": 5, "last": 8})
    assert any("Turbulence stage 2 from iteration 4" in line for line in lines)
    schemes = read_foam_file(case / "system" / "fvSchemes")
    assert tuple(schemes["divSchemes"]["div(phi,k)"]) == ("bounded", "Gauss", "linearUpwind", "grad(k)")
    assert tuple(schemes["gradSchemes"]["grad(omega)"]) == ("cellLimited", "Gauss", "linear", 1)
    assert tuple(schemes["divSchemes"]["div(phi,U)"]) == ("bounded", "Gauss", "linearUpwindV", "grad(U)")  # kept
    assert read_foam_file(case / "system" / "controlDict")["startFrom"] == "latestTime"
    log = (case / LOG_NAME).read_text()
    assert "Time = 3" in log and "Time = 7" in log  # one log for both stages
    from vortexcfd.foam.postprocessing import ReportMonitor

    monitor = ReportMonitor(case)  # opened after the run (a project reopened): both start-time directories
    monitor.poll()
    assert [row[0] for row in monitor.series("Cd")] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_stage_2_waits_for_its_own_windows(tmp_path: Path) -> None:
    """Stage 2 is judged on its own iterations: earliest = switch + the criterion's first evaluation."""
    run = StoppingCriteria(criteria=[AsymptoticCriterion(quantity="Cd", window=200),
                                     AsymptoticCriterion(quantity="Cl", window=200)], min_iterations=500)
    assert stage2_criteria(run, 1324).min_iterations == 1824  # NACA round 2: the driver's restart + 500
    stable = StoppingCriteria(criteria=[MeanStableCriterion(quantity="Cl")], min_iterations=1000)
    assert stage2_criteria(stable, 2857).min_iterations == 3857  # 2 W = 1000
    residual = StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4)])
    assert stage2_criteria(residual, 100).min_iterations > 100


def test_a_stop_in_stage_1_ends_the_run_with_its_result(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _cd(case, 0, {1: 0.5, 2: 0.4})
    before = (case / "system" / "fvSchemes").read_text()
    stage1 = FakeRunner(iteration(1) + iteration(2), hold=True, stop_lines=iteration(3) + ["End\n"])
    result, _, stages = _run(case, [stage1, FakeRunner([])], ASYMPTOTIC, stop_in=0)
    assert result.state == STOPPED and result.iterations == 3 and result.switch_iteration is None and stages == []
    assert result.stages == ({"stage": 1, "k_omega": STAGE1_SCHEME, "first": 1, "last": 3, "switch": None,
                              "condition_met_at": None},)
    assert (case / "system" / "fvSchemes").read_text() == before  # still first order


def test_a_stop_in_stage_2_ends_the_run_with_both_stages(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _cd(case, 0, {1: 0.5, 2: 0.3, 3: 0.3, 4: 0.3})
    _cd(case, 4, {5: 0.25, 6: 0.22})
    stage1 = FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["Time = 4\n"], hold=True,
                        stop_lines=iteration(4)[1:] + ["End\n"])
    stage2 = FakeRunner(iteration(5) + iteration(6), hold=True, stop_lines=iteration(7) + ["End\n"])
    result, _, stages = _run(case, [stage1, stage2], ASYMPTOTIC, stop_in=1)
    assert result.state == STOPPED and result.iterations == 7 and result.switch_iteration == 4
    assert [s["stage"] for s in result.stages] == [1, 2] and result.stages[1]["last"] == 7
    assert result.criteria_met == () and stages == [(2, 4, SWITCH_CRITERIA)]


def test_the_switch_at_half_the_iteration_limit(tmp_path: Path) -> None:
    """Without criteria (or before they are met) stage 2 gets the second half of the iteration limit."""
    case = _case(tmp_path, end_time=6)
    stage1 = FakeRunner(iteration(1) + iteration(2) + iteration(3) + ["Time = 4\n"], hold=True,
                        stop_lines=iteration(4)[1:] + ["End\n"])
    stage2 = FakeRunner(iteration(5) + iteration(6) + ["End\n"])
    result, _, stages = _run(case, [stage1, stage2], None)
    assert stages == [(2, 4, SWITCH_HALF_LIMIT)] and result.stages[0]["condition_met_at"] == 3
    assert result.iterations == 6 and result.state == "iteration_limit"


def test_a_single_stage_case_is_unchanged(tmp_path: Path) -> None:
    case = _case(tmp_path, two_stage=False)
    assert read_stages(case) is None
    runner = FakeRunner(iteration(1) + iteration(2) + ["End\n"])
    result, _, stages = _run(case, [runner], StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1.0)]))
    assert not runner.stop_requested and result.stages == () and result.switch_iteration is None and stages == []


def test_the_record_keeps_both_stages(tmp_path: Path) -> None:
    stages = ({"stage": 1, "k_omega": STAGE1_SCHEME, "first": 1, "last": 4, "switch": SWITCH_CRITERIA,
               "condition_met_at": 3}, {"stage": 2, "k_omega": STAGE2_SCHEME, "first": 5, "last": 8})
    record = RunRecord(CRITERIA_MET, 8, {"p": 1e-5}, "h", 0, (), (), (), 7, 1.0, 1, stages, 4)
    write_run_record(tmp_path, record)
    back = read_run_record(tmp_path)
    assert back.stages == stages and back.switch_iteration == 4
    single = RunRecord(CRITERIA_MET, 8, {}, "h")
    write_run_record(tmp_path, single)
    assert "stages" not in (tmp_path / "vortexcfd_run.json").read_text()  # single-stage records as before
    assert read_run_record(tmp_path).stages == ()


def test_the_wall_resolved_mode_writes_two_stages(tmp_path: Path) -> None:
    from tests.test_section_2d import airfoil_project
    from vortexcfd.foam.physics_case import build_solver_files
    from vortexcfd.workflow import solving

    project = airfoil_project(tmp_path)  # the "2D airfoil" preset: wall-resolved
    project.update_solver(stopping=StoppingCriteria(criteria=[ResidualCriterion(field="p", threshold=1e-4)]).model_dump())
    inp = solving.solver_input(project)
    files = build_solver_files(inp)
    assert inp.two_stage and files[STAGES_FILE].content["stage2"]["divSchemes"] == TURBULENCE_STAGE2["divSchemes"]
    assert "runTimeControl1" not in str(files["system/controlDict"].content["functions"].keys())  # app-side
    assert files["system/fvSchemes"].content["divSchemes"]["div(phi,k)"] == ("bounded", "Gauss", "upwind")
    staged = solving.results_hash(project)
    project.update_mesh(target_yplus=50.0, layer_controls="robust")  # wall functions: one stage, as before
    inp = solving.solver_input(project)
    files = build_solver_files(inp)
    assert not inp.two_stage and STAGES_FILE not in files
    assert any("runTime" in k or "Control" in k for k in files["system/controlDict"].content["functions"])
    assert solving.results_hash(project) != staged


def test_the_monitors_show_the_stage(qtbot) -> None:
    from vortexcfd.gui.monitors import MonitorsPanel, stage_text

    panel = MonitorsPanel()
    qtbot.addWidget(panel)
    assert not panel.stage_label.isVisibleTo(panel)
    panel.set_stage(stage_text(1))
    assert panel.stage_label.isVisibleTo(panel) and "stage 1 of 2: first-order" in panel.stage_label.text()
    panel.set_stage(stage_text(2, 1324, SWITCH_CRITERIA))
    assert panel.stage_label.text() == ("Turbulence stage 2 of 2: second-order k, omega from iteration 1324 "
                                        "(switch: criteria met)")
    panel.clear()
    assert not panel.stage_label.isVisibleTo(panel)


@pytest.mark.slow
@pytest.mark.long  # real meshing and solving above 60 s
def test_naca0012_coarse_reaches_stage_2_and_converges(tmp_path: Path) -> None:
    """The NACA 0012 coarse level at 10 deg through the app (the "2D airfoil" preset, wall-resolved): stage 1 meets
    the criteria, the switch, stage 2 meets them again."""
    from tests.validation import naca0012_case as nc
    from vortexcfd.foam.mesh_run import MeshRun
    from vortexcfd.foam.postprocessing import ReportMonitor
    from vortexcfd.workflow import meshing, solving

    project = nc.build_project(tmp_path / "naca", alpha=10.0, base_size=2.0)  # round 1's coarse level
    job = meshing.prepare_job(project)
    plan = meshing.plan_layers_for(project, job.box)
    mesh = MeshRun(job.case_dir, parts=job.inputs.patches, first_layer=(plan.first, plan.count), cores=job.cores)
    mesh.start()
    report = mesh.wait().report
    assert report is not None and report.valid
    case = solving.prepare_solver_case(project)
    assert read_stages(case) is not None
    run = SolverRun(case, stopping=project.sim.solvers.stopping, cores=project.sim.solvers.cores, timeout_s=1800)
    run.start()
    result = run.wait()
    assert result.state == CRITERIA_MET and result.switch_iteration is not None
    assert result.stages[0]["switch"] == SWITCH_CRITERIA and result.stages[1]["last"] == result.iterations
    assert result.met_iteration >= result.switch_iteration + 500  # stage 2's own windows
    monitor = ReportMonitor(case)
    monitor.poll()
    cl, cd = monitor.series("Cl")[-1][1], monitor.series("Cd")[-1][1]
    assert 1.0 < cl < 1.1 and 0.011 < cd < 0.0135  # TMR SST 1.0794, 0.012467
