"""Persisted result of the last solver run: case/vortexcfd_run.json (no Qt)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from vortexcfd.core.atomic_io import write_text_atomic
from vortexcfd.core.model import StoppingCriteria
from vortexcfd.foam.solver_run import CRITERIA_MET, STATE_LABELS, state_label

RUN_RECORD_NAME = "vortexcfd_run.json"
# States written by older versions and the state they are read as (D-058: "Converged" became
# "Criteria met").
OLD_STATES = {"converged": CRITERIA_MET}


@dataclass(frozen=True)
class RunRecord:
    state: str  # one of solver_run.STATE_LABELS
    iterations: int
    final_residuals: dict[str, float] = field(default_factory=dict)
    inputs_hash: str = ""  # hash of the solver inputs the results were computed from
    exit_code: int | None = None
    # Stopping criteria of the run (descriptions, convergence.describe) and those that stopped it.
    criteria: tuple[str, ...] = ()
    stopped_by: tuple[str, ...] = ()
    # Short names of the criteria that stopped it (convergence.short_label) and the iteration at
    # which they were met (the solver writes the iteration it was in when the app stopped it).
    met_labels: tuple[str, ...] = ()
    met_iteration: int | None = None
    # Solver wall time (s, without decomposePar / reconstructPar) and MPI ranks: the mesh study's
    # time estimate (D-066). Absent in older records (None / 1).
    duration_s: float | None = None
    cores: int = 1
    # The turbulence stages of a two-stage run (D-126; solver_run.SolverRunResult.stages) and the last iteration
    # of stage 1. Absent in single-stage and older records.
    stages: tuple[dict, ...] = ()
    switch_iteration: int | None = None
    # The run's stopping criteria as it started (a core.model.StoppingCriteria dump, D-165): the monitors show them
    # as "the last run's" next to the project's current ones. None in older records.
    stopping: dict | None = None
    # The run's segments (D-171): one dict per solver run that wrote into this solution, in order: first and last
    # iteration, state, cores, solver time (s), and for a continued one the iteration it started from and whether
    # the settings had changed ("settings_changed"). A record written before keeps none (one run).
    segments: tuple[dict, ...] = ()
    # Hash of the solution's settings without the iteration limit, the write interval and the stopping criteria
    # (workflow/solving.solution_hash): Continue compares it to tell a changed set-up (D-171). "" in older records.
    settings_hash: str = ""
    # A transient run (D-181; solver_run.SolverRunResult.transient): the end time, the steps, the sampling start and
    # the statistics. None for a steady run and in older records.
    transient: dict | None = None

    @property
    def label(self) -> str:
        return state_label(self.state, self.met_labels)


def _data(record: RunRecord) -> dict:
    return {
        "state": record.state,
        "iterations": record.iterations,
        "final_residuals": dict(record.final_residuals),
        "inputs_hash": record.inputs_hash,
        "exit_code": record.exit_code,
        "criteria": list(record.criteria),
        "stopped_by": list(record.stopped_by),
        "met_labels": list(record.met_labels),
        "met_iteration": record.met_iteration,
        "duration_s": record.duration_s,
        "cores": record.cores,
        **({"stages": [dict(s) for s in record.stages], "switch_iteration": record.switch_iteration}
           if record.stages else {}),
        **({"stopping": record.stopping} if record.stopping is not None else {}),
        **({"segments": [dict(seg) for seg in record.segments]} if record.segments else {}),
        **({"settings_hash": record.settings_hash} if record.settings_hash else {}),
        **({"transient": record.transient} if record.transient is not None else {}),
    }


def write_run_record(case_dir: Path, record: RunRecord) -> None:
    write_text_atomic(Path(case_dir) / RUN_RECORD_NAME, json.dumps(_data(record), indent=2) + "\n")


def read_run_record(case_dir: Path) -> RunRecord | None:
    """The saved record, or None if it is missing or unreadable. A record with an old state
    (OLD_STATES) is migrated: read with the new state and written back."""
    try:
        data = json.loads((Path(case_dir) / RUN_RECORD_NAME).read_text(encoding="utf-8"))
        state = str(data["state"])
        migrated = state in OLD_STATES
        state = OLD_STATES.get(state, state)
        if state not in STATE_LABELS:
            return None
        residuals = {str(k): float(v) for k, v in dict(data.get("final_residuals", {})).items()}
        code = data.get("exit_code")
        met_it = data.get("met_iteration")
        record = RunRecord(state, int(data["iterations"]), residuals, str(data["inputs_hash"]),
                           None if code is None else int(code),
                           tuple(str(c) for c in data.get("criteria", [])),
                           tuple(str(c) for c in data.get("stopped_by", [])),
                           tuple(str(c) for c in data.get("met_labels", [])),
                           None if met_it is None else int(met_it),
                           None if data.get("duration_s") is None else float(data["duration_s"]),
                           int(data.get("cores", 1)),
                           tuple(dict(s) for s in data.get("stages", [])),
                           None if data.get("switch_iteration") is None else int(data["switch_iteration"]),
                           dict(data["stopping"]) if isinstance(data.get("stopping"), dict) else None,
                           tuple(dict(seg) for seg in data.get("segments", [])),
                           str(data.get("settings_hash", "")),
                           dict(data["transient"]) if isinstance(data.get("transient"), dict) else None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if migrated:
        try:
            write_run_record(case_dir, record)
        except OSError:
            pass  # read-only case: the record is still shown with the new state
    return record


def record_stopping(record: RunRecord | None) -> StoppingCriteria | None:
    """The stopping criteria a recorded run started with (D-165); None when the record predates them or they no
    longer validate."""
    if record is None or record.stopping is None:
        return None
    try:
        return StoppingCriteria.model_validate(record.stopping)
    except ValidationError:
        return None


def remove_run_record(case_dir: Path) -> None:
    (Path(case_dir) / RUN_RECORD_NAME).unlink(missing_ok=True)
