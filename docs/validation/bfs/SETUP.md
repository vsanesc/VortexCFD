# NASA TMR 2D backward-facing step: set-up

Task w3-internal, Part C (owner decisions I1-I5). The case is built by code (tests/validation/bfs_case.py) through the
app's workflow layer and run by scripts/validation/bfs_study.py (the Mesh Study node's StudyRun); the projects live
in run/validation/bfs/ (git-ignored); the numbers go to result.json, wall_<level>.csv and RESULT.md.

## References (read on 2026-10-22)

- NASA Turbulence Modeling Resource (TMR), "2DBFS: 2D Backward Facing Step",
  https://tmbwg.github.io/turbmodels/backstep_val.html (the TMR pages moved from turbmodels.larc.nasa.gov): Re based
  on the step height "approximately 36,000" (Re_theta 5000 before the step), "The boundary layer thickness prior to
  the step is approximately 1.5H", M = 0.128 "essentially incompressible", U_ref "the reference velocity at the
  center-channel near x/H=-4" (Cf and Cp "with respect to conditions near this location"), "x/Hreattach = 6.26 +-
  0.10" (Driver & Seegmiller, laser oil-flow interferometer); the inflow length "adjusted so that the naturally
  developing turbulent boundary layer on the lower wall ... grows to approximately the correct thickness"; the
  layout figure Backstep_validation/backstep_bcs.jpg: free-stream inflow, a symmetry strip on both sides before the
  walls start "at x=-110", adiabatic solid walls, "P specified in order to achieve M approx 0.128 near x/H=-4" at the
  outlet. Experiment: Driver, D. M. & Seegmiller, H. L., AIAA J. 23(2), 1985, pp. 163-171, doi:10.2514/3.8890.
- TMR grids (backstep_grids.html; Backstep_grids.zip from https://www.nasa.gov/wp-content/uploads/2026/02/backstep-grids.zip,
  backstep5_4levdn.p2dfmt and backstep5_1levdn.p2dfmt read here): the inflow plane x/H = -130, the upstream channel
  z/H = 1 to 9 up to the step at x = 0, the downstream channel z/H = 0 to 9, the outlet x/H = 50; the second-finest
  grid's first spacing 1.504e-4 H upstream and 1.480e-4 H downstream (y+ well below 1: the TMR solutions are
  wall-resolved; "the viscous near-wall region on the backside of the step is not resolved to within a y+ of 1").
- TMR, "2D Backward Facing Step - SSTm Model Results", https://tmbwg.github.io/turbmodels/backstep_val_sst.html: CFL3D
  and FUN3D, freestream turbulence intensity 0.061 %, nut / nu 0.009, the second-finest grid, "Reattachment is
  predicted by the SSTm model near x/H = 6.50"; "the SSTm model does not converge readily to a steady-state result
  ... when run time-accurately, the solution settles down and becomes reasonably steady". The SST Cf and Cp along
  the bottom wall are given only as plots (Backstep_validation/cf_sst-CF.jpg, cp_sst-CF.jpg); no data file: the
  comparison below reads them by eye and says so.
- Experimental data files from TMR, kept here unchanged: data/cf.exp.dat (bottom wall, "revised on 10/17/2015") and
  data/cp.expnew.dat ("revised on 2/28/2014"; the shifted column has Cp = 0 near x/H = 40).

## Inputs

