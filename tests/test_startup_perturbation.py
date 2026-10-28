"""The start-up perturbations of a transient external flow (D-198): two declared options, both off by default (the
initial-field perturbation and the inflow swing), declared in the case files, the control file, the solver log, the
run record, the report and the snapshots, and never sampled."""

import json
from pathlib import Path

import numpy as np
import pytest

from tests.fake_solver import FakeRunner
from tests.test_solver_gui import fake_mesh, make_window, use_runner, wait_done  # noqa: F401 (fixture)
from tests.test_transient import _series, _steps, _transient_case, _transient_case_files
from vortexcfd.core.model import INITIAL_PERTURB_END, Inflow, Physics, Simulation, Solvers, Transient
from vortexcfd.core.presets import BUILTIN_PRESETS, apply_preset
from vortexcfd.core.project_io import load_simulation
from vortexcfd.foam import transient
from vortexcfd.foam.case_writer import write_case
from vortexcfd.foam.dictfile import read_foam_file, set_foam_entry, write_foam_file
from vortexcfd.foam.physics_case import (
    INITIAL_PERTURB_FILE,
    SolverCaseInput,
    build_solver_files,
    initial_perturbation_expression,
)
from vortexcfd.foam.run_record import RunRecord, write_run_record
from vortexcfd.foam.solver_run import CRASHED, END_TIME, ContinueFrom, SolverRun, solver_log
from vortexcfd.workflow import solving

DATA = Path(__file__).parent / "data"


def _input(span: float | None = None, **transient_settings) -> SolverCaseInput:
    """A unit body (l_ref 2 m, x from 0 to 2) at 4 m/s: t_c = 0.5 s."""
    physics = Physics(flow="incompressible_transient")
    solvers = Solvers(transient=Transient(**transient_settings))
    return SolverCaseInput(physics, Inflow(speed=4.0), solvers, ("body",), (0.0, 2.0, -0.5, 0.5, -0.5, 0.5),
                           span=span)


def test_both_perturbations_are_off_by_default_in_every_project_and_preset() -> None:
    assert not Transient().perturb and not Transient().perturb_initial
    for preset in BUILTIN_PRESETS:  # a preset never turns one on
        t = apply_preset(Simulation(name="p"), preset).solvers.transient
        assert not t.perturb and not t.perturb_initial, preset.name
    files = build_solver_files(_input())
    assert INITIAL_PERTURB_FILE not in files
    assert files["system/controlDict"].comment is None and files["0/U"].comment is None
    assert files["0/U"].content["boundaryField"]["inlet"] == {"type": "fixedValue", "value": [4.0, 0.0, 0.0]}
    control = transient.TransientControl.from_content(files[transient.TRANSIENT_FILE].content)
    assert control.perturbations == () and control.not_before == 0.0
    assert "startupPerturbation" not in files[transient.TRANSIENT_FILE].content


def test_a_v25_project_opens_with_both_off_and_otherwise_unchanged() -> None:
    """The schema v25 -> v26 migration: the inflow swing, on by default in v25, and the new option are off; nothing
    else changes (tests/data/project_v25.json, a real v25 file with the swing on)."""
    raw = json.loads((DATA / "project_v25.json").read_text())
    assert raw["schema_version"] == 25 and raw["solvers"]["transient"]["perturb"] is True
    sim = load_simulation(DATA / "project_v25.json")
    assert sim.schema_version == 26
    assert not sim.solvers.transient.perturb and not sim.solvers.transient.perturb_initial
    dumped = json.loads(sim.model_dump_json())
    stored_transient = dict(raw["solvers"]["transient"], perturb=False)
    assert {k: v for k, v in dumped["solvers"]["transient"].items() if k != "perturb_initial"} == stored_transient
    for key, value in raw.items():
        if key not in ("schema_version", "solvers"):
            assert dumped[key] == value, key
    assert {k: v for k, v in dumped["solvers"].items() if k != "transient"} == {
        k: v for k, v in raw["solvers"].items() if k != "transient"}


