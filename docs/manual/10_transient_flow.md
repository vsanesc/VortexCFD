# 10. Transient flow (1.1, in progress)

Release 1.1 adds transient incompressible flow: pimpleFoam with k-ω SST (URANS), k-ω SST DDES (scale-resolving) or no
turbulence model (laminar). Steady flow stays the default. The reasons behind each behaviour are D-181 (transient),
D-182 (laminar) and D-185 to D-191 in DECISIONS.md.

## When to use it

Use a transient run when the flow is unsteady by nature and you need its time-averaged values or its frequency:

- vortex shedding behind bluff bodies (cylinders, blunt trailing edges, cables, masts) and its Strouhal number;
- a steady run whose monitors oscillate and never settle (the oscillation warning of chapter 7 says "the flow may
  be unsteady"): the transient run's means are the answer a steady run cannot give;
- low-Reynolds-number flows that are laminar and periodic (choose Laminar in Physics).

Keep steady flow for attached flow and for mildly separated flow whose steady solution converges: it is much
cheaper. URANS with k-ω SST resolves only the large, organised unsteadiness (shedding); it is not a scale-resolving
method.

## Setting it up

1. Physics > Flow: **Incompressible, transient**. Physics > Turbulence model: k-ω SST, or **Laminar** for a low
   Reynolds number (a circular cylinder sheds laminar up to Re of about 190), or **k-ω SST DDES** (below). A laminar
   project has no y+ to target: its Mesh node shows **First-cell thickness** instead of Target y+ (Auto: 0.1
   √(ν L / U), about ten layers inside the laminar boundary layer), or use relative layers.
2. Solvers shows a **Transient** section instead of the iteration settings. The times are in **flow-through times**
   by default: t_c = l_ref / U, the time the free stream takes to pass the reference length (shown as
   "Flow-through time"; Reference Values > l_ref sets the length). Choose seconds in "Times in" if you prefer:
   the times already entered are converted (one undo step).
3. Generate the mesh as usual and Run Solver (it runs pimpleFoam; the log is log.pimpleFoam).

## The time step and the Courant number

The Courant number Co = U Δt / Δx is how many cells a fluid particle crosses in one time step. With
**Time step: Adaptive** (the default) pimpleFoam sets every step so that the largest Courant number in the mesh is
**Max Courant number** (Auto: 1 with PISO and DDES, 2 with PIMPLE): small cells near the walls set the step. The step never grows above the
**Largest time step** (auto: t_c / 50, at least 250 steps per shedding period at St 0.2), and the first step is cut
at once to the Courant limit. With **Fixed** the step is what you set, whatever the Courant number.

**Pressure-velocity coupling**: **PISO** solves each step once (one outer corrector) and needs a Courant number up to
about 1; **PIMPLE** solves the step again (outer correctors) until the initial residual of U (and k, ω) is below the
**Outer tolerance** (default 1e-4, at most **Most outer correctors**, default 10), so the step can run at a Courant
number of 2 to 5. **Auto** (the default) is PISO for a laminar project and PIMPLE for a turbulent one, whose wall
layers make Courant-1 steps tiny. PIMPLE is not always cheaper: on the laminar cylinder it needed 3 outer correctors
per step and saved nothing (docs/validation/cylinder_re100/RESULT.md, "Part 2"); the larger step pays off where the
thinnest cells, not the wake, set the Courant limit. A large Courant number resolves less of the unsteadiness, and
the largest time step (auto t_c / 50) may cap it. **Pressure correctors** (default 2) is the tutorials' value.

The schemes are second order in time (backward) and space (linearUpwind for U, a bounded TVD scheme for k and ω).

## The sampling window

The statistics (averaged fields, mean and RMS of the coefficients, the Strouhal number) must leave out the start-up
transient: the flow develops from the free stream (or from a steady solution, "Start from") before it settles into
its statistically steady state.

- **Start-up perturbation** (external flow, on by default): for the first 10 flow-through times the inflow swings
  by ±10° towards the lift direction at 0.2 U / l_ref, then flows along +x. It breaks the symmetry of the start, so a
  symmetric body sheds within a few tens of flow-through times instead of over a hundred (the cylinder at Re 100:
  3 sampled cycles after 226 s instead of 345 s on 4 cores). The sampling never starts before it has ended.
- **Sampling starts at: Auto** (the default): the app watches the force history and starts the sampling once the
  start-up is over: over two consecutive **windows**, the mean of the stop quantity (Cd by default) changes by less
  than the **tolerance** and the ranges of Cd and Cl by less than the **Start-up detection tolerance** (default 5 %;
  larger starts sooner, on a less settled flow). It then stops the solver for a moment, adds the
  field averaging and continues from the same time (the console says "Start-up transient over at t = ..."). The
  window (default 20 flow-through times) must hold a few periods of the slowest oscillation.
- Or set the start by hand (uncheck Auto in "Sampling starts at" and give a time): the averaging starts there and
  nothing is detected.

## The end of the run

The run ends at the **End time**. With **Stop when statistically converged** it also ends once the running mean of
the chosen coefficient (from the sampling start) has varied by at most the tolerance over the last window: the
mean is then known to that accuracy. The banner says which ended the run.

## Reading the results

- **Monitors**: the residuals are plotted against time. Each report slot shows the latest value and, under it, the
  running mean and the RMS from the sampling start ("start-up: sampling not started" before it). The convergence
  box shows the time reached, the phase (start-up or sampling) and, once sampling, the statistics: the sampling
  window, each coefficient's mean and RMS (with min and max) and the Strouhal number.
- **Report charts** (the slot's ↗): the instantaneous history against time with the running mean dashed; Export CSV
  gives time, value and running mean.
- **The Strouhal number** St = f l_ref / U, f the dominant frequency of the lift. It needs several cycles in the
  sampling window: below 3 the app warns ("sample longer"). For a cylinder l_ref must be the diameter.
- **RMS** is the root mean square of the fluctuation about the mean (for the lift, whose mean is zero, the RMS of the
  lift itself). Every statistic is time-weighted (the steps vary).
- **Results Scene**: the averaged fields are in the field list once the averaging has written them: p mean, Cp mean,
  |U mean| and its components, p RMS and the Ux, Uy, Uz RMS. The time selector (shown when several times are
  written) chooses a written time; the latest is the default and holds the averages over the whole sampling window.
  The live view and Write Fields Now work as in a steady run, labelled with the time.
- **Snapshots, Compare and the HTML report** carry the sampling means, the RMS and the Strouhal number.

## Continuing a transient run

A transient run that was stopped, reached its end time or met the statistics stop can go on: **Continue Solver**
asks for the new end time and runs from the latest written time. The field averages and the statistics go on from
the same sampling start (the averages written at that time are read back), and a start-up not yet over is still
detected. Only how far the run goes and how it is sampled may change (the end time, the write interval, the
statistics stop, the sampling start, the detection tolerance); any other change (time stepping, schemes, physics,
boundaries) can only start over. If the start-up was never detected (a flow whose amplitude keeps changing), set
"Sampling starts at" by hand and continue: the statistics are taken from that time over the whole history, the
averaged fields from the restart on.

## DDES (detached-eddy simulation)

**k-ω SST DDES** (Physics > Turbulence model; transient and 3D only) keeps RANS in the attached boundary layers and
resolves the large eddies (LES) where the flow has separated. It is much dearer than URANS and needs:

- a **focus region**: a refinement volume around the body and its near wake with nearly cubic cells. The Physics node
  warns when there is none, when its cell is coarser than 0.068 l_ref, or when it holds fewer than 32 cells across
  (Spalart, "Young-person's guide to detached-eddy simulation grids", NASA/CR-2001-211032);
- a Courant number about 1 there (Auto with DDES: PIMPLE at Co 1);
- a long average (the Physics node recommends at least 50 flow-through times after the start-up).

Settings (Physics, shown with DDES): the length scale **Δ** (Δω̃, the default of the OpenFOAM tutorial
wallMountedHump; the cube root of the volume; the largest cell side), the **σ variant** in the LES region (on) and
the **U convection** (DEShybrid, LUST where the LES region is resolved and linearUpwind elsewhere, the default; or
LUST everywhere). The Results Scene
offers the **DDES shielding function f_d** (near 0 in the RANS-shielded boundary layer) and the **LES region** (1
where the model is in LES mode) at the written times: check that the boundary layers stay RANS and the wake is LES.

## Not in this part of 1.1

The mesh study and the polar sweep of a transient project and the Ahmed body (docs/STATUS.md).

## Validation

The circular cylinder at Re 100 (laminar, 2D): docs/validation/cylinder_re100/RESULT.md. The square cylinder at
Re 22,000 (URANS, 2D) and the DDES functional run: docs/validation/square_re22000/ and docs/validation/ddes_sphere/.
