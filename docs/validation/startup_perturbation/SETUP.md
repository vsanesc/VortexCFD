# Start-up perturbations: equivalence measurements (A and B)

Task 1.1-transient, Part 2 closing brief (QUESTIONS 259, D-198). Written and committed before any of these runs;
the rules below are not changed after them.

## What it checks

Whether the two declared start-up perturbations of a transient external flow change the sampled answer, and how much
start-up time they save:

- **Initial-field perturbation** (new, D-198): a small, localised cross-flow component added to the initial
  velocity field only (the boundary conditions untouched; after t = 0 the run is exactly the user's set-up). Its
  amplitude, shape and declared end are those of D-198 as implemented before these runs.
- **Inflow swing** (D-187, kept as a separate option): the inflow direction swings by ±10° at 0.2 U / l_ref for the
  first 10 t_c.

A start-up perturbation is acceptable only if it leaves the sampled flow unchanged: it should shorten the start-up,
not change the statistics.

## A. Circular cylinder, Re 100, laminar, coarse level

The cylinder validation's coarse level (docs/validation/cylinder_re100/SETUP.md: 17,182 cells, PISO at Co 1, the
laminar defaults), three runs that differ only in their start:

| Run | Start |
|---|---|
| none | no perturbation |
| initial | the initial-field perturbation only |
| swing | the inflow swing only (±10°, 10 t_c) |

Each run: from the free stream, sampling start set by hand at 180 t_c, end 240 t_c, 4 MPI processes, nice 15,
one run at a time (`scripts/validation/cylinder_study.py level --name coarse --end 240 --start 180 --cores 4 --tag
<run> --set perturb=... --set perturb_initial=...`). Without a perturbation this mesh's start-up was detected at
151.7 and 153.7 t_c (Part 1 and Part 2 runs), so 180 t_c leaves margin; the window holds about 10 shedding
cycles.

**Measured quantities** (scripts/validation/window_compare.py, the app's own functions in foam/transient.py, from
the force history): over the window [180, 240] t_c and over its halves [180, 210] and [210, 240]: the Strouhal
number of the lift (St), the mean Cd and the RMS of Cl.

**Rule (equivalence).** For each quantity Q, let d = |Q_run − Q_none| over the whole window, and the window-to-window
variability v = max(|Q_run[180, 210] − Q_run[210, 240]|, |Q_none[180, 210] − Q_none[210, 240]|). A perturbed run is
**equivalent** to the unperturbed one when d ≤ v for every one of St, mean Cd and RMS Cl; otherwise it is **not
equivalent**, and the quantities that exceed v are reported with d, v and d relative to Q_none. Each option is
judged on its own (initial vs none, swing vs none).

**Start-up time saved.** The start-up time of each run is the time at which the app's detection (D-181, D-186:
two consecutive windows of 20 t_c, the mean of Cd within 0.5 %, the ranges of Cd and Cl within 5 %, both windows
after the end of the run's perturbation) settles on its force history, checked every W/50 as SolverRun checks,
in t_c and in time steps (from the solver log). Saved by an option = start-up time of "none" − start-up time of
the option, in t_c and in steps. Wall times are reported as indicative only (another workload ran on the machine).

If a run's start-up is detected after 180 t_c, A gives no verdict for that run (its window would include the
start-up) and this is reported.

## B. Square cylinder, Re 22,000, URANS, coarse level

The square-cylinder validation's coarse level (docs/validation/square_re22000/SETUP.md: 27,234 cells, k-omega SST,
PIMPLE at Co 2, the turbulent defaults). One new run with the initial-field perturbation only (no inflow swing),
from the free stream, sampling start set by hand at 96 t_c, end 150 t_c, 6 MPI processes, nice 15
(`scripts/validation/square_study.py level --name coarse --end 150 --cores 6 --tag initial --set perturb=false
--set perturb_initial=true --set sampling_start=96`). The reference is the existing PIMPLE Co 2 coarse run
(run/validation/square_re22000/coarse: the inflow swing, ±10° for 10 t_c, 4 processes), cut to the same window;
it is not rerun.

**Measured quantities and rule:** as A, over the window [96, 150] t_c and its halves [96, 123] and [123, 150],
with the swing run as the reference: the initial-field run is **equivalent** when, for each of St, mean Cd and RMS
Cl, |Q_initial − Q_swing| ≤ max(|Q_initial[96, 123] − Q_initial[123, 150]|, |Q_swing[96, 123] − Q_swing[123, 150]|).
The start-up times by the app's detection are reported as in A (for information; this flow's lift is modulated at
low frequency, so its detection settles late either way: 95.8 t_c in the reference run).

## Machine

Ryzen 9 5900X, WSL2, OpenFOAM v2606. Another workload ran on the other cores during these runs: every wall time
here is indicative only, measured with another workload running; no cost or scaling conclusion is drawn from them.

## A2. Follow-up: the three cylinder runs extended to 300 t_c (owner's addendum)

Written and committed before the extension runs; A's verdict (the initial-field perturbation fails its rule) stands
and A's rule is not relaxed. This follow-up checks whether the unperturbed run had fully settled on its limit cycle in
180-240 t_c.

Runs: the three A runs (none, initial, swing) continued from 240 to 300 t_c with the app's Continue (D-189;
`scripts/validation/cylinder_study.py continue --run coarse_<run> --end 300`), every setting kept (sampling from
180 t_c, PISO at Co 1, 4 processes), one at a time. Measured as in A over the window [240, 300] t_c and its halves
[240, 270] / [270, 300].

**Rule 1 (settling of "none").** The unperturbed run had settled in 180-240 when, for each of St, mean Cd and RMS Cl,
|Q_none[240, 300] − Q_none[180, 240]| ≤ |Q_none[180, 210] − Q_none[210, 240]| (its own window-to-window variability in
A). Otherwise it had not, and the change is reported.

**Rule 2 (equivalence in the later window).** A's rule applied to [240, 300]: a perturbed run is equivalent to "none"
when, for each of St, mean Cd and RMS Cl, |Q_run − Q_none| over [240, 300] ≤ max(|Q_run[240, 270] − Q_run[270, 300]|,
|Q_none[240, 270] − Q_none[270, 300]|). This is reported beside A's verdict, not in place of it.
