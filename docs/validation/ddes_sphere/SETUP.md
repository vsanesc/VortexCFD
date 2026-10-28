# DDES functional run: a sphere at Re 10,000 (no verdict)

> **DDES is experimental and not validated in 1.1 (D-197).** This is a functional run with no pass rule. No result here is a validation. The Ahmed DDES
> and the choice of a DDES validation case are in "Later" (docs/PLAN.md, QUESTIONS 261).

Task 1.1-transient, Part 2, Part B (3b). Written before the run.

## Why a functional run

The DDES cases of the vault note "1.1 URANS y DES" with a published reference do not fit the about 12 hours of
machine time of this part: the NASA wall-mounted hump (its case 1.1-d) is estimated there at about a day per variant
(the v2606 tutorial: 1-3 M cells, Δt 1 ms, 30 s of simulation, 30,000 steps) and needs an inflow boundary layer the
app cannot set yet; the Ahmed body (1.1-e) is out of this task; the cylinder at Re 3900 (1.1-f) is "days". So this is
a functional run with no pass rule: it shows that a DDES project set up through the app runs, writes the shielding
function and the LES-region indicator, and measures the cost per cell and time step for the Ahmed estimate. The
hump is proposed for Part 3 (QUESTIONS).

## Case

| Item | Value |
|---|---|
| Geometry | sphere of diameter D = 1 m (a 180 x 90 triangulated sphere), 3D |
| Flow | U = 1 m/s, nu = 1e-4 m²/s: Re = 10,000; k-omega SST DDES (Δω̃, σ variant, DEShybrid: the app's defaults, D-191) |
| Domain and mesh | the "External flow" preset's domain and mesh (y+ sizing, wall functions) plus a focus box from 0.5 D ahead of the sphere to 2.75 D behind it, 2 D wide and high, at 0.05 D (D/20, finer than the 0.068 D of the coarser cylinder grid in Spalart, NASA/CR-2001-211032, 40 cells across its smallest extent) |
| Run | PIMPLE at Co 1 (the DDES default), the start-up perturbation: the inflow swing (±10° at 0.2 U / D for 10 t_c; declared since D-198, the driver sets it), the sampling set at 15 t_c, end 40 t_c; 8 cores, nice 15 |

## What is recorded

The mesh (cells, the app's DDES mesh warning), the solve (steps, Courant number, the statistics from 15 t_c), the
written fields turbulenceProperties:fd and turbulenceProperties:LESRegion (their ranges and the share of LES cells),
the cost (wall seconds per step, microseconds per cell and step on 8 cores and per core, the peak resident memory of
the solver processes) and from it the estimate of an Ahmed DDES on this machine.

## Amendment (during the run, before any statistics)

At 1.06 t_c the run had taken 1,152 s on 4 cores (about 4.1 s per step at Co 1): 40 t_c would take about 12 hours,
over this part's machine time. The end time was cut to 25 t_c (10 t_c sampled from 15 t_c) by editing the running
case's controlDict (endTime 25, writeInterval 5; OpenFOAM re-reads it) and system/transientControl.

