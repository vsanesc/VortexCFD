# NACA 0012 validation: result

Task W2, Parts D-E, 2026-10-22. Set-up: SETUP.md. Numbers: result.json (collected by
`scripts/validation/naca0012_study.py collect`), verdicts.json. References: NASA TMR SST page
(https://tmbwg.github.io/turbmodels/naca0012_val_sst.html, 897 x 257 grid, CFL3D / FUN3D / NTS; their mean is the
reference) and Ladson, NASA TM 4074 (TMR's CLCD_Ladson_expdata.dat). Incompressible simpleFoam, k-omega SST, 2D
section (D-121), wall-resolved layers (D-122), C-type domain of radius 100 chords, Re 6e6, solver on 8 ranks.

## Per level and angle

y+ is the yPlus function object's value at the first cell centre at the last iteration (area-weighted over the
airfoil); "within 2x" = the wall area with 0.5 <= y+ <= 2 (the target is 1); layer coverage = the wall area with
the full planned count, from the mesh walk; "share > 2x" = the D-109 first-cell report's wall area with a first cell
above twice the plan (A6 collapse rule: 10 %). CM is about the quarter chord, nose up positive. CD = pressure +
viscous.

| Angle | Level (surface cell) | Cells | Layers | y+ mean | y+ within 2x | Coverage | Share > 2x | Iterations | Stop | CL | CD | CD pressure | CD viscous | CM | Solver time |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | coarse (1.953 mm) | 68,331 | 21 | 0.972 | 89.8 % | 98.0 % | 1.1 % | 1128 | criteria met | 1.0407 | 0.015643 | 0.010239 | 0.005404 | 0.01119 | 48 s |
| 10 | medium (1.381 mm) | 119,064 | 20 | 0.995 | 90.7 % | 98.6 % | 0.9 % | 1324 | criteria met | 1.0346 | 0.015592 | 0.010127 | 0.005466 | 0.01237 | 130 s |
| 10 | fine (0.977 mm) | 210,526 | 18 | 1.008 | 91.2 % | 99.1 % | 0.6 % | 1540 | criteria met | 1.0474 | 0.015469 | 0.009959 | 0.005510 | 0.00971 | 343 s |
| 15 | fine (0.977 mm) | 285,677 | 18 | 0.871 | 74.0 % | 99.2 % | 0.5 % | 8000 | iteration limit | 1.5744 | 0.087941 | 0.085176 | 0.002765 | -0.1004 | 1658 s |
| 0 | fine (0.977 mm) | 126,468 | 18 | - | - | - | 0.5 % | - | not solved: checkMesh hard failure (2 incorrectly oriented face pyramids; also when meshed serially) | - | - | - | - | - | - |
| 0 | medium (1.381 mm) | 77,312 | 20 | 1.057 | 99.3 % | 98.8 % | 0.9 % | 585 | criteria met | 0.000073 | 0.008079 | 0.001900 | 0.006179 | -0.00002 | 24 s |

"Criteria met": every residual target and the Cl and Cd asymptotic criteria (SETUP.md). The 15 degree run reached
the 8000-iteration limit; its values are those the app records for it (D-119: the 500-iteration mean when the
oscillation warning applies, else the last value). Its viscous drag is half that at 10 degrees and its pressure drag
eight times larger: the flow is separated over much of the upper surface, unlike the TMR SST solutions.

No level had collapsed layers (share > 2x at most 1.1 %), so A6's collapse rule excluded nothing. The fine 0 degree
mesh is the only hard checkMesh failure; per the task's rule the set-up was changed (the medium level, already valid
at 10 degrees), not the quality limits.

## Grid convergence at 10 degrees (Celik GCI, the app's mesh study)

Actual cell-size ratios (h = (A / N)^(1/2), D-121): 1.32 and 1.33 (the planned sqrt(2) is diluted by the layer and
near-wall cells, as D-066 noted in 3D).

