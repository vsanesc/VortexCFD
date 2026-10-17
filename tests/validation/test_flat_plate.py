"""Flat plate verification (short): kOmegaSST with the app's BCs, schemes and solution settings.

Case A (low Re, informative): U = 10 m/s, Re_L = 1.3e6. Reported and diagnosed, not pass/fail.
Case B (the arbiter, D-036): the NASA TMR 2D zero pressure gradient flat plate (Re = 5e6 per metre,
plate 0 to 2 m). This test runs the coarse and medium grids of the wall-normal grid study only and
checks them against the TMR incompressible SST reference (tests/data/tmr/) and against the committed
full study (docs/validation/flat_plate/case_b_grid_study.json, written by
scripts/validation/flat_plate_study.py), whose finest grid is not recomputed here.

Run explicitly (skipped by default, excluded from scripts/ship.sh; about 20 min, the three runs are
concurrent, dominated by the medium grid):

    .venv/bin/pytest -m validation -q -s tests/validation

Writes the Case A results to docs/validation/flat_plate/ (Case B files come from the full study).
"""

import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from tests.validation import flat_plate_report as report
from tests.validation import tmr
from tests.validation.flat_plate_case import (
    CASE_A,
    CASE_B_GRIDS,
    MAX_ITERATIONS,
    RESIDUAL_TARGET,
    build_plate_case,
    diagnose,
    run_plate_case,
)
from vortexcfd.foam.yplus import yplus_of_first_cell

pytestmark = [pytest.mark.validation, pytest.mark.slow]

WALL_CLOCK_BUDGET_S = 15 * 60  # Case A
GRID_BUDGET_S = 30 * 60  # each Case B run (coarse and medium)
YPLUS_TOLERANCE = 0.30  # measured vs the estimator's prediction at mid-plate
MIN_BL_CELLS = 30  # cells across the boundary layer (delta99) at x = 0.97
MEDIUM_LIMIT = tmr.NOTE_LIMIT  # |error| of the medium grid's Cf(0.97) against the TMR reference
REPRODUCTION_TOLERANCE = 1e-3  # fresh coarse/medium Cf(0.97) against the committed study (relative)
EXPECTED_VERDICT = "PASS WITH NOTE"  # the committed full study (D-036)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Case A and the coarse and medium Case B grids, run concurrently."""
    root = tmp_path_factory.mktemp("plate")
    jobs = {"A": (CASE_A, WALL_CLOCK_BUDGET_S), "B1": (CASE_B_GRIDS[0], GRID_BUDGET_S),
            "B2": (CASE_B_GRIDS[1], GRID_BUDGET_S)}

    def run(item):
        tag, (setup, budget) = item
        case = build_plate_case(root / tag / "case", setup)
        return tag, (case, run_plate_case(case, timeout_s=budget))

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return dict(pool.map(run, jobs.items()))


@pytest.fixture(scope="module")
def case_a(runs):
    case, result = runs["A"]
    report.write_artifacts(report.OUT, "A", case, result)
    diagnosis = diagnose(case, result)
    (report.OUT / "case_a_diagnosis.json").write_text(json.dumps(diagnosis, indent=2) + "\n")
    return case, result, diagnosis


@pytest.fixture(scope="module")
def case_b(runs):
    """Grid rows of the fresh coarse and medium runs and the committed full study."""
    rows = [report.grid_row(*runs[tag]) for tag in ("B1", "B2")]
    return runs, rows, report.load_study()


# -- Case A: informative ---------------------------------------------------------------------------------------


