"""NACA 0012 validation (task W2; docs/validation/naca0012/RESULT.md): re-checks the recorded verdict inputs in
docs/validation/naca0012/result.json against the TMR SST references and the owner's rule A6. Marker validation:
run with `pytest -m validation`; the runs themselves are made by scripts/validation/naca0012_study.py."""

import json
from pathlib import Path

import pytest

from tests.validation import naca0012_case as nc

RESULT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "naca0012" / "result.json"
EXPECTED_VERDICTS_FILE = RESULT.with_name("verdicts.json")


@pytest.mark.validation
def test_the_references_are_the_tmr_values() -> None:
    assert nc.reference(10.0) == pytest.approx((1.07943, 0.012467), rel=1e-4)
    assert nc.reference(15.0) == pytest.approx((1.50923, 0.02227), rel=1e-4)
    assert nc.reference(0.0)[1] == pytest.approx(0.0080867, rel=1e-4)


@pytest.mark.validation
def test_the_recorded_verdicts_follow_from_the_recorded_values() -> None:
    data = json.loads(RESULT.read_text())
    expected = json.loads(EXPECTED_VERDICTS_FILE.read_text())
    for alpha, entry in expected.items():
        cl, cd = entry["CL"], entry["CD"]
        verdict, _cl_err, _cd_err = nc.verdict(float(alpha), cl, cd)
        assert verdict == entry["verdict"], (alpha, verdict, entry)
        if "level" in entry:  # 10 deg: the study's level
            source = [lv for lv in data["levels"] if lv["name"] == entry["level"]]
        else:  # the single runs that were solved (a run with an invalid mesh has no values)
            source = [r for r in data["angles"] if r["alpha"] == float(alpha) and "values" in r and r.get("radius") is None
                      and r["values"].get("Cd") == pytest.approx(entry["CD"])]
        assert source, alpha
        values = source[0]["values"]
        assert values["Cl"] == pytest.approx(cl) and values["Cd"] == pytest.approx(cd)
        share = source[0].get("first_cell_share_over_2x")
        assert not nc.collapsed(share)  # A6: a collapsed level is never judged