| Quantity | Coarse | Medium | Fine | Result |
|---|---|---|---|---|
| CL | 1.0407 | 1.0346 | 1.0474 | oscillatory: no GCI; spread 1.2 % |
| CD | 0.015643 | 0.015592 | 0.015469 | "divergent" (the changes grow, -0.3 % then -0.8 %): no GCI; spread 1.1 % |
| CD viscous | 0.005404 | 0.005466 | 0.005510 | monotonic, p = 1.24, extrapolated 0.005614, GCI fine 2.4 %, asymptotic ratio 1.008 |
| CD pressure | 0.010239 | 0.010127 | 0.009959 | "divergent": no GCI |
| CM | 0.01119 | 0.01237 | 0.00971 | oscillatory: no GCI |

The three levels agree within 1.2 % in CL and CD, far less than CD's 24 % distance from the reference: the CD error
is not a grid error.

## Comparison and verdicts (owner rule A6)

| Angle | CL | TMR SST CL (mean) | CL error | Ladson CL (nearest angle) | CD | TMR SST CD (mean) | CD error | Verdict |
|---|---|---|---|---|---|---|---|---|
| 0 | 0.000073 (medium) | about 0 | 0.007 % of the 10 deg CL | -0.0126 / -0.0120 / -0.0115 (80 / 120 / 180 grit, -0.05 to -0.01 deg) | 0.008079 | 0.008087 | -0.1 % | **PASS** |
| 10 | 1.0474 (fine) | 1.0794 | -3.0 % | 1.0707 / 1.0775 / 1.0809 (at 10.12 / 10.10 / 10.18 deg) | 0.015469 | 0.012467 | +24.1 % | **FAIL** (CD beyond 20 %) |
| 15 | 1.5744 (fine) | 1.5092 | +4.3 % | 1.5129 / 1.5280 / 1.5169 (at 15.26 / 15.27 / 15.24 deg) | 0.087941 | 0.022270 | +295 % | **FAIL** (CD; the run did not converge and the flow separated) |

- 0 degrees: PASS. Drag and its split (76 % viscous) match the TMR codes within 0.1 %; this is the zero-lift
  baseline and checks the wall-resolved mesh, y+ and skin friction.
- 10 degrees: FAIL on CD; CL alone would pass (-2.97 %, the edge of the 3 % band). Ladson's CL at 10.1-10.2 deg is
  1.071-1.081, 1-3 % above ours. The CD excess (+0.0030) is almost all pressure drag and does not change with the
  grid (1.1 % over a 2:1 range of cell size) or with the domain (a 300-chord domain on the coarse level: CL 1.0391,
  CD 0.015732 against 1.0407, 0.015643 at 100 chords). Lift is 3 % low and drag high together, as if the
  effective incidence or the suction peak were wrong; candidates (not established): the first-order upwind
  convection of k and omega (D-022; a second-order run of the coarse level diverged at iteration 201 from the
  uniform start, so it gave no answer), the wall-function conditions used at y+ 1 instead of k = 0 and the near-wall
  omega of the TMR SST definition, and OpenFOAM's SST against SSTm. The expected compressibility effect (Prandtl-
  Glauert, about +1.1 % on CL at M 0.15; SETUP.md) explains a third of the CL gap and nothing of the drag.
- 15 degrees: FAIL. The run did not meet the stopping criteria in 8000 iterations, and the solution is separated
  (CD 0.088, a quarter of it viscous at most); CL is 4.3 % above TMR and 3-4 % above Ladson. This is not the
  attached flow the TMR SST codes compute at 15 degrees.

Total machine time of Parts A-D: about 65 min (sphere check 4, slab study 6, 2D checks 5, benchmark 3, study 10,
15 deg 30, 0 deg 2, diagnostics 3; all at nice 15), within A7's 3 h. No OpenFOAM process is left running.

## Conclusion