def test_case_a_runs_and_is_diagnosed(case_a) -> None:
    """Not pass/fail on Cf: the run must converge and the diagnosis must be physically sane."""
    case, result, d = case_a
    assert result.converged and result.iterations < MAX_ITERATIONS and RESIDUAL_TARGET == 1e-5
    print(f"\nCase A: converged in {result.iterations} iterations, {result.wall_time_s:.1f} s")
    for row in d["rows"]:
        print(f"  Re_x {row['Re_x']:.3g}: Cf {row['cf_sim']:.4g}  0.0592: {row['cf_power']:.4g} "
              f"({row['err_power']:+.1%})  White: {row['cf_white']:.4g} ({row['err_white']:+.1%})  "
              f"max nut/nu {row['nut_ratio_max']:.1f}")
    print(f"  free stream at the leading edge: k {d['k_le']:.4g} / {d['k_in']:.4g} = {d['k_decay']:.3f}, "
          f"omega {d['omega_le']:.4g} / {d['omega_in']:.4g} = {d['omega_decay']:.3f}")
    assert all(row["cf_sim"] > 0 for row in d["rows"]) and 0 < d["k_decay"] <= 1.0


# -- Case B: the arbiter (TMR verification, coarse and medium grids) --------------------------------------------


def test_case_b_runs_converge_within_budget(case_b) -> None:
    runs, rows, _ = case_b
    for row in rows:
        print(f"\n{row['cells_normal']} wall-normal cells: {row['iterations']} iterations, {row['wall_time_s']:.0f} s")
        assert row["converged"], "residualControl (initial residuals < 1e-5) not met"
        assert row["wall_time_s"] < GRID_BUDGET_S


def test_case_b_measured_yplus_matches_the_estimator(case_b) -> None:
    runs, _, _ = case_b
    case, result = runs["B1"]  # the coarse grid's first cell comes from the estimator
    i = int(np.argmin(np.abs(result.x - 1.0)))  # mid-plate
    predicted = yplus_of_first_cell(case.first_cell, case.setup.speed, case.setup.nu, result.x[i])
    measured = float(result.yplus[i])
    print(f"\ny+ at x = {result.x[i]:.3f} m: measured {measured:.3f}, predicted {predicted:.3f}, "
          f"ratio {measured / predicted:.3f}; range {float(result.yplus.min()):.2f} .. "
          f"{float(result.yplus.max()):.2f}")
    assert abs(measured - predicted) / predicted <= YPLUS_TOLERANCE


def test_case_b_medium_grid_against_tmr(case_b) -> None:
    """Medium grid within 5 % of the TMR reference, and the error decreases from coarse to medium."""
    _, (coarse, medium), _ = case_b
    for row in (coarse, medium):
        print(f"\n  {row['cells_normal']} cells, y+ {row['yplus_0.97']:.3f}, {row['cells_in_delta99']} cells in "
              f"delta99, Cf(0.97) {row['cf_0.97']:.5g}, error vs TMR {row['error']:+.2%}")
        assert row["cells_in_delta99"] >= MIN_BL_CELLS
    assert abs(medium["error"]) <= MEDIUM_LIMIT
    assert abs(medium["error"]) < abs(coarse["error"])


def test_case_b_matches_the_committed_study_and_its_verdict(case_b) -> None:
    """The fresh coarse and medium grids reproduce the committed study, so its finest grid still
    applies; the verdict band with the committed finest grid is the recorded one."""
    _, rows, committed = case_b
    for fresh, old in zip(rows, committed["grids"]):
        assert fresh["cells_normal"] == old["cells_normal"]
        assert fresh["cf_0.97"] == pytest.approx(old["cf_0.97"], rel=REPRODUCTION_TOLERANCE)
    study = report.grid_study([*rows, committed["grids"][2]])
    print(f"\n  with the committed fine grid: p {study['order']:.2f}, extrapolated {study['extrapolated']:.5g}, "
          f"GCI {study['gci_fine']:.3%}, error {study['error']:+.2%}: {study['verdict']}")
    assert committed["verdict"] == EXPECTED_VERDICT
    band = {"PASS": tmr.PASS_LIMIT, "PASS WITH NOTE": tmr.NOTE_LIMIT}[EXPECTED_VERDICT]
    assert abs(study["error"]) <= band, study["verdict"]
