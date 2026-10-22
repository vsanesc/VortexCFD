"""The Ahmed validation driver's solver time estimate (scripts/validation/ahmed_study.py, the deadline
guard): the rate measured on the round's own levels at the same core count, else round 1's rate."""

import json
from pathlib import Path

import pytest

from tests.validation import ahmed_case as ac

# Round 2 as run (RESULT.md, "Round 2"): cells, iterations, solver seconds on 8 cores
COARSE_R2 = (245_577, 1164, 400.0)
MEDIUM_R2 = (627_219, 1006, 1128.0)


def _level_record(folder: Path, name: str, cores: int, cells: int, iterations: int, seconds: float,
                  state: str = "criteria_met") -> None:
    """A study_<level>.json as the driver keeps it: the whole record, only ``name`` run."""
    levels = [{"index": i, "name": n, "factor": 1.0, "cells": None, "iterations": None, "duration_s": None,
               "state": None} for i, n in enumerate(ac.LEVELS)]
    levels[ac.LEVELS.index(name)].update(cells=cells, iterations=iterations, duration_s=seconds, state=state)
    (folder / f"study_{name}.json").write_text(json.dumps({"cores": cores, "levels": levels}), encoding="utf-8")


def test_without_a_measured_level_the_estimate_uses_round_1s_rate(tmp_path: Path) -> None:
    assert ac.measured_rates(tmp_path, 8) == {}
    mesh_s, solve_s, source = ac.estimate_level("fine", 1_982_625, ac.ITERATIONS, ac.measured_rates(tmp_path, 8))
    assert solve_s == pytest.approx(4564.0 / 1_338_191 * 1_982_625)  # 112.7 min (SETUP.md, "Plan")
    assert mesh_s == pytest.approx(1.5 * 167.0 * 1_982_625 / 1_338_191)
    assert source == "round 1's fine on 4 cores"


def test_the_estimate_uses_the_measured_rate_of_the_round_at_the_same_cores(tmp_path: Path) -> None:
    _level_record(tmp_path, "coarse", 8, *COARSE_R2)
    _level_record(tmp_path, "medium", 8, *MEDIUM_R2)
    (tmp_path / "study_events_coarse.json").write_text("{}", encoding="utf-8")  # not a level record
    measured = ac.measured_rates(tmp_path, 8)
    assert measured["coarse"][1] == pytest.approx(1.40e-6, rel=0.01)  # 1.40 us per cell-iteration
    assert measured["medium"][1] == pytest.approx(1.79e-6, rel=0.01)
    # the fine level: the measured level nearest in cells (medium), as the fine level was planned that night
    _, solve_s, source = ac.estimate_level("fine", 1_982_625, ac.ITERATIONS, measured)
    assert solve_s == pytest.approx(1128.0 / (627_219 * 1006) * 1_982_625 * ac.ITERATIONS)
    assert source == "measured, medium of this round"
    # a level run again: its own rate
    _, solve_s, source = ac.estimate_level("coarse", 250_000, 1000, measured)
    assert solve_s == pytest.approx(400.0 / (245_577 * 1164) * 250_000 * 1000)
    assert source == "measured, coarse of this round"
    # another core count does not count: round 1's rate
    assert ac.measured_rates(tmp_path, 4) == {}
    assert ac.estimate_level("fine", 1_982_625, ac.ITERATIONS, ac.measured_rates(tmp_path, 4))[2].startswith("round 1")


def test_a_crashed_or_unfinished_level_is_not_a_measured_rate(tmp_path: Path) -> None:
    _level_record(tmp_path, "coarse", 8, *COARSE_R2, state="crashed")
    _level_record(tmp_path, "medium", 8, 627_219, None, None, state=None)
    (tmp_path / "study_fine.json").write_text("{not json", encoding="utf-8")
    assert ac.measured_rates(tmp_path, 8) == {}