The angle-of-attack method (D-120), the 2D mode (D-121) and the wall-resolved layers (D-122) work: the meshes keep
98-99 % of their layers with y+ about 1 at every angle and level, and the zero-lift drag matches TMR to 0.1 %. The
lifting cases fail A6 on drag (+24 % at 10 degrees, grid- and domain-independent) and the 15 degree case separates.
The cause lies in the solver set-up (turbulence numerics or wall conditions), not in the geometry, the mesh or the
domain; it needs the owner's review (QUESTIONS 190) before a second round.

# Round 2 (task w2-naca-r2, 2026-10-22)

Owner review of round 1: D-120, D-121 (1 mm span) and D-122 accepted; QUESTIONS 187 (D-123), 189, 190 and 191 handled
here. Diagnostic runs in run/validation/naca0012/r2/ and alpha_10_base_1.41421_* (git-ignored); driver
`scripts/validation/naca0012_study.py diag | inspect | angle --buffer --mesh-only`. All at nice 15, solver on 8 ranks.

## Diagnosis at 10 degrees (QUESTIONS 190)

Level: round 1's medium (base 1.414 m, surface cell 1.381 mm, 20 layers; round 1's three levels agree within
1.2 %). One change at a time from round 1's set-up. CL / CD errors against the TMR SST mean (1.0794 / 0.012467).
Cf is signed along the body x axis (negative: reversed flow), upper surface; CFL3D SST (TMR's n0012cf / n0012cp
files, 897 x 257): Cf 9.62e-4 at x/c 0.9, 2.63e-4 at 0.99; Cp 0.165 at 0.99.

| Run | Cells | Iterations, stop | CL (err) | CD (err) | CD pressure | CD viscous | Cf 0.9 | Cf 0.99 | Cp 0.99 | Reversed flow |
|---|---|---|---|---|---|---|---|---|---|---|
| Round 1 medium | 119,064 | 1324, criteria met | 1.0346 (-4.2 %) | 0.015592 (+25.1 %) | 0.010127 | 0.005466 | 5.86e-4 | 1.44e-4 | 0.124 | none |
| B1: TMR inflow k, omega | 119,064 | 1315, criteria met | 1.0346 (-4.2 %) | 0.015592 (+25.1 %) | 0.010126 | 0.005465 | 5.85e-4 | 1.44e-4 | 0.124 | none |
| B2: k, omega second order (restart of round 1) | 119,064 | 1995 (671 after the restart), criteria met | 1.0491 (-2.8 %) | 0.015709 (+26.0 %) | 0.009991 | 0.005718 | 7.04e-4 | 1.60e-4 | 0.145 | none |
| B6: staircase buffer 12 cells | 162,854 | 1556, criteria met | 1.0359 (-4.0 %) | 0.012120 (-2.8 %) | 0.006670 | 0.005451 | 6.01e-4 | 1.43e-4 | 0.136 | none |
| B6: staircase buffer 24 cells | 246,330 | 1436, criteria met | 1.0344 (-4.2 %) | 0.011904 (-4.5 %) | 0.006461 | 0.005443 | 5.84e-4 | 1.32e-4 | 0.136 | none |
| B4: buffer 12, domain 300 chords | 307,656 | 1535, criteria met | 1.0393 (-3.7 %) | 0.011919 (-4.4 %) | 0.006439 | 0.005480 | 6.53e-4 | 1.89e-4 | 0.137 | none |
| B5: buffer 12 + k, omega second order (restart of B6) | 162,854 | 2326 (770 after the restart), criteria met | 1.0541 (-2.3 %) | 0.012241 (-1.8 %) | 0.006541 | 0.005700 | 7.29e-4 | 1.58e-4 | 0.156 | none |

(The round 1 medium row is round 1's own run; its error against the fine level's CL quoted in round 1 differs.)

