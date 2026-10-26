# 10. Transient flow (1.1, in progress)

Release 1.1 adds transient incompressible flow: pimpleFoam with k-ω SST (URANS) or no turbulence model (laminar).
Steady flow stays the default. The reasons behind each behaviour are D-181 (transient) and D-182 (laminar) in
DECISIONS.md.

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
   Reynolds number (a circular cylinder sheds laminar up to Re of about 190). For a laminar project use relative
   prism layers (Mesh > Layer sizing): the y+ sizing assumes a turbulent boundary layer.
2. Solvers shows a **Transient** section instead of the iteration settings. The times are in **flow-through times**
   by default: t_c = l_ref / U, the time the free stream takes to pass the reference length (shown as
   "Flow-through time"; Reference Values > l_ref sets the length). Choose seconds in "Times in" if you prefer;
   changing the unit does not convert the values.
3. Generate the mesh as usual and Run Solver (it runs pimpleFoam; the log is log.pimpleFoam).

## The time step and the Courant number

The Courant number Co = U Δt / Δx is how many cells a fluid particle crosses in one time step. With
**Time step: Adaptive** (the default) pimpleFoam sets every step so that the largest Courant number in the mesh is
**Max Courant number** (default 1): small cells near the walls set the step. The step never grows above the
**Largest time step** (auto: t_c / 50, at least 250 steps per shedding period at St 0.2), and the first step is cut
at once to the Courant limit. With **Fixed** the step is what you set, whatever the Courant number.

**Outer correctors** (default 1, the PISO mode) are enough at a Courant number up to about 1. Above that, raise them
(2 to 5): each solves the step again, so the cost grows with them, and a large Courant number resolves less of the
unsteadiness anyway. **Pressure correctors** (default 2) is the tutorials' value.

The schemes are second order in time (backward) and space (linearUpwind for U, a bounded TVD scheme for k and ω).

## The sampling window

The statistics (averaged fields, mean and RMS of the coefficients, the Strouhal number) must leave out the start-up
transient: the flow develops from the free stream (or from a steady solution, "Start from") before it settles into
its statistically steady state.

- **Sampling starts at: Auto** (the default): the app watches the force history and starts the sampling once the
  start-up is over: over two consecutive **windows**, the mean of the stop quantity (Cd by default) changes by less
  than the **tolerance** and the ranges of Cd and Cl by less than 5 %. It then stops the solver for a moment, adds the
  field averaging and continues from the same time (the console says "Start-up transient over at t = ..."). The
  window (default 20 flow-through times) must hold a few periods of the slowest oscillation.
- Or set a time: the averaging starts there from the beginning of the run.

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

## Not in this part of 1.1

Continuing a transient run, the mesh study and the polar sweep of a transient project, DDES and the Ahmed body
(docs/STATUS.md). A transient solution starts from the beginning each time.

## Validation

The circular cylinder at Re 100 (laminar, 2D): docs/validation/cylinder_re100/RESULT.md.
