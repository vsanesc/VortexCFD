# NACA 0012 validation: set-up

Task W2, Part C (owner decisions A5-A7). The case is built by code (tests/validation/naca0012_case.py) through the
app's workflow layer and run by scripts/validation/naca0012_study.py; the projects live in
run/validation/naca0012/ (git-ignored); the numbers go to result.json and RESULT.md.

## References (read on 2026-10-22)

- NASA Turbulence Modeling Resource (TMR), "2D NACA 0012 Airfoil Validation Case",
  https://tmbwg.github.io/turbmodels/naca0012_val.html (the TMR pages moved from turbmodels.larc.nasa.gov, which
  now redirects to nasa.gov): the geometry, M = 0.15, Re = 6 million per chord, the farfield "almost 500 chords
  away", "essentially incompressible conditions (the recommendation here is to run M = 0.15 in compressible CFD
  codes)", fully turbulent, Ladson's data.
- TMR, "NACA 0012 Validation, SST", https://tmbwg.github.io/turbmodels/naca0012_val_sst.html: the SST (SSTm) results
  of CFL3D, FUN3D and NTS on the 897 x 257 grid (the finest grid named on that page); CFL3D and FUN3D used
  "freestream turbulence intensity=0.052%" and "freestream turbulent viscosity (relative to laminar)=0.009". The
  CFL3D file (NACA0012_validation/n0012clcd_cfl3d_sst.dat) says "Lifting results have point vortex farfield
  correction on". No CM and no pressure / viscous split are given on that page: none is recorded.
- Ladson, C. L., NASA TM 4074 (1988), through TMR's NACA0012_validation/CLCD_Ladson_expdata.dat: Re 6e6, M 0.15,
  transition tripped, three grit sizes.

| alpha | CL CFL3D | CL FUN3D | CL NTS | CL mean | CD CFL3D | CD FUN3D | CD NTS | CD mean |
|---|---|---|---|---|---|---|---|---|
| 0 | approx 0 | approx 0 | approx 0 | 0 | 0.00809 | 0.00808 | 0.00809 | 0.008087 |
| 10 | 1.0778 | 1.0840 | 1.0765 | 1.0794 | 0.01236 | 0.01253 | 0.01251 | 0.012467 |
| 15 | 1.5068 | 1.5109 | 1.5100 | 1.5092 | 0.02219 | 0.02275 | 0.02187 | 0.022270 |

Ladson CL (alpha, CL) nearest to the run angles: 80 grit (-0.05, -0.0126), (10.12, 1.0707), (15.26, 1.5129); 120 grit
(-0.01, -0.0120), (10.10, 1.0775), (15.27, 1.5280); 180 grit (-0.03, -0.0115), (10.18, 1.0809), (15.24, 1.5169).
The comparison with Ladson is made at his angles' nearest run angle, not interpolated (the CL slope is about 0.11 per
degree, so his +0.1 to +0.3 degree offsets are worth +0.01 to +0.03 in CL; RESULT.md states them).

## Inputs

