# Circular cylinder at Re 100: result

Task 1.1-transient, Part B. Set-up and pass rule: [SETUP.md](SETUP.md). Numbers: [result.json](result.json) (the
collected table and the GCI) and [runs/](runs/) (each run's record: mesh, steps, time steps, Courant number,
statistics). Driver: scripts/validation/cylinder_study.py; project builder: tests/validation/cylinder_case.py;
OpenFOAM v2606, 4 cores per level, nice 15, the machine shared with another agent's runs.

## Verdict: PASS

Every level passes all three criteria. Against the sourced references (SETUP.md, "References", amended in Part 2,
Part 0; the rule and its tolerances unchanged) the finest level (63,369 cells, 10.6 shedding cycles sampled) has St
inside the band, mean Cd -0.8 % and RMS Cl -8.7 %. Against the first, unsourced references it was within 0.7 % of
each; the verdict is the same.

| Level | Background cell | Cells | Steps | Δt range (s) | Sampling from (t_c) | Cycles | St | mean Cd | RMS Cl | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| coarse | 1.414 m (surface D/90.5) | 17,182 | 25,243 | 0.0012-0.0076 | 153.7 (detected) | 4.3 | 0.1638 | 1.3402 | 0.2298 | PASS |
| medium | 1 m (D/128) | 32,817 | 35,767 | 0.0012-0.0054 | 147.4 (detected) | 5.4 | 0.1647 | 1.3390 | 0.2290 | PASS |
| fine | 0.707 m (D/181) | 63,369 | 56,366 | 0.0012-0.0038 | 135.9 (detected) | 10.6 | 0.1649 | 1.3391 | 0.2309 | PASS |

Errors against the sourced references (St: to the nearer end of the band 0.164-0.165, 0 inside it; Cd: against 1.35;
RMS Cl: against 0.253), with the errors against the first, unsourced references (0.164-0.166, 1.33, 0.23) in brackets:

| Level | St | mean Cd | RMS Cl |
|---|---|---|---|
| coarse | -0.09 % (-0.09 %) | -0.73 % (+0.77 %) | -9.17 % (-0.08 %) |
| medium | 0, in the band (0) | -0.81 % (+0.68 %) | -9.50 % (-0.45 %) |
| fine | 0, in the band (0) | -0.81 % (+0.68 %) | -8.73 % (+0.39 %) |
| tolerance | 3 % | 5 % | 15 % |

The fine level's other statistics: Cd RMS 0.0066 (Cd oscillates at twice the shedding frequency, 1.3297-1.3485 on the
coarse level), Cl between -0.326 and +0.326 (amplitude 0.326), mean Cl -0.001.

## Mesh study

GCI (Celik et al. 2008) with h = (A / N)^(1/2):

| Quantity | coarse / medium / fine | Convergence | Apparent order | Extrapolated | GCI fine |
|---|---|---|---|---|---|
| St | 0.16385 / 0.16466 / 0.16493 | monotonic | 3.5 | 0.16504 | 0.09 % (asymptotic ratio 1.002) |
| mean Cd | 1.34018 / 1.33904 / 1.33907 | oscillatory | — | — | not applicable |

The mean Cd changes by 0.09 % from coarse to medium and by 0.002 % from medium to fine: the change below the
statistical scatter of a mean over 5-10 cycles, so the sign of the last difference is noise and the GCI is not
defined; the mesh error of Cd is below 0.1 %. St converges monotonically to 0.1650, the upper end of the sourced
band (0.164-0.165).

The remaining offsets (Cd -0.8 %, RMS Cl -9 %) are not explained by the mesh (the study converges far tighter). The
RMS Cl reference itself depends on the set-up: Dong and Shen's own values range 0.253-0.261 with the wake length,
and the earlier simulations they list span 0.21-0.27 at Re 100 (SETUP.md, "References"); the app's result, 0.231,
lies inside that spread. The domain here (slip far field 30 D to each side, 50 D wake) differs from the references'
domains; no domain study was made.

## What the runs show of the app (D-181)

