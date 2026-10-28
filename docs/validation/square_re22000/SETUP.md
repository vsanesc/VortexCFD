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

## Matched inflow turbulence, default start-up (QUESTIONS 257 follow-up)

Written and committed before the run; the rule below is not changed after it. The earlier runs and their inflow
(intensity 2 % and viscosity ratio 10 at the inlet, "Case" above) stay documented as they are. This changes the
validation case's inputs only, not the app's numerics or defaults.

### What the experiment's approach flow was

ERCOFTAC Knowledge Base Wiki, UFR 2-02 Test Case (https://kbwiki.ercoftac.org/w/index.php/UFR_2-02_Test_Case, opened
again 2026-10-28):
- section "Test Case Experiments", paragraph 1: "The approach flow had a turbulence level of about 2 %."
- same section, paragraph 7: "The approach flow was measured 3 cylinder widths upstream and had a turbulence level of
  about 2%"; "In RANS calculations this was estimated by assuming a ratio of eddy viscosity to molecular viscosity in
  the range 10 to 100"; "Bosch and Rodi (1998) found that the value of 10 is more suitable for this case"; "If uniform
  inflow conditions are to be used in calculations, the inflow boundary should be placed further upstream (5 to 10
  D)."
- section "CFD Methods", paragraph 2: "a significant influence of the specification of the turbulent length scale at
  inflow on the calculation results"; "a length scale based on the assumption of a ratio of eddy to molecular
  viscosity of 10" was found "to be more realistic than the previously used value of 100"; "a location of the inflow
  boundary 4.5 D upstream of the cylinder is too close", "the boundary should be shifted further upstream to about
  10 D".

### The free-stream decay in v2606's kOmegaSST

Read in src/TurbulenceModels/turbulenceModels/Base/kOmegaSST/kOmegaSSTBase.C and .H (installed v2606): beta1 0.075,
beta2 0.0828, betaStar 0.09 (the coefficients' defaults; the validation case sets none); beta = F1 beta1 + (1 - F1)
beta2 (`blend`); the k sink betaStar omega k (`epsilonByk`), the omega sink beta omega^2; decayControl off by default
(kInf = omegaInf = 0). In a uniform free stream the production (grad U = 0), the cross-diffusion term (grad k = grad
omega = 0) and the diffusion vanish, so along the centre line, convected at U:

    domega/dt = -beta omega^2   ->  omega(t) = omega0 / (1 + beta omega0 t)
    dk/dt = -betaStar k omega   ->  k(t) = k0 (1 + beta omega0 t)^(-betaStar/beta)

with beta = beta2 where F1 = tanh(arg1^4) is about 0 (F1 8e-5 at the inlet for the values below, 0.2 at 3 D
upstream; integrating with F1(y) along the centre line changes k at 3 D upstream by 4e-6 relative: negligible).

The inlet of the coarse mesh is at x = -19.49995 D (the mesh's smallest x; the front face is at x = 0), so a parcel
takes t = (-3 - (-19.49995)) D / U = 16.49995 s (U = 1 m/s, D = 1 m) to reach 3 D upstream. nu = 1/22,000 =
4.545455e-5 m²/s. The target at x = -3 D: I = 2 %, k = 1.5 (0.02 U)^2 = 6.0000e-4 m²/s².

### The viscosity ratio 10 cannot give 2 % at 3 D upstream from this inlet

With the ratio R at the inlet (omega0 = k0 / (R nu), the app's inlet rule), k(-3 D) = k0 (1 + a k0)^(-betaStar/beta2),
a = beta2 t / (R nu). As a function of k0 it is largest at a k0 = 1 / (betaStar/beta2 - 1) = 11.5:
- R = 10: a = 0.0828 x 16.49995 / (10 x 4.545455e-5) = 3005.63; k0 = 3.8262e-3; the largest k(-3 D) is 2.4574e-4,
  I = 1.280 %: no inlet k reaches 2 %.
- R = 10 applied at 3 D upstream instead: omega(-3 D) = 6.0e-4 / (10 nu) = 1.32 1/s, and 1/omega0 = 1/1.32 - beta2 t
  = 0.7576 - 1.3662 < 0: no inlet state decays to it.
- The smallest inlet ratio that reaches 2 % at 3 D upstream is R = 24.42 (with k0 at the maximum, I0 = 7.9 %). Even
  an inlet at 10 D upstream (t = 7 s), not allowed here, would give at most 1.965 % with R = 10.

Chosen (QUESTIONS 263 asks the owner): **R = 100 at the inlet**, the upper end of the page's range "10 to 100" (the
"previously used value" in RANS for this case). With it the decay from the inlet to 3 D upstream is mild, so the
match is the least sensitive to the extra numerical decay seen in diagnostic b; R = 24.4 would need 7.9 % at the inlet
and sits exactly at the maximum, where any extra decay misses 2 %. Solving k0 (1 + a k0)^(-1.086957) = 6.0e-4 with a
= 0.0828 x 16.49995 / (100 x 4.545455e-5) = 300.563 (bisection, the smaller root): **k0 = 7.479588e-4 m²/s², I0 =
sqrt(2 k0 / 3) / U = 2.23302 %, omega0 = k0 / (100 nu) = 0.164551 1/s**; then 1 + beta2 omega0 t = 1.224809, and at 3 D
upstream k = 6.0000e-4 (I = 2.0000 %), omega = 0.134348 1/s, nut/nu = 98.3. The app's inputs: Free stream >
turbulence intensity 2.23302 % (0.022330230635474405) and viscosity ratio 100 (k = 1.5 (U I)^2, omega = k / (nu R)).

### The run

The coarse level as the earlier PIMPLE Co 2 run (run/validation/square_re22000/coarse): the same mesh settings and
domain (meshed again, 6 processes), k-omega SST, PIMPLE at Co 2, the detected sampling start, end 150 t_c; the inflow
above; **no start-up perturbation** (both options off, the app's default since D-198). 6 MPI processes, nice 15, a
solver time limit of 3 h (`scripts/validation/square_study.py level --name coarse --end 150 --cores 6 --mesh-cores 6
--timeout-h 3 --tag matched --intensity 0.022330230635474405 --viscosity-ratio 100 --set perturb=false --set
perturb_initial=false`). If by 150 t_c the detection has not found a window with at least 5 shedding cycles, the run
is continued once to 200 t_c with the app's Continue (D-189), the detection going on (`continue --run coarse_matched
--end 200`), within the 3 h cap.

### Rule

1. **Inflow check**: the modelled intensity I = sqrt(2k/3) / U at the cell nearest (x, z) = (-3 D, 0), averaged over
   the written times inside the sampled window (the sampling-switch time and the end; the upstream free stream is
   steady), is within 2.0 ± 0.2 percentage points (1.8-2.2 %). If not, it is reported and the run still counts, but
   the inflow is said not to be matched.
2. **Shedding** (the rule of diagnostic a): "sheds" if the lift range (max - min of Cl) is ≥ 1.0 in both of the last
   two 10 t_c intervals of the run; "steady" if ≤ 0.2 in both; otherwise "undetermined".
3. **If it sheds**: this file's original pass rule (ERCOFTAC UFR 2-02, Lyn et al. 1995: St within 10 % of 0.133, mean
   Cd within 15 % of 2.1) over the window the app's automatic start-up detection chose, which must hold at least 5
   shedding cycles (the app's cycle count of the lift in the window). A window of fewer cycles gives no verdict.