def test_the_initial_field_perturbation_changes_the_initial_velocity_only(tmp_path: Path) -> None:
    """D-198: a cross-flow Gaussian of 0.1 U, radius 0.25 l_ref, 0.5 l_ref behind the body, set on 0/U by
    setExprFields before the run; every boundary condition and every other file as without it; the sampling never
    starts before 5 t_c; declared in controlDict, the dictionary itself and the control file."""
    off, on = build_solver_files(_input()), build_solver_files(_input(perturb_initial=True))
    for rel, spec in off.items():
        if rel not in ("system/controlDict", transient.TRANSIENT_FILE):
            assert on[rel].content == spec.content, rel  # 0/U's conditions and values are the set-up's
    assert on["system/controlDict"].content == off["system/controlDict"].content  # only its comment differs
    expression = initial_perturbation_expression(_input(perturb_initial=True))
    assert expression == ("U + vector(0, 0, 0.4*exp(-(sqr(pos().x() - (3)) + sqr(pos().y() - (0)) + "
                          "sqr(pos().z() - (0)))/0.5))")
    assert "pos().y()" not in initial_perturbation_expression(_input(span=0.1, perturb_initial=True))  # 2D
    control = transient.TransientControl.from_content(on[transient.TRANSIENT_FILE].content)
    assert control.not_before == pytest.approx(INITIAL_PERTURB_END * 0.5)
    assert len(control.perturbations) == 1 and control.perturbations[0].startswith("Initial-field perturbation")
    assert "Initial-field perturbation" in on["system/controlDict"].comment
    case = tmp_path / "case"
    write_case(case, on)
    text = (case / INITIAL_PERTURB_FILE).read_text()
    assert "object setExprFieldsDict;" in text and "readFields ( U );" in text and f"#{{\n            {expression}" in text
    assert "// VortexCFD start-up perturbation (D-198)" in text and "boundary conditions" in text
    control_dict = case / "system" / "controlDict"
    assert "// VortexCFD start-up perturbation(s) declared by the user" in control_dict.read_text()
    assert read_foam_file(control_dict)["application"] == "pimpleFoam"  # still a valid dictionary
    set_foam_entry(control_dict, "startFrom", "latestTime")  # the app's later edits keep the declaration
    assert "// VortexCFD start-up perturbation(s) declared by the user" in control_dict.read_text()
    written = transient.read_control(case)
    assert written.perturbations == control.perturbations and written.not_before == control.not_before


def test_both_declared_together() -> None:
    files = build_solver_files(_input(perturb=True, perturb_initial=True))  # swing 10 t_c = 5 s, initial 2.5 s
    control = transient.TransientControl.from_content(files[transient.TRANSIENT_FILE].content)
    assert control.not_before == pytest.approx(5.0) and len(control.perturbations) == 2
    assert files["0/U"].content["boundaryField"]["inlet"]["type"] == "uniformFixedValue"
    assert "Inflow swing" in files["0/U"].comment and "Inflow swing" in files["system/controlDict"].comment
    assert INITIAL_PERTURB_FILE in files


def test_the_sampling_never_starts_inside_the_initial_field_perturbation(make_window) -> None:
    """D-198: a sampling start set by hand before its end (5 t_c) is refused; the detection's windows both begin
    after it (the control file's notBefore)."""
    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(perturb_initial=True, sampling_start=3.0)
    assert "inside the start-up perturbation" in (solving.transient_problem(w.project, [], [], [], []) or "")
    w.project.update_transient(sampling_start=INITIAL_PERTURB_END)
    assert solving.transient_problem(w.project, [], [], [], []) is None
    w.project.update_transient(perturb_initial=False, sampling_start=3.0)
    assert solving.transient_problem(w.project, [], [], [], []) is None
    t_c = solving.convective_time(w.project)
    w.project.update_transient(perturb_initial=True, time_unit="s", sampling_start=3.0 * t_c)  # in seconds
    assert "inside the start-up perturbation" in (solving.transient_problem(w.project, [], [], [], []) or "")
    t = np.arange(0.0, 20.0, 0.01)  # settled from the start: detected only once two windows follow the end
    series = {"Cd": [(x, 1.3) for x in t], "Cl": [(x, 0.3 * np.sin(2 * np.pi * x)) for x in t]}
    assert transient.detect_start(series, 2.0, 0.005, "Cd") == pytest.approx(4.0)
    assert transient.detect_start(series, 2.0, 0.005, "Cd", not_before=2.5) == pytest.approx(6.5)


def _perturbed_case(case: Path) -> Path:
    _transient_case(case, start=2.0, end=5.0)
    control = transient.read_control(case)
    transient.write_control(case, transient.TransientControl(
        *[getattr(control, f) for f in ("convective_time", "length", "speed", "end_time", "window", "tolerance",
                                        "stop_quantity", "statistics_stop", "sampling_start", "detected",
                                        "field_average", "range_tolerance")],
        not_before=0.5, perturbations=("Initial-field perturbation (declared by the user): a test.",)))
    (case / INITIAL_PERTURB_FILE).write_text("expressions ();\n")
    (case / "0").mkdir()
    (case / "0" / "U").write_text("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class volVectorField;\n"
                                  "    object U;\n}\n// VortexCFD start-up perturbation: the swing\n"
                                  "internalField uniform (1 0 0);\n")
    return case


