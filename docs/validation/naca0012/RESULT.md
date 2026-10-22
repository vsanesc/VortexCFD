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