- **The adaptive time step**: every level starts from the automatic Δt = t_c / 1000 = 0.001 s (the free-stream
  field's Courant number is below 1, so setInitialDeltaT keeps it), grows by at most 1.2 per step (the first steps
  0.0012, 0.00144, 0.00173 s ...) and settles where the largest Courant number is 1.00 (1.0004 / 1.0002 / 1.005 at
  most): 0.0076, 0.0054 and 0.0038 s, falling with the cell size as it should.
- **The start-up detection** started the sampling at 153.7, 147.4 and 135.9 t_c (the shedding grows from the mesh's
  own asymmetry and saturates at about 100-120 t_c; the detection then needs two settled windows of 20 t_c). At each
  detection the solver was stopped cleanly, fieldAverage was added and the run went on from the written time; the
  log is continuous.
- **The statistics** were written into the run record (`transient.statistics`: mean, RMS, min, max of Cd, Cl,
  CmPitch, St and the cycles) and the field averages (UMean, UPrime2Mean, pMean, pPrime2Mean) into the fine level's
  final time.

Found and fixed during the study: the coarse and medium levels' final time was not written (OpenFOAM counts write
times from the restart time of the sampling switch, so an end time that is not a whole number of intervals after it
is never written); their coefficient statistics, read from the force history, are unaffected, but their field
averages were lost. The fine level and the short run below ran with the fix (the write interval now divides the
remaining time exactly, `transient.even_interval`).

## Short run (Part A)

The coarse level to 60 t_c with the sampling set at 30 t_c and a write interval of 25 t_c (`level --name coarse --end
60 --start 30 --write 25 --tag short`, [runs/coarse_short.json](runs/coarse_short.json)): 8,114 time steps in 136 s
(2 min 29 s with the 11 s meshing), Δt from 0.0012 s to 0.0076 s at Co 1.0, the interval shortened to 20 t_c so the
end is written, UMean, UPrime2Mean, pMean and pPrime2Mean written at t = 60. At 60 t_c the shedding is still growing
(RMS Cl 0.003): the statistics of that window are not physical results, only the proof that they are written.

## Machine time

About 90 minutes of solver time in all, 4 cores per run, nice 15: the coarse 9 min, medium 19 min, fine 45 min (the
fine and medium levels in parallel for part of it), the short run 2.5 min, plus two aborted trial runs before the
statistics checks were throttled and the levels fixed (about 14 min; D-181, "SolverRun checks this every W/50").

## Part 2: PIMPLE and the start-up perturbation (coarse level)

Runs of the coarse level (17,182 cells) through the same driver, 4 cores each, two runs at a time, nice 15
(`level --name coarse ... --set ...`; records in run/validation/cylinder_re100/, not committed). The study above is
unchanged (it ran without the perturbation, which the driver keeps off unless set).

**Start-up perturbation (D-187).** Time to developed shedding (≥ 3 cycles sampled after the detected start-up):

| Run | Start-up detected at | 3 cycles sampled at | Solver wall time to it |
|---|---|---|---|
| no perturbation, PISO | 151.7 t_c | 170.0 t_c | 345 s |
| inflow swinging ±10° at 0.2 U/D for 10 t_c, PISO | 83.9 t_c | 102.2 t_c | 226 s |

With the perturbation the statistics of the detected window are St 0.16383, mean Cd 1.3400, RMS Cl 0.2297 (the
study's coarse level: 0.16385, 1.3402, 0.2298).

**PISO and PIMPLE (D-185)**, the same perturbation, statistics over 60-120 t_c from the force histories:

| Run | Steps | Max Co | St | mean Cd | Solver wall time (120 t_c) |
|---|---|---|---|---|---|
| PISO, Co 1 | 17,377 | 1.0 | 0.16383 | 1.33993 | 265 s |
| PIMPLE, Co 2 | 8,682 | 2.0 | 0.16403 (+0.12 %) | 1.33538 (-0.34 %) | 334 s |
| PIMPLE, max_courant 5 | 6,011 | 3.7 (capped by the largest step, t_c / 50) | 0.16400 (+0.10 %) | 1.33495 (-0.37 %) | 252 s |

PIMPLE needed 3 outer correctors per step (residual control at 1e-4) and is within 1 % of PISO on St and mean Cd.
It saves no wall time on this mesh: its Courant limit is set by the wake cells, not by thin wall layers. PISO stays
the default of laminar projects.
