"""Persisted result of the last solver run: case/vortexcfd_run.json (no Qt)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.foam.solver_run import STATE_LABELS

RUN_RECORD_NAME = "vortexcfd_run.json"


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

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]


def write_run_record(case_dir: Path, record: RunRecord) -> None:
    data = {
        "state": record.state,
        "iterations": record.iterations,
        "final_residuals": dict(record.final_residuals),
        "inputs_hash": record.inputs_hash,
        "exit_code": record.exit_code,
        "criteria": list(record.criteria),
        "stopped_by": list(record.stopped_by),
    }
    (Path(case_dir) / RUN_RECORD_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_run_record(case_dir: Path) -> RunRecord | None:
    """The saved record, or None if it is missing or unreadable."""
    try:
        data = json.loads((Path(case_dir) / RUN_RECORD_NAME).read_text(encoding="utf-8"))
        state = str(data["state"])
        if state not in STATE_LABELS:
            return None
        residuals = {str(k): float(v) for k, v in dict(data.get("final_residuals", {})).items()}
        code = data.get("exit_code")
        return RunRecord(state, int(data["iterations"]), residuals, str(data["inputs_hash"]),
                         None if code is None else int(code),
                         tuple(str(c) for c in data.get("criteria", [])),
                         tuple(str(c) for c in data.get("stopped_by", [])))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def remove_run_record(case_dir: Path) -> None:
    (Path(case_dir) / RUN_RECORD_NAME).unlink(missing_ok=True)
