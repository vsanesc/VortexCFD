"""Circular cylinder at Re 100 (task 1.1-transient, Part B; docs/validation/cylinder_re100/RESULT.md): re-checks the
recorded verdicts in docs/validation/cylinder_re100/result.json against the pass rule of SETUP.md. Marker validation:
run with `pytest -m validation`; the runs themselves are made by scripts/validation/cylinder_study.py."""

import json
from pathlib import Path

import pytest

from tests.validation import cylinder_case as cc

RESULT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "cylinder_re100" / "result.json"


@pytest.mark.validation
def test_the_pass_rule() -> None:
    assert cc.RE == pytest.approx(100.0)
    assert cc.verdict(0.165, 1.35, 0.253)[0] == "PASS"
    assert cc.verdict(0.170, 1.35, 0.253)[1]["st"] == pytest.approx(0.005 / 0.165)
    assert cc.verdict(0.171, 1.35, 0.253)[0] == "FAIL"  # 3.6 % above the band
    assert cc.verdict(0.165, 1.43, 0.253)[0] == "FAIL"  # Cd +5.9 %
    assert cc.verdict(0.165, 1.35, 0.295)[0] == "FAIL"  # Cl RMS +16.6 %


@pytest.mark.validation
def test_the_recorded_verdicts_follow_from_the_recorded_values() -> None:
    data = json.loads(RESULT.read_text())
    levels = {row["level"]: row for row in data["levels"]}
    for row in levels.values():
        verdict, errors = cc.verdict(row["st"], row["cd_mean"], row["cl_rms"])
        assert verdict == row["verdict"] and errors == pytest.approx(row["errors"])
        assert row["cycles"] >= 3.0  # SETUP.md: a level with fewer cycles does not count
    assert levels["fine"]["verdict"] == "PASS"
