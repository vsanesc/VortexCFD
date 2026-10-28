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

Amendment 2 (at 80 t_c of the coarse level and 62 t_c of the medium one, before either ended; the pass rule is
unchanged): the lift amplitude of this flow is modulated at low frequency (1.0 to 2.1 per 5 t_c), so the mean of
Cd over consecutive 20 t_c windows moves by about 1 % and their ranges by up to 25 %: the detection (0.5 % and
5 %) had not settled. If a level ends without a detected start-up, its sampling start is set by hand at 50 t_c
(40 t_c after the start-up perturbation; the shedding is developed from about 10 t_c) and the solution is continued
by 1 t_c with Continue Solver (D-189), which takes the statistics from 50 t_c over the whole force history.

## References

ERCOFTAC Knowledge Base Wiki, UFR 2-02 "Flow past a square cylinder"
(https://kbwiki.ercoftac.org/w/index.php/UFR_2-02_Test_Case, opened 2026-10-27), on the experiments of Lyn, Einav,
Rodi and Park (1995, J. Fluid Mech. 304, 285-319): Re = UD/nu = 22,000, a 40 mm cylinder, blockage 7.1 %, approach
turbulence about 2 %; "St of 0.133 ± 0.004"; "CD ≈ 2.1", not measured but inferred from the velocity distribution
in the wake. The page recommends the inflow 5 to 10 D upstream. The Evaluation page (https://kbwiki.ercoftac.org/w/index.php?title=UFR_2-02_Evaluation,
opened 2026-10-28), Table 1 "Global parameters for flow past square cylinder", row "Experiments": St 0.132, C_D
1.9-2.2, L_R/D 1.38 (C_L' not measured: "there are no experimental results available for comparison"). Added in
the Part 2 review; the references and the rule above are unchanged.

## Pass rule

The vault note's rule for this case (1.1-c), adopted unchanged:

| Quantity | Reference | PASS within |
|---|---|---|
| St (lift spectrum) | 0.133 | 10 % |
| mean Cd | 2.1 | 15 % |

The case PASSES when the medium level passes both. If St passes and Cd fails, the case is a FAIL documented as a
limitation of 2D URANS (the note expects URANS to under-predict Cd). A run whose sampling window holds fewer than
3 shedding cycles does not count.

## Time-step convergence (QUESTIONS 257; Part 2 closing brief, measurement C)

Written and committed before the run; the rule is not changed after it.

The PIMPLE Co 2 and PISO Co 1 coarse runs disagree by 8-9 % in St and mean Cd over 96-150 t_c (RESULT.md). One
more run separates the time step from the coupling: the coarse level with PIMPLE (the same outer correctors and
residual control 1e-4) at a largest Courant number of 1, with the same start-up as the two existing runs (the
inflow swing, ±10° at 0.2 U / D for 10 t_c), from the free stream, sampling start set by hand at 96 t_c, end
150 t_c, 6 MPI processes, nice 15 (`scripts/validation/square_study.py level --name coarse --end 150 --cores 6
--tag pimple_co1 --timeout-h 8 --set algorithm=pimple --set max_courant=1 --set perturb=true --set
sampling_start=96`). Only the time step differs from the PIMPLE Co 2 run, and only the coupling from the PISO Co 1
run.

Measured over the same window 96-150 t_c by scripts/validation/window_compare.py (the app's own St, mean and RMS
from the force history; also the halves 96-123 and 123-150).

**Rule.** If PIMPLE Co 1 and PIMPLE Co 2 agree within 2 % in St and in mean Cd (|Q_Co1 − Q_Co2| / |Q_Co2| ≤ 0.02
for each), PIMPLE is time-step converged there and PISO Co 1 is the outlier. Otherwise the three runs' numbers are
reported as they are, with what they show, and no conclusion on convergence is drawn. No default is changed either
way; the result and its reading go to QUESTIONS 257 for the owner.

Machine: another workload ran on the other cores: wall times are indicative only, measured with another workload
running.
