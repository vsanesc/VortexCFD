# Flat plate validation (Task 4A)

**Verdict: NOT MET.** The converged case is mesh-independent and wall-resolved, the y+ estimator is
confirmed, but the skin friction is on average 13.1 % (max 17.0 %) below the correlation
Cf = 0.0592 Re_x^-0.2, against the required mean error of at most 10 %. The app's numerics were not
tuned to pass (see "Attempts" and docs/QUESTIONS.md).

Run it with `.venv/bin/pytest -m validation -q -s tests/validation` (about 30 s; skipped by default,
excluded from `scripts/ship.sh`; run it after every change to the physics or numerics).
`test_skin_friction_matches_the_correlation` is a strict xfail until the verdict changes.

## Setup

- 2D zero-pressure-gradient turbulent flat plate: slip leading section x = -0.3 .. 0 m, no-slip plate
  x = 0 .. 2 m, domain height 0.5 m (> 10 boundary layer thicknesses; delta ~ 0.044 m at x = 2 m),
  one empty cell in y.
- U = 10 m/s, nu = 1.5e-5 m2/s, so Re_L = 1.33e6. Free stream: the app's defaults (turbulence
  intensity 1 %, viscosity ratio 10).
- Mesh from blockMesh by a test helper (`tests/validation/flat_plate_case.py`), 230 x 100 cells. The
  wall-normal grading starts with the y+ estimator's first cell (`first_layer_thickness` for a target
  of 2, 7.2e-5 m, i.e. y+ about 1 at the cell centre at the plate end) and grows by 1.063 per cell.
- Everything else is the app's builder (`foam/physics_case.py`): kOmegaSST, the BCs (inlet fixedValue,
  outlet inletOutlet/p fixedValue, top and leading section slip, plate noSlip with kqRWallFunction,
  omegaWallFunction, nutUSpaldingWallFunction), the motorBike schemes and solution settings (SIMPLEC,
  U 0.9, k/omega 0.7). Only `sides` is `empty` (2D) and `residualControl 1e-5` is added for p, U, k and
  omega as the stopping criterion.
- simpleFoam, wallShearStress and writeCellCentres post-processing, Cf = |tau_w| / (0.5 U^2) from the
  kinematic wall shear stress on the plate patch.

## Results (default case)

| Quantity | Value |
|---|---|
| Iterations to convergence (all initial residuals < 1e-5) | 494 (limit 3000) |
| Wall time (simpleFoam) | 24 s |
| Cf vs 0.0592 Re_x^-0.2, Re_x 3e5 .. 1.3e6 (150 faces): mean / max error | **13.1 % / 17.0 %** (tolerance: mean <= 10 %) |
| y+ of the first cell at mid-plate (x = 1.0 m): measured / estimator | 1.003 / 1.050 (ratio 0.955, tolerance 30 %) **met** |
| y+ over the plate (min / mean / max) | 0.96 / 1.03 / 2.3 |

| x (m) | Re_x | Cf simulation | Cf 0.0592 Re^-0.2 | error | Cf 0.455/ln^2(0.06 Re) | error |
|---|---|---|---|---|---|---|
| 0.455 | 3.03e5 | 3.933e-3 | 4.742e-3 | 17.1 % | 4.729e-3 | 16.8 % |
| 0.495 | 3.30e5 | 3.883e-3 | 4.663e-3 | 16.7 % | 4.649e-3 | 16.5 % |
| 1.005 | 6.70e5 | 3.490e-3 | 4.047e-3 | 13.8 % | 4.048e-3 | 13.8 % |
| 1.495 | 9.97e5 | 3.296e-3 | 3.738e-3 | 11.8 % | 3.761e-3 | 12.4 % |
| 1.945 | 1.30e6 | 3.182e-3 | 3.546e-3 | 10.3 % | 3.587e-3 | 11.3 % |

Files: `residuals.csv` (initial residuals per iteration), `cf_comparison.csv` (per face: x, Re_x, Cf
simulation, both laws, relative errors, y+). The second column of laws is informational (a more
accurate flat-plate law, Cf = 0.455 / ln^2(0.06 Re_x)); it is not part of the criterion.

## Attempts (only the case was varied, never the app's numerics)

| # | Variation | Iterations | Mean / max Cf error | y+ ratio |
|---|---|---|---|---|
| 1 | default: 230 x 100 cells, I = 1 %, ratio 10 | 494 | 13.1 % / 17.0 % | 0.955 |
| 2 | refined: 430 x 150 cells | 879 | 13.0 % / 16.9 % | 0.956 |
| 3a | free stream I = 5 % | 511 | 13.0 % / 16.7 % | 0.956 |
| 3b | free stream I = 0.1 %, ratio 1 | 507 | 13.4 % / 17.3 % | 0.954 |
| 3c | free stream I = 3 %, ratio 100 (not physical for a plate) | 499 | 10.8 % / 14.6 % | 0.968 |

The result does not depend on the mesh or on realistic free-stream turbulence, so it is not a
discretisation or set-up artefact of the case. The error shrinks along the plate (17 % at Re_x 3e5, 10 %
at 1.3e6) and the simulation also differs by 13 % from the more accurate law, which points at the
model's behaviour at low Re_x (the boundary layer does not behave as turbulent from the leading edge,
a virtual-origin effect) and at the 1/5-power correlation overestimating Cf at low Re_x, rather than at
the app's settings. This was not investigated further. The call on whether the criterion should be
relaxed, restricted to higher Re_x, or the model/settings changed is Vic's.
