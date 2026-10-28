# Square cylinder at Re 22,000, 2D URANS: result

Task 1.1-transient, Part 2, Part B (3a). Set-up and pass rule: [SETUP.md](SETUP.md) (written before the runs; two
amendments before any result). Numbers: [result.json](result.json). Driver: scripts/validation/square_study.py;
project builder: tests/validation/square_case.py; OpenFOAM v2606, 4 cores per level, nice 15, the two levels side
by side.

## Verdict: PASS, under investigation (QUESTIONS 257)

The PASS below was measured with PIMPLE at Co 2 (the app's default). Measurement C ("Time-step convergence", at the
end) found that PIMPLE at Co 1 loses the shedding on the coarse mesh, where PISO at Co 1 and PIMPLE at Co 2 shed: until
that is understood this case's status is "PASS under investigation" and URANS is not called validated.

The medium level (the deciding one) passes both criteria; the coarse level passes too.

| Level | Cells | Steps | Δt range (s) | Sampling from (t_c, detected) | Cycles | St | mean Cd | RMS Cl | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| coarse | 27,234 | 112,902 | 0.00040-0.0022 | 95.8 | 14.1 | 0.1355 | 2.132 | 1.422 | PASS |
| medium | 40,527 | 65,593 | 0.00020-0.0073 | 82.3 | 8.9 | 0.1310 | 2.082 | 1.474 | PASS |

Errors against ERCOFTAC UFR 2-02 (Lyn et al. 1995: St 0.133 ± 0.004 measured; Cd ≈ 2.1 inferred from the wake;
the Evaluation page's Table 1 lists the experiments as St 0.132, C_D 1.9-2.2: both levels are inside that range
too):

| Level | St | mean Cd |
|---|---|---|
| coarse | +1.9 % | +1.5 % |
| medium | -1.5 % | -0.8 % |
| tolerance | 10 % | 15 % |

Both levels are inside the experiment's ±0.004 band for St (0.129-0.137). The two levels bracket the references
rather than converge monotonically towards them (St 0.1355 -> 0.1310, Cd 2.132 -> 2.082 from coarse to medium):
with two levels and a modulated signal no extrapolation is attempted. Mean Cl -0.004 / -0.014, Cd RMS 0.19 / 0.14.

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
(0.1-0.4 %). Both would pass this validation's rule (PISO: St -6.0 %, Cd -7.7 % against 0.133 and 2.1); PIMPLE,
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
- The validation's verdict (PASS, on PIMPLE Co 2, the app's default) is unchanged as measured, but it is not shown to
  be time-step independent. No default was changed. For the owner: QUESTIONS 257.