- B1, freestream turbulence. TMR (CFL3D's file header, also the FUN3D input): k / a^2 = 9e-9 and
  omega mu / (rho a^2) = 1e-6 at M 0.15. With U = 90 m/s (a = U / 0.15 = 600 m/s) and nu = 1.5e-5: k = 3.24e-3 m2/s2,
  omega = 24,000 1/s, i.e. Tu = (2k/3)^(1/2) / U = 0.0516 % and nut / nu = 0.009. Round 1 used Tu 0.052 % and 0.009:
  k 3.285e-3 (+1.4 %), omega 24,336 (+1.4 %). Run with the TMR values: no change to 4-5 digits. Decay (cell
  values on z = 0 ahead of the quarter chord): nut / nu 0.009 at the inlet, 0.0084 at 99 chords, 0.0058 at 50,
  0.0055 at 10 and 2, 0.0057 at 1 chord, the same in both runs (k and omega decay together; the decay of nut is
  -38 %). With second-order k and omega (B2, B5) the far-field value falls further (0.0008 at 50 chords, 0.003-0.005
  near the airfoil), always negligible against the boundary layer's nut. Freestream turbulence is not the cause.
- B2, second-order turbulence convection: `bounded Gauss linearUpwind grad(k)` / `grad(omega)` with
  `cellLimited Gauss linear 1` gradients, from round 1's converged first-order solution. CL +1.4 %, upper-surface
  Cf +15-20 % (toward CFL3D), viscous drag +4.6 %, pressure drag -1.3 %: total CD +0.8 %. Helps CL, not the drag.
- B3, the SST variant (no run). v2606's kOmegaSST (src/TurbulenceModels/turbulenceModels/Base/kOmegaSST/
  kOmegaSSTBase.C) is the SST-2003 form (Menter, Kuntz and Langtry): nut = a1 k / max(a1 omega, b1 F2 S) with the
  strain rate S = (2 S:S)^(1/2) (F3 off); k production min(nut (grad U : dev(2 symm(grad U))), c1 betaStar k omega)
  with c1 = 10; omega production gamma min(G / nu, (c1 / a1) betaStar omega max(a1 omega, b1 F2 S)), i.e. the limiter
  in both equations; F1's CD_komega floor 1e-10; gamma1 = 5/9, gamma2 = 0.44, beta1 0.075, beta2 0.0828, betaStar 0.09,
  sigma_k 0.85 / 1, sigma_omega 0.5 / 0.856, a1 0.31, b1 1. TMR's SSTm (the NACA 0012 SST page's label; "SST, SSTm,
  SST-V and SST-Vm give very close results for this case"): Menter 1994, nut with the vorticity Omega, P = mut S^2,
  limiter 20 betaStar rho omega k in the k equation only, gamma from the formula (0.5532, 0.4403), floor 1e-20.
  Differences: S against Omega in the nut limiter (equal in a thin attached boundary layer), the limiter value and
  equation (acts only where P exceeds 10 betaStar k omega: the stagnation region), gamma (0.4 %). The only
  supported options are coefficient overrides and decayControl (SST-sust, a different variant); none gives SSTm's
  Omega-based nut or its k-only limiter, so nothing matches TMR better: no run.
