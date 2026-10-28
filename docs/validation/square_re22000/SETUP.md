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

## Start-up perturbation used (declared, D-198)

Every run of this validation (the coarse and medium levels, the PISO timing and window runs, and measurement C)
started with the **inflow swing**: the inflow direction swinging by ±10° in the x-z plane at 0.2 U / D for the first
10 t_c, then along +x (D-187; the app's default when these runs were made). The initial-field perturbation was not
used. Since D-198 both start-up perturbations are off by default and must be declared; the driver
(tests/validation/square_case.py) declares the swing so that these runs are reproduced. The runs were not repeated.

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

## Diagnostics of measurement C (owner's addendum)

Written and committed before any of these runs or samples; the rules are not changed after them. One solver job at
a time, at most 6 MPI processes, nice 15. Driver: scripts/validation/square_diagnostics.py. The lift histories
(Cl against t, offscreen PNG) go to ~/vortexcfd-research/1.1-urans-diagnostics/ (outside the repository), for C,
the a and c runs and PIMPLE Co 2. "Lift range" below is max(Cl) − min(Cl) over a 10 t_c interval.

### a. Restart from PIMPLE Co 2 at the sampling switch, continued at PIMPLE Co 1

The PIMPLE Co 2 coarse run's fields at t = 95.81674986 t_c (the time its sampling switch wrote, with the old-time
fields the backward scheme needs; reconstructed from its processor folders) are copied with its mesh into a new case
and continued to 150 t_c with the same settings except a largest Courant number of 1 (PIMPLE, at most 10 outer
correctors, residual control 1e-4), 6 processes. The question: does the developed shedding decay at Co 1 (Co 1 has
only the nearly steady state) or persist (two states; the start-up picks one)?

Rule: the shedding **persists** if the lift range is at least 1.0 in each of [130, 140] and [140, 150] t_c; it
**decays** if the lift range is at most 0.2 in each of them (C's level from 20 t_c on was 0.02-0.23); anything else
is **undecided** (still evolving at 150 t_c) and is reported as such. Reading fixed in advance: persists -> at Co 1
the two states coexist and the start-up selects one; decays -> at PIMPLE Co 1 only the nearly steady state is
sustained on this mesh. St, mean Cd and RMS Cl over 96-150 are reported beside C and PIMPLE Co 2.

### b. Eddy viscosity and inflow turbulence (no solver run)

From the written fields (instantaneous: C at 150 t_c, PISO Co 1 at 150, PIMPLE Co 2 at 95.8 and 200), at the cell
nearest each point on the centre line z = 0 (the square spans x 0 to 1, z -0.5 to 0.5): upstream x = -10, -3, -1;
the front face x = -0.05; the near wake x = 1.5, 2, 3 (x in D). Reported: nut/nu, k and the modelled turbulence
intensity I = sqrt(2k/3) / U. The inlet values (k and omega of 0/, from the inlet intensity 2 % and the viscosity
ratio 10) and their analytic free-stream decay under k-omega SST's far-field terms (dk/dt = -beta* k omega,
domega/dt = -beta omega^2, beta* = 0.09, beta = 0.0828, convected at U) are compared with the sampled values.

Reference (ERCOFTAC UFR 2-02 Test Case page, https://kbwiki.ercoftac.org/w/index.php/UFR_2-02_Test_Case, opened
2026-10-28): "The approach flow was measured 3 cylinder widths upstream and had a turbulence level of about 2%";
"no information is available from the measurements on the length scale of the turbulence"; computations are
recommended an eddy-to-molecular viscosity ratio at inflow of 10 ("the value of 10 is more suitable for this case")
and a uniform inflow 5 to 10 D upstream.

Rules: (b1) the modelled approach turbulence is **consistent** with the experiment if I at x = -3 D is between 1.5 %
and 2.5 %, **lower** below 1.5 %, **higher** above 2.5 % (in every run sampled). (b2) C's near-wake eddy viscosity is
**higher** if its nut/nu exceeds both PISO Co 1's and PIMPLE Co 2's (each of its sampled times) by more than a factor
2 at at least two of the three near-wake points, **lower** if it is below both by more than a factor 2 at at least
two, otherwise **comparable**. A higher value makes eddy-viscosity damping of the shedding a candidate in C, not a
proof; the front-face values are reported only.

### c. C rerun with turbOnFinalIterOnly false (diagnostic only)

C exactly (`--set algorithm=pimple --set max_courant=1 --set perturb=true --set sampling_start=96`, end 150 t_c, 6
processes, the mesh on 6), except that system/fvSolution's PIMPLE dictionary gets `turbOnFinalIterOnly false` (v2606
pimpleControl: k and omega are then solved in every outer corrector, not only in the final one) written into the
case after the app has written it. No app code or setting changes; the entry is not kept. [NUMERICS-REVIEW]

Rule: as a, the shedding **persists** (lift range ≥ 1.0 in each of [130, 140] and [140, 150]), **decays** (≤ 0.2 in
each) or is **undecided**. Reading fixed in advance: persists while C decays -> solving the turbulence only on the
final outer corrector is implicated in C's loss of shedding, and its St and mean Cd are then compared with PIMPLE
Co 2 by C's 2 % rule; decays -> that setting is not (alone) the cause.
