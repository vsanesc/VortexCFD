"""Ahmed body 25 degree validation: re-checks the recorded verdict inputs (docs/validation/ahmed/result.json,
written by scripts/validation/ahmed_study.py collect) without running OpenFOAM.

It recomputes the Celik GCI of the body's Cd from the recorded per-level means over the last
AVERAGE_WINDOW iterations and cell sizes with the
app's foam/gci.py, the value judged (the extrapolated one when the GCI is in the asymptotic range, else
the finest grid's), its error against the experimental Cd of Ahmed et al. (1984) and the V6 band, and
checks them against the recorded verdict in RESULT.md. Marker `validation` (skipped by default):

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
