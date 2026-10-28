# Square cylinder at Re 22,000, 3D DDES: not run (cost)

> **DDES is experimental and not validated in 1.1 (D-197).** This case was not run. No result here is a validation. The Ahmed DDES
> and the choice of a DDES validation case are in "Later" (docs/PLAN.md, QUESTIONS 261).

Task 1.1-transient, Part 2, Step 3. Set-up and pass rule: [SETUP.md](SETUP.md) (committed in 539e779 before any
run). No verdict: the run was not launched because its estimate is far above the 12 hours allowed.

## Scaling and cost (clean: nothing else running)

The 3D case (810,540 cells) from the same start, 80 time steps at each process count (60 measured: the first 20
are left out), with the app's MPI command (`mpirun -np N pimpleFoam -parallel`), nice 15. The steps are in the
impulsive start (Δt about 8e-5 s at Co 1). Numbers: [scaling.json](scaling.json).

| Processes | Wall s per step | s per step per million cells | Speed-up vs 4 | Efficiency vs 4 |
|---|---|---|---|---|
| 4 | 17.56 | 21.7 | 1.00 | 1.00 |
| 6 | 13.25 | 16.4 | 1.33 | 0.88 |
| 8 | **12.86** | **15.9** | 1.37 | 0.68 |
| 10 | 14.05 | 17.3 | 1.25 | 0.50 |
| 12 | 14.74 | 18.2 | 1.19 | 0.40 |

8 processes are the fastest; more are slower (the memory-bandwidth limit of D-064). A step costs 3.3-3.5 PIMPLE outer
correctors and about 490-560 GAMG iterations for p (the final corrector's absolute tolerance 1e-6, cells up to an
aspect ratio of 358 between the 0.2 D spanwise spacing and the wall layers): the pressure solve dominates.

## The run's estimate and the options

Steps per flow-through time at Co 1: about 834 (the validated 2D medium level ran 417 per t_c at Co 2 in its
developed flow, 28,352 steps over 82-150 t_c). Wall time at 8 processes, 15.9 s per step per million cells:

| Option | Steps | Estimate | What it does to the comparison |
|---|---|---|---|
| as set up: 0.81 M cells, 100 t_c, Co 1 | 83,380 | 298 h | none (the committed set-up) |
| Co 2 (PIMPLE) | 41,690 | 149 h | half the steps; Δt twice Spalart's guidance for the focus region (local CFL about 1) |
| end at 70 t_c (30 t_c sampled) | 58,366 | 209 h | about 4 shedding cycles, under the rule's minimum of 5 |
| Nz 10 (Δz = 0.4 D) | 83,380 | 149 h | half the spanwise resolution, below every LES grid of Table 1 (N_z 13-48) |
| Nz 10, Co 2, end 70 t_c | 29,183 | 52 h | all three compromises together |

None fits in 12 hours. What would: a cheaper pressure solve (a looser absolute tolerance or a relative one on the
final corrector, fewer outer correctors), which is a numerics change for the owner (QUESTIONS 261), or a much
smaller case (the 2D coarse section extruded in 10 cells: about 0.27 M cells, still about 20 h at Co 2 to 70 t_c).

## Ahmed 25° DDES on this machine (estimate)

From the same 15.9 s per step per million cells at 8 processes, with the vault note "1.1 URANS y DES" assumptions
(8-12 M cells, Δt 5e-5 s, 10 t_c of start-up and 20-40 t_c sampled; t_c = L / U = 1.044 m / 60 m/s = 0.0174 s):

| Cells | 10 + 20 t_c (10,440 steps) | 10 + 40 t_c (17,400 steps) | Memory at 8 processes (2.0 GB per M cells + 30 %) |
|---|---|---|---|
| 6 M | 276 h (11.5 days) | 460 h (19.2 days) | 16 GB |
| 8 M | 368 h (15.3 days) | 613 h (25.6 days) | 21 GB |
| 12 M | 552 h (23.0 days) | 920 h (38.3 days) | 31 GB |

Arithmetic: steps = (10 + sampled) t_c x 0.0174 s / 5e-5 s; hours = steps x 15.9 s x (cells / 1e6) / 3600. The note
estimated 1.5-3 days; the measured per-cell cost of this DDES set-up (PIMPLE with residual control, the GAMG solve
at 1e-6) is about 10 times what that estimate assumed. The memory fits (55 GB visible); the time does not.
