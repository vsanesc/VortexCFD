# Flat plate validation (Task 4A)

Two cases with the app's own solver builder (`foam/physics_case.py`: kOmegaSST, the BCs, the
motorBike schemes and solution settings, SIMPLEC, U 0.9, k/omega 0.7, `residualControl` 1e-5 for p, U, k
and omega as in the Solvers settings); only the mesh comes from a blockMesh test helper
(`tests/validation/flat_plate_case.py`). Run with

    .venv/bin/pytest -m validation -q -s tests/validation

(skipped by default, excluded from `scripts/ship.sh`; run it after every change to the physics or
numerics). Outputs: `case_{A,B}_residuals.csv` (initial residuals per iteration),
`case_{A,B}_cf_comparison.csv` (per face: x, Re_x, Cf, both laws, signed relative errors, y+) and
`case_a_diagnosis.json`.

**Verdict: Case B (the arbiter) is NOT MET** (mean Cf error 11.6 % against a limit of 5 %). Case A is
informative only. The y+ estimator is confirmed in both cases. The app's numerics were not tuned.

Geometry in both cases: 2D (one empty cell in y, x streamwise, z wall-normal), a slip section upstream
of the leading edge, no-slip plate from x = 0 to 2 m, top and leading section slip, outlet p = 0.

## Case A (low Re, informative)

U = 10 m/s, nu = 1.5e-5 (Re_L = 1.3e6), 230 x 100 cells, domain height 0.5 m, slip section 0.3 m, free
stream from the app's defaults (I = 1 %, nut/nu = 10: k = 0.015, omega = 100), first cell from the
estimator with target 2 at L = 2 m (7.2e-5 m, cell-centre y+ about 1). Converged in 494 iterations
(26 s). y+ at mid-plate: measured 1.003, estimator 1.050 (ratio 0.955).

| Re_x | Cf simulated | Cf 0.0592 Re^-0.2 | error | Cf 0.455/ln^2(0.06 Re) | error | max nut/nu in the BL |
|---|---|---|---|---|---|---|
| 2.97e5 (x 0.445 m) | 3.947e-3 | 4.763e-3 | **-17.1 %** | 4.750e-3 | **-16.9 %** | 18 |
| 5.97e5 (x 0.895 m) | 3.551e-3 | 4.142e-3 | **-14.3 %** | 4.138e-3 | **-14.2 %** | 34 |
| 9.97e5 (x 1.495 m) | 3.296e-3 | 3.738e-3 | **-11.8 %** | 3.761e-3 | **-12.4 %** | 54 |
| 1.30e6 (x 1.945 m) | 3.182e-3 | 3.546e-3 | **-10.3 %** | 3.587e-3 | **-11.3 %** | 68 |

(The stations are the plate faces nearest to the requested Re_x = 3e5, 6e5, 1e6, 1.3e6.) The sign of the
error is negative everywhere: the simulation is below both laws. Free stream just upstream of the
leading edge (x = -0.005 m, z = 0.375 m): k = 0.01181 against 0.015 at the inlet (decay ratio 0.787) and
omega = 80.2 against 100 (0.802).

Interpretation. The simulation is 10-17 % below both laws, the error shrinks steadily along the
plate, and the maximum eddy-viscosity ratio in the boundary layer is only 18-68 (a developed turbulent
boundary layer at these Reynolds numbers has several hundred): the boundary layer is still developing
its turbulence over this Re_x range instead of being turbulent from the leading edge, which gives a
thicker layer (a virtual origin downstream of x = 0) and so a lower Cf than a law that assumes a
turbulent start. The free-stream decay (about 20 % over the 0.3 m slip section) is modest and not the
cause. The fully turbulent laws are therefore not a fair reference below Re_x of about 1e6, which is why
this case is informative only and the arbiter is Case B. Earlier attempts (mesh 430 x 150: 13.0 % mean
error; free stream I = 5 %, or I = 0.1 % with ratio 1: 13.0-13.4 %) did not change this.

## Case B (the arbiter, TMR-like)

Modelled on the NASA Turbulence Modeling Resource 2D zero pressure gradient flat plate
(https://tmbwg.github.io/turbmodels/flatplate.html, read for this task): wall x = 0 .. 2 m, Re = 5e6 per
unit length (Re_x = 1e7 at x = 2 m), top boundary at y = L = 1 (the page states that moving it to 0.48 L
changes Cf by less than 0.2 %), Cf at x = 0.97 mentioned there. The page does not give the SST free-stream
values, the boundary conditions (a figure) or the y+ guidance, and its flow is compressible (M = 0.2),
ours incompressible. So:

- U = 75 m/s, nu = 1.5e-5 m2/s (Re_L = 1e7), domain height 1 m, slip section 0.3 m upstream.
- Free stream in Menter's recommended SST ranges: omega_inf = 5 U / L = 375 1/s and
  k_inf = 1e-6 U^2 = 5.625e-3 m2/s2 with L = 1 m, i.e. nut/nu = k / (omega nu) = **1.0**. In the app's
  terms: turbulence intensity 8.165e-4 and viscosity ratio 1.0 (k = 1.5 (U I)^2 and omega = k / (nu ratio)
  reproduce both values exactly).
- 330 x 150 cells; the plate block is graded along x (last / first cell 10), the first wall-normal cell
  from the estimator with target 2 at L = 1 m (1.06e-5 m: cell-centre y+ about 1 at x = 1 m), growth 1.059.
  checkMesh: only the aspect ratio check trips (max 2390, boundary-layer cells).
- Criterion: mean absolute error <= 5 % and max <= 8 % against White's law
  Cf = 0.455 / ln^2(0.06 Re_x) for Re_x in [1e6, 1e7]; y+ at mid-plate within 30 % of the estimator;
  budget 15 min.

### Result (attempt 1, the committed case)

| Quantity | Value |
|---|---|
| Iterations (all initial residuals < 1e-5) | 1188 |
| Wall time (simpleFoam) | 204 s |
| Cf error vs White, Re_x 1e6 .. 1e7: mean / max | **11.6 % / 14.3 %** (limit 5 % / 8 %) **not met** |
| Cf at x = 0.97 m | 2.556e-3 (White 2.873e-3, -11.0 %) |
| y+ at x = 1 m: measured / estimator | 0.942 / 1.000 (ratio 0.942, limit 30 %) **met** |
| y+ over the plate (min .. max) | 0.90 .. 2.31 |

### Attempts (case set-up only)

| # | Variation | Iterations / time | Mean / max error | Cf at 0.97 m | y+ measured / predicted |
|---|---|---|---|---|---|
| 1 | as above (330 x 150, first cell target 2) | 1188 / 204 s | 11.6 % / 14.3 % | 2.556e-3 | 0.942 / 1.000 |
| 2 | refined 630 x 200 cells | 1784 / 889 s | 11.6 % / 14.3 % | 2.561e-3 | 0.943 / 1.000 |
| 3 | first cell at half the height (target 1: centre y+ about 0.5) | 1194 / 167 s | 9.5 % / 12.1 % | 2.617e-3 | 0.476 / 0.500 |

All values stay below White's law. The result is mesh independent (attempt 2) but moves with the height
of the first cell (attempt 3: Cf rises as the cell gets thinner, still 9.5 % low), which points at the
near-wall treatment at y+ of about 1 (the omegaWallFunction blending and nutUSpaldingWallFunction used
by the builder) rather than at resolution. I stopped here as instructed; whether the wall treatment, the
reference or the criterion should change is Vic's decision (see docs/QUESTIONS.md).