- B4, boundary conditions written for this case (every boundary):

  | Patch | U | p | k | omega | nut |
  |---|---|---|---|---|---|
  | inlet (front half circle, R = 100 chords) | fixedValue (90 0 0) | zeroGradient | fixedValue | fixedValue | calculated |
  | outlet (100 chords behind) | inletOutlet (0) | fixedValue 0 | inletOutlet | inletOutlet | calculated |
  | farfield (flat top and bottom, z = +-100 chords) | slip | slip | slip | slip | calculated |
  | frontAndBack | empty | empty | empty | empty | empty |
  | naca0012 | noSlip | zeroGradient | kqRWallFunction | omegaWallFunction | nutUSpaldingWallFunction |

  TMR: a characteristic (Riemann) far field "almost 500 chords away", CFL3D with the point-vortex correction for
  the lifting cases. The mismatch is the far-field model (a Dirichlet velocity without the vortex's induced flow at
  100 chords against a vortex-corrected far field at 500), a known effect of order c / R. Run at 300 chords (with
  the buffer, since round 1's 300-chord check had 4-16 m cells there and could not carry the circulation): CL
  +0.3 %, CD -1.7 % against 100 chords. Small, and it moves CD away from TMR: not adopted.
- B6 (not in the task's list; found while reading B1-B2): the near-field resolution. In 2D the staircase grows each
  level's box by 3 cells of that level, so at a distance d from the airfoil's box the cell is about d / 6 on every
  level of a study (measured on round 1's coarse / medium / fine: 44-63 mm at 0.3 chord above, 177-250 mm one chord
  ahead, 250 mm two chords down the wake, the same on all three; 97 % of the cells inside the airfoil's box). The
  study refined the boundary layer, not the field around a lifting airfoil (pressure field decaying as 1 / r, the
  wake): its 1.2 % spread did not test it. A 12-cell buffer removes 97 % of what a 24-cell one removes: CD +25 % ->
  -2.8 %, all of it pressure drag (0.010127 -> 0.006670); CL unchanged.
- B5, the changes that helped combined (buffer 12 and second-order k, omega; not the 300-chord domain): CL 1.0541
  (-2.3 %), CD 0.012241 (-1.8 %): PASS at 10 degrees on the medium level.

Cause: the 2D staircase's 3-cell buffer (D-121) left the near field of the lifting airfoil about ten times coarser
than a body-fitted grid, independently of the study level; numerical dissipation there produced the extra pressure
drag (+0.0035 of the +0.0031 excess). The remaining CL deficit is first-order k / omega convection (+1.4 % when
second order), the incompressible solver (Prandtl-Glauert +1.1 % at M 0.15, SETUP.md) and the 100-chord far field
(+0.3 % at 300 chords). Proposed app default for the wall-resolved 2D mode only: D-124 (12 cells). Machine time of
the diagnosis: about 21 min (B1 1.4, B2 0.8, B6 3.6 + 5.7, B4 6.9, B5 1.4, inspections 0.3, Part C remeshes 1.6).

## Round 2 runs (Part D)

Set-up: round 1's (SETUP.md) on the fine level (base 1 m, surface cell 0.977 mm, 18 layers of 8.91 um at 1.2) with
the round 2 app defaults for wall-resolved 2D sections, the 12-cell staircase buffer (D-124) and the 10-edge
medial-axis walk (D-125), then the change that helped CL: each angle first run first order from the free stream with
the app's criteria, then restarted with second-order k and omega (bounded Gauss linearUpwind, cellLimited
gradients) until the criteria are met again (at least 500 more iterations). 15 degrees: the mean-stable criterion
(D-118, W 500, 0.5 %) on Cl and Cd, both, from iteration 1000, limit 12,000 (first order) and 4,000 more (restart);
its values are the 500-iteration means (D-119), with the amplitude (max - min) / mean over that window. The 0 deg
mesh is Part C's (checkMesh OK). Numbers: result_round2.json (`naca0012_study.py collect-r2`).

| Angle | Cells | y+ mean | y+ within 2x | Coverage | Share > 2x | First order: iterations, stop, CL, CD | Second order: iterations, stop | CL | CD | CD pressure | CD viscous | CM | Solver time (both) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 179,784 | 1.057 | 99.5 % | 99.2 % | 0.5 % | 834, criteria met, -0.00003, 0.007463 | 1336, criteria met | -0.000037 | 0.007563 | 0.001277 | 0.006286 | 0.00001 | 88 + 58 s |
| 10 | 268,914 | 1.051 | 93.3 % | 99.1 % | 0.6 % | 1903, criteria met, 1.0424, 0.012162 | 2686, criteria met | 1.0642 | 0.012186 | 0.006430 | 0.005757 | 0.00848 | 357 + 150 s |
| 15 | 345,687 | 0.915 | 82.3 % | 99.2 % | 0.5 % | 2857, mean stable, 1.4155 (amplitude 14.5 %), 0.025666 (96 %) | 4500, mean stable | 1.4894 (0.8 %) | 0.022558 (7.8 %) | 0.017574 | 0.004983 | 0.01934 | 756 + 462 s |

Upper-surface trailing-edge region against CFL3D SST (Cf at x/c 0.9 / 0.99, Cp at 0.99): 10 deg 9.28e-4 / 2.62e-4 /
0.167 (CFL3D 9.62e-4 / 2.63e-4 / 0.165); 15 deg 1.95e-4 / 1.55e-5 / 0.054 (CFL3D 2.01e-4 / -5.3e-5 / 0.054, with
TMR's note that its values very near the trailing edge carry a large numerical error). No reversed flow at any
angle; round 1's 15 degree run was separated over much of the upper surface. The first-order 15 degree run
oscillates strongly (CD 96 % over 500 iterations) about a mean of 1.4155 / 0.025666 (CD +15 %): first-order k and
omega convection is what made round 1's 15 degrees unsteady together with the coarse near field.

No level collapsed (share > 2x at most 0.6 %, A6). Grid: the fine level's boundary layer was within 1.2 % of the
medium in round 1, and at 10 degrees the medium (B5: 1.0541, 0.012241) and the fine (1.0642, 0.012186) agree within
1.0 % / 0.4 % with the round 2 set-up. The near field is set by the buffer, not the level (D-124): 12 against 24
cells changed CD by 1.8 % and CL by 0.15 % (first order, medium).

## Round 2 comparison and verdicts (owner rule A6)

| Angle | CL | TMR SST CL | CL error | Ladson CL (nearest angle) | CD | TMR SST CD | CD error | Verdict |
|---|---|---|---|---|---|---|---|---|
| 0 | -0.000037 | about 0 | 0.003 % of the 10 deg CL | -0.0126 / -0.0120 / -0.0115 | 0.007563 | 0.008087 | -6.5 % | **PASS** |
| 10 | 1.0642 | 1.0794 | -1.4 % | 1.0707 / 1.0775 / 1.0809 (10.12 / 10.10 / 10.18 deg) | 0.012186 | 0.012467 | -2.3 % | **PASS** |
| 15 | 1.4894 | 1.5092 | -1.3 % | 1.5129 / 1.5280 / 1.5169 (15.26 / 15.27 / 15.24 deg) | 0.022558 | 0.022270 | +1.3 % | **PASS** (500-iteration means; CD oscillates by 7.8 %) |

Verdict: PASS at 0, 10 and 15 degrees with the round 2 set-up. Notes:
- 0 degrees moved from -0.1 % (round 1) to -6.5 %: round 1's agreement was partly a cancellation, since the coarse
  near field also added pressure drag at zero lift (CD pressure 0.00190 then, 0.00128 now). The remaining -6.5 %
  is within A6's 10 % but larger than at 10 and 15 degrees; not diagnosed (candidates: the incompressible solver
  at M 0.15, the wall conditions at y+ 1, the 100-chord far field).
- The second-order k / omega convection is a restart in the validation driver; the app writes first-order upwind
  for k and omega (D-022) and has no two-stage run (QUESTIONS).
- 15 degrees is not outside steady RANS with this set-up: the restart settles to a mean with CL steady to 0.8 % and
  CD oscillating by 7.8 % about it, and the attached trailing-edge flow of the TMR codes.
- Lift is 1.3-1.4 % below TMR at 10 and 15 degrees; the Prandtl-Glauert estimate of the M 0.15 effect is +1.1 %
  (SETUP.md).

Machine time of round 2: about 62 min at nice 15 (diagnosis and Part C remeshes 21.5, benchmark check 3.9, Part D
37.1), within the task's 2 h. No OpenFOAM process is left running.

Benchmark check (the defaults of the public cases must not change): `python -m vortexcfd.bench --no-solve --compare
benchmarks/baseline.json` (mesh only, serial, at commit 9c63edb plus the validation driver; result
run/validation/naca0012/r2/bench/20261022T100159Z_9c63edb-dirty.json, git-ignored): every mesh metric identical on
the three public cases (sphere 233,534 cells, max non-orthogonality 46.46, coverage 99.59 %; half wing 300,025,
64.91, 94.37 %, trailing edge 38.36 %; Ahmed body 231,606, 64.28, 96.55 %, slant edges 56.01 %; fidelity unchanged;
0 hard failures): "no regressions".

# Round 3 (app pipeline, task w2-naca-r2, 2026-10-22)

Owner review of round 2: D-123 to D-125 accepted; the round 2 PASS came from the validation driver, and W2 closes
only when the app reproduces it. Round 3 runs the case as a user would (`naca0012_case.build_app_project`,
`naca0012_study.py app-study | app-angle`): the "2D airfoil" preset with only the TMR inputs (the airfoil, U 90 m/s
and nu 1.5e-5 for Re 6e6, the angle, Tu 0.052 % and nut / nu 0.009, chord 1 m and the quarter chord as reference,
the 100-chord C-type domain) and the user's solver and study settings (round 1's stopping criteria, limit 8000;
at 15 deg the mean-stable criterion on Cl and Cd and limit 12,000; 8 cores; the study with the preset's mesh as its
medium level, see below). Everything else is the app's: the surface refined to the wall-resolved limit (D-122,
automatic for y+ 1, D-123), the 12-cell staircase (D-124), the medial-axis walk (D-125), the two turbulence stages
(D-126: first-order k, omega to the criteria, then second order to the criteria again) and the study levels'
refinement of the whole domain (D-127). No driver override.

