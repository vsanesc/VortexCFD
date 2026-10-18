"""Persisted result of the last solver run: case/vortexcfd_run.json (no Qt)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

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
    }


def write_run_record(case_dir: Path, record: RunRecord) -> None:
    (Path(case_dir) / RUN_RECORD_NAME).write_text(json.dumps(_data(record), indent=2) + "\n", encoding="utf-8")


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
                           None if met_it is None else int(met_it))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if migrated:
        try:
            write_run_record(case_dir, record)
        except OSError:
            pass  # read-only case: the record is still shown with the new state
    return record


def remove_run_record(case_dir: Path) -> None:
    (Path(case_dir) / RUN_RECORD_NAME).unlink(missing_ok=True)
