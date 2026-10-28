# Square cylinder at Re 22,000, 2D URANS: an investigation (not a validation)

Task 1.1-transient, Part 2. Set-up: [SETUP.md](SETUP.md). Numbers: [result.json](result.json) and the files named in
each section. Drivers: scripts/validation/square_study.py, scripts/validation/square_diagnostics.py; project
builder: tests/validation/square_case.py; OpenFOAM v2606.

## Status: an investigation; URANS available, not validated (D-199)

This case was set up as a validation of 2D URANS (k-omega SST) with a pass rule (SETUP.md). The runs that followed
showed that the same coarse set-up reaches different sustained states depending on the start-up, the time step and
the inflow turbulence, so the owner closed it as an investigation (D-199, QUESTIONS 257): the pass rule is withdrawn,
no URANS result here carries a verdict, and URANS ships in 1.1 as available but not validated. The numbers below are
kept as measured.

The four sustained states of the coarse level (27,234 cells, k-omega SST with wall functions, PIMPLE with residual
control 1e-4, the same mesh and dictionaries otherwise):

| State | Start-up | Inflow turbulence (inlet; at 3 D upstream) | Coupling | Window (t_c) | St | mean Cd | RMS Cl | The wake |
|---|---|---|---|---|---|---|---|---|
| 1 | inflow swing, ±10° for 10 t_c | 2 %, viscosity ratio 10; 1.0 % | PIMPLE Co 2 | 96-150 | 0.1353 | 2.129 | 1.405 | shedding, modulated |
| 2 | initial-field perturbation | 2 %, ratio 10 (not sampled at 3 D) | PIMPLE Co 2 | 96-150 | 0.1435 | 2.008 | 1.136 | shedding, constant amplitude |
| 3 | inflow swing, ±10° for 10 t_c | 2 %, ratio 10; 0.75 % | PIMPLE Co 1 | 96-150 | (0.109) | 1.511 | 0.014 | nearly steady (no shedding) |
| 4 | none (the default) | 2.23 %, ratio 100; 2.0 % (the experiment's) | PIMPLE Co 2 | 100-200 | 0.097 | 2.425 | 1.531 | irregular shedding, never detected as settled |

The experiment (ERCOFTAC UFR 2-02, Lyn et al. 1995): St 0.132-0.133, C_D 1.9-2.2, approach turbulence about 2 % at
3 D upstream. State 3's "St" is the spectral peak of a lift of amplitude about 0.02, not a shedding frequency; state 4's
window was set here (the app's detection found none by 200 t_c). Sources: states 1 and 3, "Time-step convergence"
below; state 2, docs/validation/startup_perturbation/RESULT.md, "B"; state 4, "Matched inflow turbulence" below.

**Conclusion.** On this coarse 2D mesh, k-omega SST URANS of the square cylinder has several sustained states, and
which one a run reaches is decided by its start-up (the perturbation, the time step and coupling during it) and by
the free-stream turbulence that reaches the body; a developed shedding is kept at Co 1 when started from it
(diagnostic a), so the states coexist rather than one being an unconverged form of another. Two of the four states
fall within the experiment's ranges (states 1 and 2 for St within 10 % and C_D within 1.9-2.2), the default start-up
with the experiment's inflow turbulence does not (state 4), and none can be called the model's answer for this case.
What remains open (docs/PLAN.md, "Later"): the medium mesh and 3D, and a free stream that keeps its turbulence to the
body (kOmegaSST's decay control).

## The first runs (Part B): the coarse and medium levels with the inflow swing at PIMPLE Co 2

| Level | Cells | Steps | Δt range (s) | Sampling from (t_c, detected) | Cycles | St | mean Cd | RMS Cl |
|---|---|---|---|---|---|---|---|---|
| coarse | 27,234 | 112,902 | 0.00040-0.0022 | 95.8 | 14.1 | 0.1355 | 2.132 | 1.422 |
| medium | 40,527 | 65,593 | 0.00020-0.0073 | 82.3 | 8.9 | 0.1310 | 2.082 | 1.474 |

Differences from ERCOFTAC UFR 2-02 (Lyn et al. 1995: St 0.133 ± 0.004 measured; Cd ≈ 2.1 inferred from the wake;
the Evaluation page's Table 1 lists the experiments as St 0.132, C_D 1.9-2.2):

| Level | St | mean Cd |
|---|---|---|
| coarse | +1.9 % | +1.5 % |
| medium | -1.5 % | -0.8 % |

The two levels bracket the references rather than converge monotonically towards them (St 0.1355 -> 0.1310, Cd
2.132 -> 2.082 from coarse to medium): with two levels and a modulated signal no extrapolation is attempted. Mean Cl
-0.004 / -0.014, Cd RMS 0.19 / 0.14. SETUP.md's original rule is withdrawn (D-199) and is not applied here.

## What the runs show

- **The start-up perturbation and the detection.** The shedding was developed from about 10 t_c (lift amplitude
  1.5-2.2 per 5 t_c from then on). The lift amplitude is modulated at low frequency (between 1.0 and 2.1 per 5 t_c
  over the whole run), so the detection (0.5 % on the window mean of Cd, 5 % on the ranges) settled only at
  95.8 t_c (coarse) and 82.3 t_c (medium); SETUP's fallback (a sampling start set by hand) was not needed.
- **The k-omega scheme.** The first run of this case crashed in its first step with D-181's limitedLinear k and
  omega (omega clipped to -1213, then a floating-point exception); with D-192's linearUpwind on limited gradients
  neither level clipped omega.
- **PIMPLE at Co 2 on a mesh with wall layers.** Every step ran 3 outer correctors (residual control 1e-4). The
  largest Courant number exceeded the target only in the first two steps of the impulsive start (6.1 and 11.0 at
  t ≈ 0.0015 s), not in the sampled flow.

## Start-up perturbation used (declared, D-198)

These runs used the inflow swing (±10° at 0.2 U / D for 10 t_c, then +x), as SETUP.md states; no initial-field
perturbation. The sampling windows all start after it ended (detected at 95.8 and 82.3 t_c; set at 96 t_c for the
window comparisons). They were not rerun after D-198 made both perturbations declared options, off by default.

## Cost

| Level | Cells | Solver wall time | Wall time per step | Wall µs per cell and step (4 cores) |
|---|---|---|---|---|
| coarse | 27,234 | 7,297 s (200 t_c) | 0.065 s | 2.4 |
| medium | 40,527 | 6,293 s (150 t_c) | 0.096 s | 2.4 |

## PISO and PIMPLE on this mesh (D-185)

A PISO run of the coarse level at Co 1 to 15 t_c (`level --name coarse --end 15 --tag piso_timing --set
algorithm=piso`, run/validation/square_re22000/, beside the DDES run) against the PIMPLE run's first 15 t_c (beside
the medium level): PISO 16,139 steps in 759 s, PIMPLE at Co 2 8,768 steps in 613 s (3 outer correctors each).
PIMPLE took 19 % less wall time here, where the wall layers set the Courant limit (on the laminar cylinder, whose
limit is set by the wake cells, it took 26 % more). The PISO run's statistics were not sampled (timing only).

### PISO and PIMPLE over a sampled window (Part 2 review)

A PISO run of the coarse level at Co 1 (6 cores, `--tag piso_window --set algorithm=piso --set sampling_start=96`,
157,885 steps to 150 t_c in 3,596 s) against the PIMPLE coarse run, statistics over the same window 96-150 t_c
from the force histories:

| Coupling | St | mean Cd | RMS Cl | St 96-123 / 123-150 | Cd 96-123 / 123-150 |
|---|---|---|---|---|---|
| PIMPLE, Co 2 | 0.1353 | 2.129 | 1.405 | 0.1359 / 0.1368 | 2.154 / 2.103 |
| PISO, Co 1 | 0.1250 (-7.6 %) | 1.939 (-8.9 %) | 1.030 | 0.1250 / 0.1251 | 1.940 / 1.938 |

Each run agrees with itself across the two halves of the window to about 1-2 %, so the difference between them is
systematic, not sampling noise: on this case the coupling changes the answer by 8-9 %, unlike the laminar cylinder
(0.1-0.4 %). Both lie within the original rule's tolerances, withdrawn by D-199 (PISO: St -6.0 %, Cd -7.7 % against 0.133 and 2.1); PIMPLE,
which iterates each step to the outer tolerance, is the nearer to the experiment. QUESTIONS 257.

## Time-step convergence: PIMPLE at Co 1 (QUESTIONS 257; Part 2 closing brief, measurement C)

Rule committed before the run (SETUP.md, "Time-step convergence", commit 8f73cbc): if PIMPLE Co 1 and PIMPLE Co 2
agree within 2 % in St and mean Cd, PIMPLE is time-step converged there and PISO Co 1 is the outlier; otherwise the
three runs are reported as they are. Run: the coarse level, PIMPLE (at most 10 outer correctors, residual control
1e-4) at a largest Courant number of 1, the same start-up as the other two (the inflow swing, ±10° for 10 t_c),
sampling set at 96 t_c, end 150 t_c, 6 processes (`--tag pimple_co1`; the mesh step ran on 8 processes for 12 s,
over the brief's limit of 6, before `--mesh-cores` existed). Its mesh is the same as the other two runs' (27,234
cells; the points agree to 5e-6 m, only their numbering differs) and its dictionaries differ from the PIMPLE Co 2
run's only in maxCo and the end and sampling times. 141,315 steps (2.5 outer correctors per step), Δt
0.00020-0.0011 s; the Courant number above 1 only in the first, impulsive step (5.7 at t = 0.0013 s). Solver wall
time 4,235 s on 6 processes (indicative only: measured with another workload running). Numbers:
[time_step.json](time_step.json) (scripts/validation/window_compare.py, window 96-150 t_c).

| Run | St | mean Cd | RMS Cl | St 96-123 / 123-150 | Cd 96-123 / 123-150 |
|---|---|---|---|---|---|
| PIMPLE, Co 2 | 0.1353 | 2.129 | 1.405 | 0.1359 / 0.1368 | 2.154 / 2.103 |
| PIMPLE, Co 1 | 0.1090 (-19.4 %) | 1.511 (-29.0 %) | 0.014 | 0.1020 / 0.1120 | 1.511 / 1.512 |
| PISO, Co 1 | 0.1250 (-7.6 %) | 1.939 (-8.9 %) | 1.030 | 0.1250 / 0.1251 | 1.940 / 1.938 |

**Verdict under the rule: PIMPLE Co 1 and PIMPLE Co 2 do not agree within 2 %** (St -19.4 %, mean Cd -29.0 %), so
nothing is concluded about time-step convergence. What the three runs show:

- **PIMPLE at Co 1 loses the shedding.** The lift range per 10 t_c is 2.4 during the swing (0-10 t_c), 1.3 at 10-20,
  0.2 at 20-30 and 0.02-0.06 from 50 t_c to the end; the mean Cd settles at 1.51. The flow becomes nearly steady
  and symmetric; its "St" (a spectral peak of a lift of amplitude about 0.02) is not a shedding frequency.
- **PISO at Co 1 and PIMPLE at Co 2 shed throughout**, with different amplitudes: lift range per 10 t_c about 2.9
  (PISO, constant from 20 t_c) and 3.6-4.4 (PIMPLE Co 2).
- So on this coarse mesh the 2D URANS solution depends on the time stepping and the coupling: three runs that differ
  only in Δt or in the outer correctors give a decaying wake, a moderate shedding and a strong shedding. Halving
  PIMPLE's time step moved the answer away from the experiment (St 0.132-0.133, Cd 1.9-2.2), not towards a limit.
  The cause is not established (the PIMPLE outer loop's exit at the residual tolerance, which leaves each step's
  coupling only partly converged, and the eddy viscosity of SST damping a weak shedding are candidates; neither was
  tested).
- The first runs' agreement with the experiment (PIMPLE Co 2, the app's default) is not shown to be time-step
  independent. No default was changed. For the owner: QUESTIONS 257 (closed by D-199: an investigation, not a
  validation).

## Diagnostics of measurement C (owner's addendum)

Rules committed before the runs and samples (SETUP.md, "Diagnostics of measurement C", commit bd7273a; two driver
fixes after it, neither touching a rule: the restart folder created first, and PIMPLE Co 2's fields at the switch read
from their reconstructed copy). Lift histories (offscreen PNG): ~/vortexcfd-research/1.1-urans-diagnostics/
(lift_all.png and one per run; outside the repository).

### a. Restart from PIMPLE Co 2 at 95.8 t_c, continued at PIMPLE Co 1

The PIMPLE Co 2 run's fields at its sampling switch (t = 95.81674986, with their old-time fields), continued to 150 t_c
at a largest Courant number of 1, everything else unchanged, 6 processes: 60,416 steps (Δt 0.00080-0.0011 s; the
Courant number 2.0 in the first step after the restart only, at the Co 2 run's last step, then 1), 2.85 outer
correctors per step, 1,937 s (indicative only: measured with another workload running). Numbers:
[diagnostic_a.json](diagnostic_a.json).

| Run | St | mean Cd | RMS Cl | lift range 130-140 / 140-150 |
|---|---|---|---|---|
| PIMPLE Co 2 | 0.1353 | 2.129 | 1.405 | 4.30 / 4.14 |
| a: Co 2 -> Co 1 at 95.8 t_c | 0.1352 (-0.04 %) | 2.131 (+0.10 %) | 1.405 (-0.04 %) | **4.31 / 4.14** |
| C: PIMPLE Co 1 from the start | 0.1090 | 1.511 | 0.014 | 0.04 / 0.02 |

**Verdict under the rule: the shedding persists** (lift range ≥ 1.0 in both intervals). Reading fixed in advance: at
PIMPLE Co 1 the two states coexist on this mesh and the start-up selects one. A developed shedding is sustained at
Co 1 with the Co 2 run's statistics (within 0.1 %); C's nearly steady wake is the other state, reached because C's
shedding had not developed when its start-up swing ended.

### b. Eddy viscosity and inflow turbulence (no solver run)

Instantaneous written fields, the cell nearest each point on z = 0. Numbers: [diagnostic_b.json](diagnostic_b.json).
The inlet (x = -19.5 D): k 6.0e-4 m²/s², omega 1.32 1/s: I = 2.0 %, nut/nu = 10 (the app's defaults with the inlet
intensity 2 % set by the validation). Analytic decay of that free stream under SST's far-field terms, convected at U:
I 1.36 / 1.14 / 1.10 / 1.08 % and nut/nu 9.4 / 9.1 / 9.1 / 9.1 at x = -10 / -3 / -1 / -0.05 D.

| Point (x in D) | C (Co 1), t 150 | PISO Co 1, t 150 | PIMPLE Co 2, t 95.8 | PIMPLE Co 2, t 200 |
|---|---|---|---|---|
| upstream -10: nut/nu, I | 3.35, 1.15 % | 3.51, 1.16 % | 6.69, 1.33 % | 6.69, 1.33 % |
| upstream -3: nut/nu, I | 1.42, **0.75 %** | 1.53, **0.77 %** | 3.80, **1.00 %** | 3.80, **1.00 %** |
| upstream -1: nut/nu, I | 1.22, 0.70 % | 1.29, 0.72 % | 3.52, 1.00 % | 3.53, 1.00 % |
| front face -0.05: nut/nu, I | 1.45, 1.87 % | 1.56, 1.98 % | 2.21, 2.36 % | 2.21, 2.37 % |
| near wake 1.5: nut/nu | **887** | 427 | 347 | 139 |
| near wake 2: nut/nu | **2,310** | 574 | 369 | 2.2 |
| near wake 3: nut/nu | **3,530** | 101 | 226 | 544 |

Reference: ERCOFTAC UFR 2-02 (Test Case page, opened 2026-10-28): "The approach flow was measured 3 cylinder widths
upstream and had a turbulence level of about 2%"; "no information is available from the measurements on the length
scale of the turbulence"; an inflow viscosity ratio of 10 recommended, the inflow 5 to 10 D upstream.

- **(b1) Approach turbulence: lower** than the experiment's in every run: I = 0.75-1.00 % at 3 D upstream against
  about 2 %. The inlet sits 19.5 D upstream (the preset's C-type far field), twice the page's 5-10 D, and the free
  stream's turbulence decays on the way: the analytic SST decay alone leaves 1.14 %, and the computed fields have less
  still (nut/nu 1.4-3.8 where the analytic decay keeps about 9). The upstream values also differ between the runs
  (C and PISO alike; PIMPLE Co 2 about 15-35 % higher in I and 2-2.7 times in nut/nu, the same at 95.8 and 200 t_c); why
  was not examined.
- **(b2) C's near-wake eddy viscosity: higher**: it exceeds both other runs (each sampled time) by more than a factor
  2 at all three near-wake points (887-3,530 against 2-574). By the rule this makes eddy-viscosity damping a candidate
  in C, not a proof: with a (the same Co 1 sustains the shedding when started from it), the high wake eddy viscosity
  may as well be a property of the steady state (long, steady shear layers) as its cause.

### c. C rerun with turbOnFinalIterOnly false (diagnostic only)

C exactly, with `turbOnFinalIterOnly no;` written into the case's PIMPLE dictionary after the app wrote it (k and omega
solved in every outer corrector); no app code or setting changed. 141,024 steps, 2.5 outer correctors per step, 5,832
s (indicative only: measured with another workload running), the Courant number above 1 only in the first step.
Numbers: [diagnostic_c.json](diagnostic_c.json).

| Run | St | mean Cd | RMS Cl | mean Cl | lift range 130-140 / 140-150 |
|---|---|---|---|---|---|
| C: turbOnFinalIterOnly true (default) | 0.1090 | 1.511 | 0.014 | 0.122 | 0.04 / 0.02 |
| c: turbOnFinalIterOnly false | 0.1077 | 1.512 | 0.016 | 0.113 | **0.03 / 0.02** |

**Verdict under the rule: the shedding decays** (lift range ≤ 0.2 in both intervals). Reading fixed in advance:
solving the turbulence only on the final outer corrector is not (alone) the cause of C's loss of shedding. The lift
histories of C and c agree nearly interval by interval (lift range per 10 t_c 2.44 / 2.45, 1.27 / 1.19, 0.22 / 0.21,
then both 0.02-0.07; [lift_ranges.json](lift_ranges.json)).

### What the diagnostics show together

- At PIMPLE Co 1 on this mesh **two sustained states exist**: the developed shedding (sustained from a restart, a) and
  a nearly steady wake with a small steady lift (mean Cl 0.11-0.12, its range 0.07-0.16: an asymmetric steady
  solution), reached from the free stream (C, c). Which one a run ends in is decided during the start-up.
- The lift histories (~/vortexcfd-research/1.1-urans-diagnostics/lift_all.png) show where: during the 10 t_c swing the
  Co 1 runs (C, c) answer with about half the lift amplitude of PISO Co 1 and PIMPLE Co 2 (peak |Cl| 1.2-1.4 against
  1.7-2.5), and after the swing their oscillation decays, while the others' grows into shedding. B adds a third
  sustained state at PIMPLE Co 2 (constant-amplitude shedding after the initial-field start, St 0.1435, Cd 2.008).
- The cause of the different start-up response at Co 1 is not established. Not the turbulence-per-outer-corrector
  setting (c). The model's approach turbulence is about half the experiment's (b1), and C's steady wake carries 2-35
  times the eddy viscosity of the shedding runs (b2), which would damp a weak oscillation; whether that is cause or
  consequence of the steady state is open.

## Matched inflow turbulence, default start-up (QUESTIONS 257 follow-up)

Set-up, the inlet arithmetic and the rule: SETUP.md, "Matched inflow turbulence, default start-up" (committed before
the run, f955494). The inlet: intensity 2.23302 %, viscosity ratio 100 (k0 7.4796e-4 m²/s², omega0 0.16455 1/s), so
that SST's free-stream decay leaves 2 % at 3 D upstream; ratio 10, the value the ERCOFTAC page favours, cannot reach
2 % there from this inlet (at most 1.28 %; QUESTIONS 263). No start-up perturbation (the default since D-198).

Case dictionaries against the earlier PIMPLE Co 2 run (run/validation/square_re22000/coarse): 0/k and 0/omega (the
inlet, internal and inlet-outlet values: k 6.0e-4 -> 7.4796e-4, omega 1.32 -> 0.16455); 0/U's inlet fixedValue
instead of the swing's table and transientControl's notBefore 10 -> 0 (no perturbation); the end time 150 instead of
200 (controlDict endTime and writeInterval, transientControl endTime); 6 processes instead of 4 (decomposeParDict);
transientControl's maxCourant / maxDeltaT records (D-194, written by later code, not read by OpenFOAM). The earlier
case's startFrom latestTime, fieldAverage entry and samplingStart were written by its sampling switch during its run,
not inputs. fvSchemes, fvSolution, turbulenceProperties, transportProperties, 0/p and 0/nut are identical. The mesh was
meshed again on 6 processes (27,234 cells, max non-orthogonality 58.73, as before).

The run: 81,916 steps to 150 t_c (3,493 s), no start-up detected, so continued once to 200 t_c as SETUP.md provides
(29,331 more steps, 1,287 s): 111,247 steps, Δt 0.00043-0.0025 s, 3.0 outer correctors per step, the Courant number
above 2 only in the first step. Solver wall time 4,780 s on 6 processes, indicative only: measured with another
workload running (a serial run of another project was on the machine from 17:21). Numbers: coarse_matched.json (run
folder), [inflow_coarse_matched.json](inflow_coarse_matched.json), [matched_96_150.json](matched_96_150.json),
[matched_100_200.json](matched_100_200.json). Lift histories overlaid: ~/vortexcfd-research/1.1-urans-diagnostics/
lift_matched_overlay.png.

Lift range and mean Cd per 10 t_c: 0.04 / 1.43, 0.37 / 1.54, 2.97 / 1.60, 4.46 / 2.40, 4.81 / 2.58, 3.77 / 2.30, 3.92 /
2.24, 3.58 / 2.03, 2.54 / 1.71, 3.87 / 1.88, 3.78 / 1.86, 4.32 / 2.37, 4.92 / 2.83, 5.62 / 2.56, 4.64 / 2.56, 5.20 /
2.67, 5.10 / 2.41, 4.58 / 2.31, 4.99 / 2.49, 4.01 / 2.30 (0 to 200 t_c). The shedding grows from round-off and is
developed from about 25 t_c; it stays irregular (a dominant period of about 10 t_c with secondary peaks in each cycle)
and modulated at low frequency.

**Verdict under each part of the rule:**
1. **Inflow check: matched at both written times.** I at the cell nearest (-3 D, 0): 1.995 % at 150 t_c and 1.999 %
   at 200 t_c (nut/nu 75 and 65; the analytic decay gives 2.000 % and 98), within 1.8-2.2 %. The rule's average "over
   the written times inside the sampled window" has no window to use (none was detected), so both written times are
   reported instead; the upstream free stream is steady. The earlier runs had 0.75-1.0 % there (diagnostic b).
2. **Shedding: sheds** (lift range 4.99 and 4.01 in [180, 190] and [190, 200], ≥ 1.0).
3. **Pass rule: no verdict.** The app's automatic start-up detection did not find a window by 200 t_c (the Cd window
   means and ranges kept changing between 20 t_c windows, below), so there is no detected window
   to judge; the rule requires one.

Why it did not settle: between consecutive 20 t_c windows the mean Cd moved by 0.30-0.54 (up to 25 %) and the lift
range by up to 25 % until 160 t_c. In the last pair, [160, 180] / [180, 200], the mean Cd (0.2 %) and the lift range
(2 %) agree, but the range of Cd does not (2.29 -> 2.56, 11 %; the detection asks 5 % of it too).

For information only (not a verdict; windows set here, not detected):

| Run (coarse, 2D URANS) | Window (t_c) | St | mean Cd | RMS Cl | I at 3 D upstream |
|---|---|---|---|---|---|
| matched inflow, no perturbation, PIMPLE Co 2 | 100-200 | 0.0971 | 2.425 | 1.531 | 2.0 % |
| matched inflow, no perturbation, PIMPLE Co 2 | 96-150 | 0.0952 | 2.416 | 1.526 | 2.0 % |
| swing, PIMPLE Co 2 (the first coarse run) | 96-150 | 0.1353 | 2.129 | 1.405 | 1.0 % |
| swing, PIMPLE Co 1 (C) | 96-150 | 0.1090 | 1.511 | 0.014 | 0.75 % |
| initial field, PIMPLE Co 2 (B) | 96-150 | 0.1435 | 2.008 | 1.136 | (not sampled) |
| PISO Co 1, swing | 96-150 | 0.1250 | 1.939 | 1.030 | 0.77 % |

Over 100-200 t_c the matched run's St would be -27 % and its mean Cd +15.5 % from the references (0.133, 2.1): outside
the pass rule's 10 % and 15 % on both, had a detected window existed. Its "St" is the lift spectrum's peak of an
irregular signal (about one main cycle per 10 t_c), not a clean shedding frequency.

Reading: with the default start-up and the experiment's approach turbulence at 3 D upstream, this coarse 2D URANS case
sheds, but on a fourth state, irregular, slower and with more drag than the first coarse run's, and the app's detection never
declares it settled. The change of inflow is large in the model's terms (nut/nu about 70 instead of about 4 at 3 D
upstream, from the ratio 100 needed to keep 2 % over 16.5 D of decay), so this run shows how sensitive the state is
to the free-stream turbulence as much as to the start-up.