The study's current settings are its medium level (Mesh Study "current as" medium): the preset's surface cell is
1.307 mm (h / t1 = 147), so as the fine level the coarse one would be 2.61 mm (h / t1 = 293), beyond D-122's tested
limit of 220; as the medium level the three levels are 1.848 / 1.307 / 0.924 mm (h / t1 207 / 147 / 104).

## Mesh study at 10 degrees (through the app)

| Level | Surface cell | Cells | Layers | Share > 2x | Switch (iteration) | Iterations, stop | Solver time | CL | CD | CD pressure | CD viscous |
|---|---|---|---|---|---|---|---|---|---|---|---|
| coarse | 1.848 mm | 96,322 | 21 | 1.2 % | 1323 | 1973, criteria met | stage 2 only recorded: 34 s | 1.0534 | 0.012614 | 0.006933 | 0.005681 |
| medium (the preset) | 1.307 mm | 176,110 | 19 | 0.6 % | 1577 | 2363, criteria met | stage 2 only: 89 s | 1.0602 | 0.012155 | 0.006477 | 0.005678 |
| fine | 0.924 mm | 329,801 | 17 | 0.3 % | 1828 | 2701, criteria met | stage 2 only: 221 s | 1.0656 | 0.011991 | 0.006259 | 0.005732 |

