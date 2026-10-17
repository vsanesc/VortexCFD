# Flat plate verification (Task 4A)

Two cases with the app's own solver builder (`foam/physics_case.py`: kOmegaSST, the D-022 BCs, the
motorBike schemes and solution settings, SIMPLEC, U 0.9, k/omega 0.7, `residualControl` 1e-5 for p, U, k
and omega as in the Solvers settings); only the mesh comes from a blockMesh test helper
(`tests/validation/flat_plate_case.py`). Run with

    .venv/bin/pytest -m validation -q -s tests/validation

(about 20 min, 17 min measured: Case A plus the coarse and medium Case B grids, concurrent, dominated by the medium grid;
skipped by default and excluded from `scripts/ship.sh`; run it after every change to the physics or
numerics). It asserts that the medium grid's Cf(0.97) is within 5 % of the TMR reference, that the
error decreases from coarse to medium, that both grids reproduce the committed full study within 0.1 %,
and that the recorded verdict band holds with the committed finest grid. It writes the Case A files.

The full Case B study (three grids, Celik GCI, TMR distribution; `--k-wall` adds the k wall BC
diagnostic) is a script:

    .venv/bin/python scripts/validation/flat_plate_study.py [--k-wall]

(about 80 min measured, about 2 h with `--k-wall`; dominated by the finest grid, which needs about
7200 iterations; at most five single-core solvers run concurrently, keep the machine otherwise free). Case directories go to
run/validation/flat_plate_study/ (a finished run of an identical set-up is reused). It writes
`case_B_residuals.csv` and `case_B_cf_comparison.csv` (finest grid), `case_b_grid_study.json` / `.csv`
and the generated tables below. Run it when the numerics change, before updating the committed results.

Files: `case_{A,B}_residuals.csv` (initial residuals per iteration), `case_{A,B}_cf_comparison.csv` (per
face: x, Re_x, Cf, the TMR CFL3D distribution for B, both laws, signed relative errors, y+),
`case_a_diagnosis.json`, `case_b_grid_study.json` / `.csv`.

**Verdict: Case B (the arbiter) is PASS WITH NOTE**: the grid-extrapolated Cf(x = 0.97) is 3.3 % below
the NASA TMR incompressible SST reference (band 3-5 %). The app's turbulence model, schemes and wall BCs
were not changed. Case A is informative only. The y+ estimator is confirmed.

