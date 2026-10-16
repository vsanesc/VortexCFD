"""Flat plate validation: kOmegaSST with the app's BCs, schemes and solution settings.

Run explicitly (it is excluded from scripts/ship.sh and skipped by default):

    .venv/bin/pytest -m validation -q -s tests/validation

Results are written to docs/validation/flat_plate/ (residual history and Cf comparison CSV).
"""

import csv
from pathlib import Path

import numpy as np
import pytest

from tests.validation.flat_plate_case import (
    MAX_ITERATIONS,
    NU,
    RESIDUAL_TARGET,
    SPEED,
    PlateCase,
    PlateResult,
    build_plate_case,
    correlation,
    run_plate_case,
)
from vortexcfd.foam.logparse import LogParser
from vortexcfd.foam.yplus import yplus_of_first_cell

pytestmark = [pytest.mark.validation, pytest.mark.slow]

OUT = Path(__file__).resolve().parents[2] / "docs" / "validation" / "flat_plate"
RE_RANGE = (3e5, 1.3e6)
CF_MEAN_TOLERANCE = 0.10  # mean absolute relative error against the correlation
YPLUS_TOLERANCE = 0.30  # measured vs the estimator's prediction at mid-plate


def schlichting(re):
    """Cf = 0.455 / ln(0.06 Re_x)^2 (a more accurate flat-plate law; reported for information)."""
    return 0.455 / np.log(0.06 * np.asarray(re)) ** 2


@pytest.fixture(scope="module")
def plate(tmp_path_factory) -> tuple[PlateCase, PlateResult]:
    case = build_plate_case(tmp_path_factory.mktemp("flat_plate") / "case")
    result = run_plate_case(case, timeout_s=600.0)
    write_artifacts(case, result)
    return case, result


def write_artifacts(case: PlateCase, result: PlateResult) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parser = LogParser()
    for line in (case.case_dir / "log.simpleFoam").read_text().splitlines():
        parser.feed(line)
    fields = ["Ux", "Uz", "p", "k", "omega"]  # y is the empty direction
    with open(OUT / "residuals.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["iteration", *[f"initial_residual_{f}" for f in fields]])
        for step in parser:
            first = {name: init for name, init, _, _ in reversed(step.residuals)}
            writer.writerow([int(step.time), *[f"{first.get(f, float('nan')):.6g}" for f in fields]])
    corr, re = correlation(result.x)
    law = schlichting(np.maximum(re, 1.0))
    with open(OUT / "cf_comparison.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["x_m", "Re_x", "Cf_simulation", "Cf_0.0592_Re^-0.2", "rel_error_vs_0.0592",
                         "Cf_0.455_ln2(0.06Re)", "rel_error_vs_0.455_ln2", "yplus_first_cell"])
        for x, r, cf, c, lw, yp in zip(result.x, re, result.cf, corr, law, result.yplus):
            writer.writerow([f"{x:.4f}", f"{r:.6g}", f"{cf:.6g}", f"{c:.6g}", f"{abs(cf - c) / c:.4f}",
                             f"{lw:.6g}", f"{abs(cf - lw) / lw:.4f}", f"{yp:.4f}"])


def test_residuals_converge_within_the_iteration_budget(plate) -> None:
    case, result = plate
    assert result.converged, "residualControl (initial residuals < 1e-5) not met"
    assert result.iterations < MAX_ITERATIONS and RESIDUAL_TARGET == 1e-5
    assert result.wall_time_s < 600
    print(f"\nconverged in {result.iterations} iterations, {result.wall_time_s:.1f} s")


def test_measured_yplus_matches_the_estimator(plate) -> None:
    case, result = plate
    i = int(np.argmin(np.abs(result.x - 1.0)))  # mid-plate
    predicted = yplus_of_first_cell(case.first_cell, SPEED, NU, result.x[i])
    measured = float(result.yplus[i])
    print(f"\ny+ at x = {result.x[i]:.3f} m: measured {measured:.3f}, predicted {predicted:.3f}, "
          f"ratio {measured / predicted:.3f}")
    assert abs(measured - predicted) / predicted <= YPLUS_TOLERANCE
    assert 0.5 < float(result.yplus.mean()) < 2.0  # the mesh really is wall resolved


@pytest.mark.xfail(
    strict=True,
    reason="NOT MET (see docs/validation/flat_plate/README.md and docs/QUESTIONS.md): the app's "
           "kOmegaSST case gives a mean error of about 13 % (max 17 %) against 0.0592 Re^-0.2, "
           "independent of mesh resolution and free-stream turbulence; the app's numerics were not tuned.",
)
def test_skin_friction_matches_the_correlation(plate) -> None:
    _, result = plate
    corr, re = correlation(result.x)
    mask = (re >= RE_RANGE[0]) & (re <= RE_RANGE[1])
    err = np.abs(result.cf - corr) / corr
    law = schlichting(re[mask])
    err_law = np.abs(result.cf[mask] - law) / law
    print(f"\nCf vs 0.0592 Re^-0.2 for Re_x in {RE_RANGE}: mean error {err[mask].mean():.3%}, "
          f"max {err[mask].max():.3%} ({int(mask.sum())} faces); "
          f"vs 0.455/ln2(0.06 Re): mean {err_law.mean():.3%}, max {err_law.max():.3%}")
    assert err[mask].mean() <= CF_MEAN_TOLERANCE