(The study's solver times are those of stage 2 only: the result's duration was the last stage's; fixed after
the study, the 0 and 15 deg runs below include both stages.)

GCI (Celik, h = (A / N)^(1/2), D-121; h = 0.610 / 0.451 / 0.329 m, ratios 1.35 / 1.37):

| Quantity | Convergence | Order p | Extrapolated | GCI fine | Asymptotic ratio |
|---|---|---|---|---|---|
| CL | monotonic | 0.90 | 1.0822 (TMR 1.0794, +0.26 %) | 1.9 % | 1.005 |
| CD | monotonic | 3.49 | 0.011908 (TMR 0.012467, -4.5 %) | 0.86 % | 0.987 |
| CD pressure | monotonic | 2.53 | 0.006078 | 3.6 % | 0.966 |
| CD viscous | oscillatory (0.005681 / 0.005678 / 0.005732) | - | - | - | - |
| CM | monotonic | 0.95 | 0.00562 | 40 % | 0.90 |

Round 1's study gave CL and CD oscillatory or divergent within a 1.2 % spread; with D-124 and D-127 both converge
monotonically in the asymptotic range. Cell size at fixed points (median within 0.1 chord, coarse / medium /
fine): one chord above the quarter chord 59.0 / 41.9 / 29.6 mm (ratio 1.41, 1.41); one chord ahead of the leading
edge 71.3 / 41.9 / 29.6 mm (1.70, 1.41); two chords behind the trailing edge 236 / 167 / 59 mm (1.41, 2.83). The
planned sizes (the dictionaries) scale by 1.414 at all three points (tests/test_wall_resolved.py); the measured
exceptions lie within a few cells of a staircase box edge (one chord ahead is 16 mm outside the level-5 box), where
snappyHexMesh places the transition on each level's own cells (QUESTIONS). Round 1's meshes had no cell centre within
0.1 chord of most of these points (cells of 0.18-0.7 m).