| Input | Value | Source / deviation |
|---|---|---|
| Geometry | the TMR channel in the x-z plane with H = 1 m: walls from x/H = -110, upstream channel z/H 1-9, step at x = 0, downstream channel z/H 0-9, outlet at x/H = 50; built by code (`bench/internal_geometries.extruded_outline_solids`) as a closed slab 1 m across y, one solid per patch (inlet, lower, step, floor, outlet, upper; the end caps belong to "lower" and are outside the 2D slab) | TMR grids |
| Inflow | a uniform velocity inlet at x/H = -110, where TMR's walls start, with TMR's inflow turbulence: intensity 0.061 % and nut / nu 0.009 (the length scale set to 6.37e-4 m: nut = k^0.5 Cmu^0.25 L with the inlet's k); TMR: a free-stream inflow at x/H = -130 and a 20 H symmetry strip, which the app has no role for. The walls develop from the same station; the boundary layer at x/H = -4 is reported against the experiment (Cf; TMR: thickness about 1.5 H) | deviation (no symmetry role, D-129) |
| Outlet | static pressure 0 Pa at x/H = 50 (TMR: the back pressure for M = 0.128) | incompressible |
| Reynolds number | nu = 1/36,000 m2/s, U_ref target 1 m/s: the inlet speed 0.95 m/s so the centre-channel velocity at x/H = -4 (the core accelerated by the boundary layers' displacement) is close to U_ref; Re_H is reported from the run's own U_ref (probe "uref" at x/H = -4, z/H = 5) | TMR |
| Fluid | rho 1 kg/m3 (incompressible: Cf and Cp are independent of it) | |
| Analysis | internal flow, the "2D internal flow" preset (D-129): 2D section mode (D-121), wall-resolved y+ 1 at the first cell centre (D-122, D-123), first layer 1.318 mm (1.32e-3 H; the estimate with the inlet's bulk speed and D_h, D-129), two turbulence stages (D-126) | owner Part C2 (TMR's solutions are wall-resolved) |
| Turbulence | k-omega SST, fully turbulent | |
| Numerics | the app's set (D-022), first-order k and omega then the D-126 second stage | D-022, D-126 |
| Stopping | the app's mean-stable criterion (D-118), all of: the inlet-to-outlet total pressure loss (floor 1e-3 Pa) and the velocity at x/H = 6, z/H = 0.05 (probe "reatt", floor 0.01 m/s), each over two windows of 500 iterations within 0.5 %, not before iteration 2,000; limit 12,000 iterations (stage 2 from the switch, D-126) | TMR note on steadiness |
| Reattachment | x where Cf_x on the bottom wall (patch floor) changes from negative to positive the last time before x/H = 30, linear between face centres; Cf = -tau_x / (0.5 U_ref^2) (tau the wall's stress on the fluid, D-061), Cp = (p - p(x/H = 40)) / (0.5 rho U_ref^2) (TMR's shift) | |
| Cores | solver 8 ranks; meshing 1 (automatic) | |

## Grid study

The app's mesh study (D-066), ratio sqrt(2); in 2D every level keeps the current settings' staircase boxes (D-127's 2D
part) and grows its own wall-resolved stack from the same first layer (D-122). With the wall-resolved controls the
study placed the current settings as the coarse level (D-128: as the fine level the coarse level's surface cell, 0.516
H, would exceed the 220-first-layer limit, 0.290 H; the "2D internal flow" preset's 20,000 background cells on the
1,330 H^2 section give a base cell of 0.258 H). Planned (`plan.json`): surface cells 0.2579 H / 0.1823 H / 0.1289 H
(the whole fluid at the parts' level, D-129), about 46,000 / 89,000 / 175,000 cells, 21 / 19 / 17 layers from the
same first layer.

A refinement box over the step and the bubble (x/H -2 to 12, z/H 0 to 1.5, 0.05 H) was tried on the current settings
(mesh only) and left out: the floor's layers fell to 64 % of the stack and the step's to 9.6 of 21 layers, and the
non-orthogonality rose to 69 degrees (the plain mesh: 21 layers on every wall, 36 degrees).

A second, finer study family was run after the first (its levels moved x_r by about 0.4 H each): the same project with
160,000 background cells and "current settings are" medium (`bfs_case.FINE_FAMILY`, `bfs_study.py --family fine`),
levels 0.129 / 0.091 / 0.064 H; its coarse level is the first family's fine level.
