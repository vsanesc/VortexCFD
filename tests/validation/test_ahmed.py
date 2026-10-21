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
    assert round(100 * abs(values[2] / values[1] - 1.0), 1) == 0.8  # 0.82 %, quoted as 0.8 %
    assert round(value, 3) == 0.325 and round(100 * error) == 14
    text = _round2_text()
    assert re.search(rf"\*\*Verdict: {re.escape(judged['verdict'])}\*\*", text)
    assert f"**{value:.4f}**" in text


def test_round2_reverdict_with_the_verified_references(record_r2) -> None:
    """RESULT.md, "Re-verdict with the verified references": the same V6 rule on [G08] and the vendor pages."""
    cd = record_r2["verdict"]["cd"]
    published = tuple(ac.PUBLISHED_SST_VERIFIED.values())
    assert published == (0.2915, 0.3074, 0.313)
    consistent = ac.consistent_with_sst(cd, published)
    error = cd / ac.CD_EXPERIMENT - 1.0
    assert not consistent and ac.verdict(error, consistent) == "FAIL"
    assert round(100 * (cd / max(published) - 1.0), 1) == 3.7
    assert round(100 * (cd / 0.3074 - 1.0), 1) == 5.6
    text = _round2_text()
    section = text[text.index("### Re-verdict with the verified references"):]
    assert re.search(r"\*\*Verdict \(verified references\): FAIL\*\*", section)


def test_round4_ground_keeps_its_own_stack() -> None:
    """Round 4: the ground's layer entry gets round 2's stack, the body's entries are untouched."""
    text = ('layers\n{\n    "body.*"\n    {\n        nSurfaceLayers 12;\n    }\n    ground\n    {\n'
            '        nSurfaceLayers 12;\n    }\n}\n')
    out = ac.ground_layer_override(text, 0.000635357966547543, 9, 1.2, 6.35357966547543e-05)
    assert '"body.*"\n    {\n        nSurfaceLayers 12;' in out
    assert re.search(r"ground\n\{\n    nSurfaceLayers 9;\n    firstLayerThickness 0.000635357966547543;\n"
                     r"    expansionRatio 1.2;\n    minThickness 6.35357966547543e-05;\n\}", out)
    with pytest.raises(RuntimeError):
        ac.ground_layer_override(out, 0.001, 9, 1.2, 1e-4)  # already overridden: no plain entry left


def test_round4_note_condition() -> None:
    """Round 4's V6 (owner): PASS WITH NOTE inside 0.2915-0.313 or within 3 % of Guilmineau's 0.3074."""
    assert ac.consistent_round4(0.2915) and ac.consistent_round4(0.313)
    assert ac.consistent_round4(0.3166) and not ac.consistent_round4(0.3168)  # 0.3074 * 1.03 = 0.31662
    assert not ac.consistent_round4(0.29) and not ac.consistent_round4(0.3246)
    assert ac.verdict(0.3166 / ac.CD_EXPERIMENT - 1.0, ac.consistent_round4(0.3166)) == "PASS WITH NOTE"
    assert ac.verdict(0.3246 / ac.CD_EXPERIMENT - 1.0, ac.consistent_round4(0.3246)) == "FAIL"


def test_round4_verdict_follows_from_the_recorded_values() -> None:
    """RESULT.md, "Round 4": V6 with the owner's round 4 rule on the finest level run; y+ far from 1."""
    r4 = json.loads((RECORD / "result_round4.json").read_text(encoding="utf-8"))
    fine = r4["levels"][-1]
    assert [lv["name"] for lv in r4["levels"]] == ["medium", "fine"]
    cd = fine["window"]["Cd@body"]["mean"]
    error = cd / ac.CD_EXPERIMENT - 1.0
    judged = r4["verdict"]
    assert judged["cd"] == pytest.approx(cd, rel=1e-12) and judged["basis"] == "fine"
    assert judged["consistent"] == ac.consistent_round4(cd) is True
    assert judged["verdict"] == ac.verdict(error, judged["consistent"]) == "PASS WITH NOTE"
    assert round(100 * error, 1) == 10.7 and round(100 * (cd / ac.CD_GUILMINEAU - 1.0), 1) == 2.6
    assert all(lv["yplus_body"]["mean"] > 5 for lv in r4["levels"])  # the hypothesis is not tested
    text = _round2_text()
    section = text[text.index("## Round 4"):]
    assert "**Verdict (V6, round 4 rule, finest level = fine): PASS WITH NOTE.**" in section
    assert f"**{cd:.4f}**" in section