Level used for 0 and 15 degrees: the medium, the preset's own mesh. The study is in the asymptotic range for CL
and CD (ratios 1.005, 0.987), the medium level is within 0.5 % (CL) and 1.4 % (CD) of the fine one (2.0 % and 2.1 %
from the extrapolated values), and it is the mesh a user of the preset gets.

## Per angle (through the app, medium level)

| Angle | Cells | y+ mean | y+ within 2x | Coverage | Share > 2x | Switch | Iterations, stop | Solver time | CL | CD | CD pressure | CD viscous |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 126,688 | 1.050 | 99.8 % | 98.9 % | 0.6 % | 589 | 1259, criteria met | 82 s | -0.0000022 | 0.007527 | 0.001283 | 0.006244 |
| 10 (study medium) | 176,110 | - | - | - | 0.6 % | 1577 | 2363, criteria met | see above | 1.0602 | 0.012155 | 0.006477 | 0.005678 |
| 15 | 218,711 | 0.901 | 80.4 % | 98.8 % | 0.7 % | 2918 | 4402, mean stable | 625 s | 1.4752 (amplitude 0.17 %) | 0.023147 (0.76 %) | 0.018303 | 0.004844 |

15 degrees: 500-iteration means (D-119); the run is close to steady after the switch (round 2's driver run
oscillated by 7.8 % in CD). Upper-surface Cf against CFL3D at x/c 0.9 / 0.95 / 0.99: 1.34e-4 / 3.7e-5 / -7.9e-6
(CFL3D 2.01e-4 / 7.7e-5 / -5.3e-5): a small reversed-flow region from x/c 0.972, as in CFL3D's solution near the
trailing edge; Cp at 0.99 0.036 (0.054). 0 degrees: Cf 1.85e-3 at x/c 0.9, Cp 0.196 at 0.99.

## Round 3 comparison and verdict (owner rule A6)

| Angle | CL | CL error | CD | CD error | Round 2 (driver, fine): CL / CD error | Verdict |
|---|---|---|---|---|---|---|
| 0 | -0.0000022 | 0.0002 % of the 10 deg CL | 0.007527 | -6.9 % | about 0 / -6.5 % | **PASS** |
| 10 | 1.0602 | -1.8 % | 0.012155 | -2.5 % | -1.4 % / -2.3 % | **PASS** |
| 15 | 1.4752 | -2.3 % | 0.023147 | +3.9 % | -1.3 % / +1.3 % | **PASS** |

Verdict: PASS at 0, 10 and 15 degrees through the app pipeline, within 1 % (CL) and 2.6 % (CD) of round 2's driver
result; the differences are mostly the level (the preset's 1.307 mm against the driver's 0.977 mm; at 10 degrees the
app's fine level, 0.924 mm, gives CL -1.3 % and CD -3.8 %). No level collapsed (share > 2x at most 1.2 %). The
0 degree drag is -6.9 %: inside PASS; round 1's -0.1 % was a cancellation and the likely cause of the remaining gap
is the SST-2003 (v2606) against SSTm (TMR) difference, not established (owner review of round 2, QUESTIONS 194).

Machine time of round 3: about 42 min at nice 15 (the two-stage slow test 2.5, the benchmark check 3.0, the study
21.9, 0 deg 2.1, 15 deg 11.8, dictionary dumps about 1). No OpenFOAM process is left running.