class _SetExprFields(FakeRunner):
    """setExprFields as v2606 runs it: 0/U written anew (no comment)."""

    def start(self, command, case_dir, log_file, **kwargs) -> None:
        (Path(case_dir) / "0" / "U").write_text("FoamFile\n{\n    version 2.0;\n    format ascii;\n"
                                                "    class volVectorField;\n    object U;\n}\n"
                                                "internalField nonuniform List<vector> 0();\n")
        super().start(command, case_dir, log_file, **kwargs)


def test_solver_run_applies_the_initial_field_once_and_declares_it(tmp_path: Path) -> None:
    """D-198: setExprFields runs once before the solver (log.setExprFields), the declaration opens the solver log and
    the console, the result (the run record) keeps it, and 0/U keeps its comment; a continued run does not apply
    it again; a failed setExprFields stops the run before the solver."""
    case = _perturbed_case(tmp_path / "a")
    lines, first, second = [], _SetExprFields(["End\n"]), FakeRunner(_steps(0.1, 5.0) + ["End\n"])
    queue = [first, second]
    run = SolverRun(case, on_line=lines.append, runner_factory=lambda: queue.pop(0))
    run.start()
    result = run.wait(20)
    assert first.command == ["setExprFields"] and first.log_file.name == "log.setExprFields"
    assert second.command[0] == "pimpleFoam" and second.append
    assert result.state == END_TIME
    log = solver_log(case).read_text()
    assert log.startswith("VortexCFD start-up perturbation: Initial-field perturbation (declared by the user)")
    assert "Time = " in log  # the solver's output follows
    assert any("VortexCFD start-up perturbation" in line for line in lines)
    assert result.transient["perturbation"] == ["Initial-field perturbation (declared by the user): a test."]
    u = (case / "0" / "U").read_text()
    assert u.count("// VortexCFD start-up perturbation: the swing") == 1 and "nonuniform" in u
    resumed = FakeRunner(_steps(5.1, 6.0) + ["End\n"])
    run = SolverRun(case, runner_factory=lambda: resumed, resume=ContinueFrom(50, (), False, False))
    run.start()
    run.wait(20)
    assert resumed.command[0] == "pimpleFoam"  # not setExprFields again
    case = _perturbed_case(tmp_path / "b")
    failing = FakeRunner(["--> FOAM FATAL ERROR\n"], exit_code=1)
    run = SolverRun(case, runner_factory=lambda: failing)
    run.start()
    result = run.wait(20)
    assert result.state == CRASHED and "setExprFields failed" in result.crash


def test_the_panel_declares_each_option_and_hints_without_turning_one_on(make_window) -> None:
    """D-198: each option is its own control with a visible one-line explanation; with both off a hint suggests the
    initial-field option (and turns nothing on); internal flow shows none of it."""
    w = make_window()
    panel = w.properties
    w.project.update_physics(flow="incompressible_transient")
    w._select_node("solvers", None)
    for key in ("transient_perturb_initial", "transient_perturb"):
        assert panel._rows[key].isVisibleTo(panel)
        assert panel.field_notes[key].isVisibleTo(panel) and panel.field_notes[key].text()
    assert "initial velocity" not in panel.field_notes["transient_perturb"].text()
    assert "initial field" in panel.field_notes["transient_perturb_initial"].text()
    assert panel.transient_perturb_hint.isVisibleTo(panel) and "initial-field perturbation" in (
        panel.transient_perturb_hint.text())
    assert not w.project.sim.solvers.transient.perturb_initial  # a hint only
    assert not panel._rows["transient_perturb_angle"].isVisibleTo(panel)
    panel.group_fields["transient"]["perturb_initial"].setChecked(True)  # the user turns it on
    assert w.project.sim.solvers.transient.perturb_initial
    assert not panel.transient_perturb_hint.isVisibleTo(panel)


def test_the_report_and_the_snapshot_carry_the_declaration(make_window) -> None:
    from vortexcfd.workflow import report, snapshots

    w = make_window()
    w.project.update_physics(flow="incompressible_transient")
    w.project.update_transient(perturb_initial=True)
    case = w.project.path.parent / "case"
    _transient_case_files(case)
    stats = transient.summary(_series(20.0, 0.1), 7.0, 1.0, 1.0)
    declared = ["Initial-field perturbation (declared by the user): a test."]
    write_run_record(case, RunRecord(END_TIME, 200, transient={
        "end_time": 20.0, "steps": 200, "sampling_start": 7.0, "detected": True, "convective_time": 1.0,
        "met_time": None, "statistics": stats, "perturbation": declared}))
    body = report.convergence_section(w.project).body
    assert "Start-up perturbation" in body and "Initial-field perturbation (declared by the user)" in body
    snap = snapshots.capture(w.project, "a")
    assert snap.transient["perturbation"] == declared
    assert snap.setup["transient: start-up perturbation"] == "initial field"
    assert snapshots.load(snapshots.save(w.project, snap)).transient["perturbation"] == declared
