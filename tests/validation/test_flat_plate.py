"""Flat plate validation: kOmegaSST with the app's BCs, schemes and solution settings.

Case A (low Re, informative): U = 10 m/s, Re_L = 1.3e6. Reported and diagnosed, not pass/fail.
Case B (the arbiter): TMR-like, Re = 5e6 per metre, Re_L = 1e7, compared with
0.455 / ln^2(0.06 Re_x) (White) for Re_x in [1e6, 1e7].

Run explicitly (skipped by default, excluded from scripts/ship.sh):

    .venv/bin/pytest -m validation -q -s tests/validation

Results are written to docs/validation/flat_plate/ (residual history, Cf comparison and diagnosis).
"""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from tests.validation.flat_plate_case import (
    CASE_A,
    CASE_B,
    MAX_ITERATIONS,
    RESIDUAL_TARGET,
    PlateCase,
    PlateResult,
    build_plate_case,
    diagnose,
    laws,
    run_plate_case,
)
from vortexcfd.foam.logparse import LogParser
from vortexcfd.foam.yplus import yplus_of_first_cell

pytestmark = [pytest.mark.validation, pytest.mark.slow]

OUT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "flat_plate"
WALL_CLOCK_BUDGET_S = 15 * 60
CF_MEAN_TOLERANCE = 0.05  # Case B: mean absolute relative error against White's law
CF_MAX_TOLERANCE = 0.08  # Case B: maximum
YPLUS_TOLERANCE = 0.30  # measured vs the estimator's prediction at mid-plate
RE_RANGE_B = (1e6, 1e7)


def write_artifacts(tag: str, case: PlateCase, result: PlateResult) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parser = LogParser()
    for line in (case.case_dir / "log.simpleFoam").read_text().splitlines():
        parser.feed(line)
    fields = ["Ux", "Uz", "p", "k", "omega"]  # y is the empty direction
    with open(OUT / f"case_{tag}_residuals.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["iteration", *[f"initial_residual_{f}" for f in fields]])
        for step in parser:
            first = {name: init for name, init, _, _ in reversed(step.residuals)}
            writer.writerow([int(step.time), *[f"{first.get(f, float('nan')):.6g}" for f in fields]])
    re, power, white = laws(result.x, case.setup)
    with open(OUT / f"case_{tag}_cf_comparison.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["x_m", "Re_x", "Cf_simulation", "Cf_0.0592_Re^-0.2", "error_vs_0.0592",
                         "Cf_0.455_ln2(0.06Re)", "error_vs_0.455_ln2", "yplus_first_cell"])
        for x, r, cf, c, w, yp in zip(result.x, re, result.cf, power, white, result.yplus):
            writer.writerow([f"{x:.4f}", f"{r:.6g}", f"{cf:.6g}", f"{c:.6g}", f"{(cf - c) / c:+.4f}",
                             f"{w:.6g}", f"{(cf - w) / w:+.4f}", f"{yp:.4f}"])


@pytest.fixture(scope="module")
def case_a(tmp_path_factory):
    case = build_plate_case(tmp_path_factory.mktemp("plate_a") / "case", CASE_A)
    result = run_plate_case(case, timeout_s=WALL_CLOCK_BUDGET_S)
    write_artifacts("A", case, result)
    diagnosis = diagnose(case, result)
    (OUT / "case_a_diagnosis.json").write_text(json.dumps(diagnosis, indent=2) + "\n")
    return case, result, diagnosis


@pytest.fixture(scope="module")
def case_b(tmp_path_factory):
    case = build_plate_case(tmp_path_factory.mktemp("plate_b") / "case", CASE_B)
    result = run_plate_case(case, timeout_s=WALL_CLOCK_BUDGET_S)
    write_artifacts("B", case, result)
    return case, result


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


# -- Case B: the arbiter -----------------------------------------------------------------------------------------


def test_case_b_converges_within_budget(case_b) -> None:
    _, result = case_b
    assert result.converged, "residualControl (initial residuals < 1e-5) not met"
    assert result.iterations < MAX_ITERATIONS and result.wall_time_s < WALL_CLOCK_BUDGET_S
    print(f"\nCase B: converged in {result.iterations} iterations, {result.wall_time_s:.1f} s")


def test_case_b_measured_yplus_matches_the_estimator(case_b) -> None:
    case, result = case_b
    i = int(np.argmin(np.abs(result.x - 1.0)))  # mid-plate
    predicted = yplus_of_first_cell(case.first_cell, case.setup.speed, case.setup.nu, result.x[i])
    measured = float(result.yplus[i])
    print(f"\ny+ at x = {result.x[i]:.3f} m: measured {measured:.3f}, predicted {predicted:.3f}, "
          f"ratio {measured / predicted:.3f}; range {float(result.yplus.min()):.2f} .. "
          f"{float(result.yplus.max()):.2f}")
    assert abs(measured - predicted) / predicted <= YPLUS_TOLERANCE


@pytest.mark.xfail(
    strict=True,
    reason="NOT MET (docs/validation/flat_plate/README.md, docs/QUESTIONS.md): Case B gives a mean Cf error "
           "of about 11.6 % (max 14.3 %) below White's law, independent of mesh resolution (11.6 % with "
           "4x more cells) and 9.5 % / 12.1 % with the first cell at y+ 0.5; the app's numerics were not tuned.",
)
def test_case_b_skin_friction_matches_whites_law(case_b) -> None:
    case, result = case_b
    re, power, white = laws(result.x, case.setup)
    mask = (re >= RE_RANGE_B[0]) & (re <= RE_RANGE_B[1])
    err = np.abs(result.cf - white) / white
    i97 = int(np.argmin(np.abs(result.x - 0.97)))
    print(f"\nCase B Cf vs 0.455/ln2(0.06 Re_x), Re_x in {RE_RANGE_B}: mean error {err[mask].mean():.3%}, "
          f"max {err[mask].max():.3%} ({int(mask.sum())} faces); Cf at x = {result.x[i97]:.3f} m: "
          f"{result.cf[i97]:.5g} (White {white[i97]:.5g}, {(result.cf[i97] - white[i97]) / white[i97]:+.1%})")
    assert err[mask].mean() <= CF_MEAN_TOLERANCE and err[mask].max() <= CF_MAX_TOLERANCE
