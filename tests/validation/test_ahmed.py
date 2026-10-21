"""Ahmed body 25 degree validation: re-checks the recorded verdict inputs (docs/validation/ahmed/result.json,
written by scripts/validation/ahmed_study.py collect) without running OpenFOAM.

It recomputes the Celik GCI of the body's Cd from the recorded per-level means over the last
AVERAGE_WINDOW iterations and cell sizes with the
app's foam/gci.py, the value judged (the extrapolated one when the GCI is in the asymptotic range, else
the finest grid's), its error against the experimental Cd of Ahmed et al. (1984) and the V6 band, and
checks them against the recorded verdict in RESULT.md. Round 2 (result_round2.json, RESULT.md "Round 2"):
the same on the means over the mean-stable criterion's window at each level's stop. Marker `validation`
(skipped by default):

    .venv/bin/pytest -m validation -q tests/validation/test_ahmed.py
"""

import json
import re
from pathlib import Path

import pytest

from tests.validation import ahmed_case as ac

pytestmark = pytest.mark.validation

RECORD = Path(__file__).resolve().parents[2] / "docs" / "validation" / "ahmed"


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads((RECORD / "result.json").read_text(encoding="utf-8"))


def test_the_recorded_study_is_complete(record) -> None:
    assert [lv["name"] for lv in record["levels"]] == ["coarse", "medium", "fine"]
    for level in record["levels"]:
        assert level["check"]["failed_checks"] == 0 and level["cells"] > 0
        assert level["window"]["Cd@body"]["n"] == ac.AVERAGE_WINDOW


def test_the_gci_and_the_verdict_follow_from_the_recorded_values(record) -> None:
    levels = record["levels"]
    values = [lv["window"]["Cd@body"]["mean"] for lv in levels]
    sizes = [lv["h_m"] for lv in levels]
    value, basis, result = ac.judged_value(values, sizes)
    row = record["gci_window_means"]["Cd@body"]
    assert row["convergence"] == result.convergence
    if result.applicable:
        assert row["gci_fine"] == pytest.approx(result.gci_fine, rel=1e-9)
        assert row["extrapolated"] == pytest.approx(result.extrapolated, rel=1e-9)
    judged = record["verdict"]
    assert judged["basis"] == basis and judged["cd"] == pytest.approx(value, rel=1e-9)
    error = value / ac.CD_EXPERIMENT - 1.0
    assert judged["error"] == pytest.approx(error, rel=1e-9)
    assert judged["consistent_with_sst"] == ac.consistent_with_sst(value)
    assert judged["verdict"] == ac.verdict(error, judged["consistent_with_sst"])
    text = (RECORD / "RESULT.md").read_text(encoding="utf-8")
    assert re.search(rf"\*\*Verdict: {re.escape(judged['verdict'])}\*\*", text)


def test_the_body_and_stilt_forces_add_up(record) -> None:
    """Per-part forces (D-073): all walls = body + the two stilts (the ground is in none of them)."""
    for level in record["levels"]:
        v = {q: w["mean"] for q, w in level["window"].items()}  # means are linear: the parts add up
        assert v["Cd"] == pytest.approx(v["Cd@body"] + v["Cd@stilt_front"] + v["Cd@stilt_rear"], abs=2e-6)
        assert v["Cd@body"] == pytest.approx(v["Cd_pressure@body"] + v["Cd_viscous@body"], abs=2e-6)


# -- round 2 (owner review of round 1; RESULT.md "Round 2") --------------------------------------------


@pytest.fixture(scope="module")
def record_r2() -> dict:
    return json.loads((RECORD / "result_round2.json").read_text(encoding="utf-8"))


def _round2_text() -> str:
    text = (RECORD / "RESULT.md").read_text(encoding="utf-8")
    return text[text.index("\n## Round 2"):]


def test_round2_levels_stopped_on_the_mean_stable_window(record_r2) -> None:
    window = ac.stopping_round2().criteria[0].window
    assert record_r2["average_window"] == window
    assert [lv["name"] for lv in record_r2["levels"]] == ["coarse", "medium", "fine"]
    for level in record_r2["levels"]:
        assert level["check"]["failed_checks"] == 0 and level["cells"] > 0
        assert level["criteria_met"] and "mean stable" in level["state_label"]
        assert not level["stopped_at_deadline"] and level["iterations"] < ac.ITERATIONS
        assert level["window"]["Cd@body"]["n"] == window
        v = {q: w["mean"] for q, w in level["window"].items()}
        assert v["Cd"] == pytest.approx(v["Cd@body"] + v["Cd@stilt_front"] + v["Cd@stilt_rear"], abs=2e-6)
        assert v["Cd@body"] == pytest.approx(v["Cd_pressure@body"] + v["Cd_viscous@body"], abs=2e-6)


def test_round2_gci_and_verdict_follow_from_the_recorded_values(record_r2) -> None:
    levels = record_r2["levels"]
    values = [lv["window"]["Cd@body"]["mean"] for lv in levels]
    sizes = [lv["h_m"] for lv in levels]
    value, basis, result = ac.judged_value(values, sizes)
    row = record_r2["gci_window_means"]["Cd@body"]
    assert row["values"] == pytest.approx(values, rel=1e-12)
    assert row["convergence"] == result.convergence == "oscillatory" and not result.applicable
    judged = record_r2["verdict"]
    assert judged["basis"] == basis == "fine" and judged["cd"] == pytest.approx(value, rel=1e-9)
    error = value / ac.CD_EXPERIMENT - 1.0
    assert judged["error"] == pytest.approx(error, rel=1e-9)
    assert judged["error_alt"] == pytest.approx(value / ac.CD_EXPERIMENT_ALT - 1.0, rel=1e-9)
    assert judged["consistent_with_sst"] == ac.consistent_with_sst(value) is False
    assert judged["verdict"] == ac.verdict(error, judged["consistent_with_sst"]) == "FAIL"
    # the owner's reading (RESULT.md, "Reading of round 2"): medium and fine within 0.8 %, Cd about 0.325, +14 %
    assert abs(values[2] / values[1] - 1.0) < 0.008
    assert round(value, 3) == 0.325 and round(100 * error) == 14
    text = _round2_text()
    assert re.search(rf"\*\*Verdict: {re.escape(judged['verdict'])}\*\*", text)
    assert f"**{value:.4f}**" in text