| Input | Value | Source |
|---|---|---|
| Geometry | TMR revised NACA 0012, y = +- 0.594689181 [0.298222773 sqrt(x) - 0.127125232 x - 0.357907906 x^2 + 0.291984971 x^3 - 0.105174606 x^4], chord 1 m, sharp trailing edge, 11.894 % thick; 401 cosine-spaced points per surface written as a Selig file and imported with File > Import Airfoil (scale 1, trailing edge "blunt": already closed) | TMR validation page; `naca0012_case.write_dat` |
| Analysis | 2D section (x-z plane), the "2D airfoil" preset (D-121) | owner A5 |
| Angle of attack | 0, 10, 15 deg: the parts rotated nose up about the quarter chord (D-120), flow +x | owner A1, A6 |
| Reynolds number | 6e6 per chord: U = 90 m/s, nu = 1.5e-5 m2/s, chord 1 m | TMR |
| Mach number | incompressible (simpleFoam); TMR's M = 0.15 is not modelled (below) | app limit |
| Turbulence | k-omega SST, fully turbulent; inlet intensity 0.052 % (I = 0.00052), nut / nu = 0.009 | TMR (CFL3D, FUN3D inputs) |
| Wall | wall-resolved: target y+ 1 at the first cell centre (D-107): first layer 8.91 um; the app's wall conditions (nutUSpaldingWallFunction, omegaWallFunction, kqRWallFunction), which at y+ about 1 give nut about 0 and the viscous-sublayer omega | owner A6; D-022 |
| Layers | "wall_resolved" layer controls (D-122): ratio 1.2, the stack one surface cell thick (coarse / medium / fine: 21 / 20 / 18 layers), layer-phase relaxed determinant 1e-5 and non-orthogonality 75 | Part B2 |
| Domain | C-type, radius 100 chords around the chord centre (200 chords across), the outlet 100 chords behind the trailing edge; inlet U = (90, 0, 0), farfield slip, outlet p = 0 | owner Part C2 (at least 100 chords) |
| Reference values | l_ref = chord = 1 m, A_ref = chord x span (automatic in 2D), CofR = quarter chord (0.25, 0, 0): CM about the quarter chord, nose up positive; forces in wind axes | D-120, D-121 |
| Numerics | the app's steady SIMPLEC set (motorBike: linearUpwindV for U, first-order upwind for k and omega, D-022); unchanged | D-022 |
| Stopping | the app's criteria (D-058), all of them: residuals p 1e-4, U, k, omega 1e-5, and Cl, Cd asymptotic over 200 iterations within 0.1 % / 0.2 %, not before iteration 500; limit 8000 iterations; a level that oscillates is recorded on its windowed mean (D-119) | owner Part D |
| Cores | solver 8 ranks; meshing automatic (3 ranks) | D-111 |

## Grid study (10 degrees)

The app's mesh study (D-066), ratio sqrt(2), the current settings as the fine level; in 2D the background budget
scales with the area (D-121) and every level grows its own wall-resolved stack from the same first layer (D-122).

| Level | Base cell | Surface cell | h / t1 | Background cells | Layers | Planned cells | Planned solver time (8 cores) |
|---|---|---|---|---|---|---|---|
| coarse | 2.000 m | 1.953 mm | 219 | 10,816 | 21 | about 80,000 | about 4 min (3,000 it.), at most 10 min (8,000) |
| medium | 1.414 m | 1.381 mm | 155 | 21,170 | 20 | about 150,000 | about 7 min, at most 18 min |
| fine | 1.000 m | 0.977 mm | 110 | 41,616 | 18 | about 280,000 | about 12 min, at most 33 min |

Planned cells: scaled from the preset's 10 deg mesh (129,553 cells with 1.31 mm surface cells, run/w2/e2e10),
dominated by the finest staircase box around the rotated airfoil (about 0.29 m2 of 1 mm cells on the fine level).
Planned times: that mesh's measured rate, 8.7e-7 s per cell and iteration on 8 ranks (792 iterations in 89 s).
Meshing about 1-3 min per level. Then 0 and 15 degrees at the level the study supports (the fine one if it is in
the asymptotic range; about 12 min each, at most 33). Total planned machine time about 1 h, at most 2 h, within the
owner's 3 h (A7) together with the 25 min used before (the sphere rotation check, the slab study and the
benchmark check).

A6: before a level is solved, its D-109 first-cell report is read; a level whose first cell is above twice the
planned one over more than 10 % of the wall is not solved and is reported inconclusive.

## Known differences from TMR and their expected size

- Compressibility: the app is incompressible; TMR recommends M = 0.15 and calls the case "essentially incompressible"
  without giving a number. Expected size (not from TMR: the Prandtl-Glauert rule, CL proportional to
  1 / sqrt(1 - M^2)): CL at M 0.15 about 1.1 % higher than incompressible, so the incompressible CL is expected about
  1 % below the TMR values, within the 3 % band but a third of it.
- Domain: 100 chords radius against TMR's about 500 chords with a point-vortex farfield correction in CFL3D. A slip /
  fixed-velocity boundary at a finite distance reduces the circulation; the TMR numerics page studies the farfield
  distance but this set-up does not reproduce it, so the effect is a risk on CL of the order of 1 %, stated in RESULT.md
  rather than estimated here.
- Turbulence convection is first-order upwind (D-022) where the TMR codes are second order: a risk on CD (excess
  diffusion of the wake and the boundary-layer edge).
- Wall conditions: the app's wall-function conditions are used at y+ about 1 (they switch to the viscous-sublayer
  values there) instead of k = 0 and the near-wall omega of the TMR SST definition.