Note for the 3-5 % band: TMR states that in 2014 the SA, SST and Wilcox2006 implementations of standard
OpenFOAM did not match the equations on its site, and that with code modifications OpenFOAM matched the
TMR flat plate and bump results (Gomez et al., AIAA-2014-2087;
https://tmbwg.github.io/turbmodels/openfoam_issues.html). TMR does not track whether this still applies.

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

## Case B (the arbiter): NASA TMR verification

The NASA Turbulence Modeling Resource 2D zero pressure gradient flat plate
(https://tmbwg.github.io/turbmodels/flatplate.html and flatplate_sst.html, read 2026-10-17) is a
VERIFICATION case: verified codes converge to the same Cf with grid refinement. Reference data in
tests/data/tmr/ (README there). White's law is not a valid pass/fail reference for SST (at x = 0.97, White gives 2.873e-3;
the TMR SST results are 5.3 % below it incompressible and 6.7 % compressible) and is reported for
information only.

Set-up (unchanged from the first Case B): U = 75 m/s, nu = 1.5e-5 m2/s (Re = 5e6 per metre, Re_L = 1e7),
domain height 1 m, slip section 0.3 m upstream, 300 + 30 streamwise cells (plate block graded, last /
first 10). Free stream: k = 1.5e-6 U^2 = 8.4375e-3 m2/s2, omega = k / nu = 562.5 1/s = 7.5 U / L
(nut/nu = 1.0), as written in 0/k and 0/omega. (Earlier text and the case comment said k = 1e-6 U^2 and
omega = 5 U / L, Menter's recommended values; the intensity was converted with k = 1.5 (U I)^2 one time
too many. The case was not changed.) TMR's
default is k = 1.125 U^2 / Re_L, omega = 125 U / L (nut/nu = 0.009); its table on flatplate_sst.html shows
that free-stream levels in this range change Cf(0.97) by less than 0.1 %. Differences from TMR: our flow
is incompressible (TMR's compressible codes run M = 0.2; their incompressible codes give about 1 % higher
Cf), the inflow is a fixed velocity and the top boundary is slip.

**Reference**: Cf(0.970084) = **2.7214e-3**, the mean of the three TMR incompressible SST codes (FUN3D,
SC/Tetra, GHOST) each extrapolated from its three finest grids (mean of their finest-grid values 2.7165e-3).

### Wall-normal grid study

Three nested grids: same streamwise cells; each level splits every wall-normal cell of the previous one in
two (twice the cells, growth ratio sqrt(r), first cell h1 / (1 + sqrt(r))), so the wall-normal refinement
ratio is exactly 2. The first grid's first cell comes from the y+ estimator (target 2 at x = 1 m).
y+ is OpenFOAM's first-cell-centre y+ at x = 0.97; delta99 is where Ux reaches 0.99 U at x = 0.97.

<!-- BEGIN generated: grid study -->
| Grid | Wall-normal cells | First cell [m] | Expansion ratio | y+ (x 0.97) | delta99 [mm] | Cells in delta99 | Cf(0.97) | Error vs reference | Iterations / time |
|---|---|---|---|---|---|---|---|---|---|
| 1 (coarse) | 128 | 1.056e-05 | 1.0713 | 0.943 | 12.5 | 65 | 2.5561e-03 | -6.07 % | 881 / 171 s |
| 2 | 256 | 5.188e-06 | 1.0350 | 0.470 | 12.7 | 130 | 2.6239e-03 | -3.58 % | 3395 / 1320 s |
| 3 (fine) | 512 | 2.572e-06 | 1.0174 | 0.233 | 12.8 | 260 | 2.6307e-03 | -3.33 % | 7208 / 7483 s |

| Quantity | Value |
|---|---|
| Observed order p | 3.34 (monotonic convergence) |
| Extrapolated Cf(0.97) | 2.6314e-03 |
| e_a^21 / e_ext^21 | 0.256 % / 0.028 % |
| GCI_fine^21 | 0.035 % |
| Reference (TMR incompressible SST, extrapolated mean) | 2.7214e-03 |
| **Error of the extrapolated value vs the reference** | **-3.31 %: PASS WITH NOTE** |

Cf(x) on the finest grid, 0.1 < x < 1.9 (245 faces; informative):

| Against | Mean abs. error | Max abs. error |
|---|---|---|
| TMR CFL3D distribution (compressible, 545 x 385) | 1.9 % (mean signed -1.9 %) | 3.9 % |
| White 0.455 / ln^2(0.06 Re_x) | 9.1 % | 11.8 % |
<!-- END generated: grid study -->

The observed order is above the scheme's formal order: the change from grid 1 to 2 (y+ 0.94 to 0.47) is
ten times the change from 2 to 3, i.e. Cf depends on the first-cell y+ mainly between y+ 1 and 0.5 and
is essentially converged below it. The GCI covers the wall-normal error only (streamwise cells fixed; the
first Case B showed 2.556e-3 vs 2.561e-3 with 2.1 times the streamwise cells). The remaining -3.3 % is
not a discretisation error of this study.

y+ estimator (grid 1, x = 1 m): measured 0.943 against 1.000 predicted (within 30 %).

### Wall BC sensitivity (diagnostic, finest grid)

k on the plate replaced; omega (omegaWallFunction, v2606 default blending binomial with n = 2) and nut
(nutUSpaldingWallFunction) unchanged.

<!-- BEGIN generated: k wall -->
| k wall BC | Cf(0.97) | Error vs reference | Iterations |
|---|---|---|---|
| kqRWallFunction (default) | 2.630650e-03 | -3.334 % | 7208 |
| kLowReWallFunction | 2.630648e-03 | -3.334 % | 7208 |
| fixedValue 1e-10 | 2.630648e-03 | -3.334 % | 7208 |
<!-- END generated: k wall -->

At first-cell y+ 0.23 the k wall BC has no effect (differences below 1e-6 relative), so no k BC is
closer to TMR and no change is proposed. This diagnostic does not cover y+ about 1 or wall-function
meshes (y+ 30-100), where the BCs act differently; the grid study shows the y+ 1 grid 2.6 % below the
y+ 0.5 grid.

### History: the first Case B (White's law criterion, superseded)

The first Case B (330 x 150 cells, same free stream) was judged against White's law with mean <= 5 % /
max <= 8 % over Re_x 1e6-1e7 and gave 11.6 % / 14.3 % (Cf(0.97) = 2.556e-3); refined to 630 x 200 cells:
11.6 % / 14.3 % (2.561e-3); first cell halved: 9.5 % / 12.1 % (2.617e-3). The criterion was replaced by
the TMR reference (D-036) because SST itself is below White's law at these Reynolds numbers.
