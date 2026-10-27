# Square cylinder at Re 22,000, 2D URANS: set-up

Task 1.1-transient, Part 2, Part B (3a). Written before the runs; the pass rule below is not changed after them.

## What it checks

Turbulent transient flow (D-181, k-omega SST URANS) with the Part 2 defaults of a turbulent project: PIMPLE with
residual control at Co 2 (D-185), the start-up perturbation (D-187) and the detected sampling start (D-186), on the
case the vault note "1.1 URANS y DES" recommends for URANS (its case 1.1-c): the square cylinder of ERCOFTAC UFR 2-02.
Set up and run through the app's workflow layer: the "2D airfoil" preset (2D mode, D-121), the square imported as a
2D section, Generate Mesh and Run Solver (scripts/validation/square_study.py; tests/validation/square_case.py).

## Case

| Item | Value |
|---|---|
| Geometry | square of side D = 1 m, sharp corners, a closed polygon imported as a Selig section |
| Flow | U = 1 m/s, nu = 1/22,000 m²/s: Re = U D / nu = 22,000; k-omega SST, transient; inlet turbulence 2 % (the experiment's), viscosity ratio 10 (the app's default) |
| Reference values | l_ref = D, A_ref = D x span (2D); t_c = D / U = 1 s |
| Domain | the preset's C-type far field, 20 D ahead and to each side; wake 30 D; blockage 1/40 = 2.5 % (the experiment's channel: 7.1 %) |
| Walls | the app's default layer sizing (target y+ 50 at the first cell centre, wall functions) |

## Mesh

Two levels by the app's mesher, every size scaled by the background cell (ratio sqrt(2)): 1.414 m and 1 m
(coarse, medium); surface cell base / 128; a wake box from 0.5 D ahead of the front face to 14.5 D behind it, 5 D
high, at base / 16. The coarse level meshed in a trial: 27,234 cells, 5 prism layers on the square (100 %
extruded).

## Run

The app's defaults of a transient turbulent project: PIMPLE (at most 10 outer correctors, residual control 1e-4)
at a largest Courant number of 2; the start-up perturbation (the inflow swinging by 10 degrees at 0.2 U / D for
10 t_c); the sampling start detected over windows of 20 t_c (detection tolerance 5 %); end time 200 t_c. 4 cores,
nice 15. A PISO run (Co 1) of the coarse level compares the two couplings on a mesh with wall layers.

Amendment (after the first minutes of the coarse run, before any result; the pass rule is unchanged): the medium
level runs to 150 t_c instead of 200. The wall layers set the time step (about 760 steps per t_c on the coarse
level at Co 2), so 200 t_c of the medium level would take about 7 hours of the 14 of Part B; 150 t_c still leaves
more than 10 shedding periods after a start-up detected near 60 t_c. The PISO comparison runs only if machine time
is left.

## References

ERCOFTAC Knowledge Base Wiki, UFR 2-02 "Flow past a square cylinder"
(https://kbwiki.ercoftac.org/w/index.php/UFR_2-02_Test_Case, opened 2026-10-27), on the experiments of Lyn, Einav,
Rodi and Park (1995, J. Fluid Mech. 304, 285-319): Re = UD/nu = 22,000, a 40 mm cylinder, blockage 7.1 %, approach
turbulence about 2 %; "St of 0.133 ± 0.004"; "CD ≈ 2.1", not measured but inferred from the velocity distribution
in the wake. The page recommends the inflow 5 to 10 D upstream.

## Pass rule

The vault note's rule for this case (1.1-c), adopted unchanged:

| Quantity | Reference | PASS within |
|---|---|---|
| St (lift spectrum) | 0.133 | 10 % |
| mean Cd | 2.1 | 15 % |

The case PASSES when the medium level passes both. If St passes and Cd fails, the case is a FAIL documented as a
limitation of 2D URANS (the note expects URANS to under-predict Cd). A run whose sampling window holds fewer than
3 shedding cycles does not count.
