# Status

Updated 2026-10-18 (task/6.4-studies: Tasks 6.4 and 6.5 done). Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/6.4-studies** (not yet published; Tasks 6.1 and 6.6 were merged in PR #15). Done on it:
- Part A (D-064, D-043 updated, D-063 Accepted): marker `long` for real runs above 60 s (skipped
  unless `-m long`; scripts/ship.sh runs `-m "not validation and not long"`), ship suite 963 s ->
  379 s single-process offscreen (not under 3 min: docs/QUESTIONS.md item 70); `.gitignore` keeps
  `log.*` except `tests/data/**/log.*` (tests/data/sphere_run/log.simpleFoam is read by a test and
  is now tracked); speedup study on a 990k-cell sphere (docs/validation/parallel/README.md): 3.0 at
  8 cores, efficiency >= 0.5 only up to 4 ranks, `--bind-to core` not clearly better, Open MPI's
  default kept; the Solvers node shows the recommended cores min(physical, cells / 50,000, 4).

- Part B (freestream far field) STOPPED at the validation step, not applied (docs/QUESTIONS.md
  item 71, docs/notes/freestream_far_field.md and .patch): at alpha 10 deg the freestream far field
  raises Cl of the flattened ellipsoid from 0.041 to about 0.068 but the run oscillates; the flat
  plate validation could not reach its verdict (medium Case B grid stalled, coarse Cf -0.60 %). The
  app keeps the slip far field of D-022.

- Part C, Task 6.4 (D-066, schema v7): foam/gci.py (Celik 2008, checked against the paper's worked
  example; oscillatory, divergent and undefined cases get no GCI); a Mesh Study node under Reports &
  Monitors (ratio, current settings as fine or medium, quantities, cores; estimated cells and time
  per level; the same absolute prism-layer stack on every level); levels in case_study/level_<n>/,
  each judged by the stopping criteria (unreliable GCI otherwise); results window (GCI table, levels,
  value against h, CSV) and case_study/study.json. Real study on the coarse sphere at Re 200: all
  levels met the criteria; Cd divergent and Cl oscillatory (not in the asymptotic range; actual h
  ratios 1.31 and 1.33, docs/QUESTIONS.md item 72).

- Part D, Task 6.5 (D-067): a Polar Sweep node (range or list of angles, cores, initialise from the
  previous converged point); points in case_sweep/point_<n>/ on the current mesh, each judged by the
  stopping criteria (flagged otherwise); results window (table, CL-alpha, drag polar, CM-alpha with
  hollow flagged points, CSV) and case_sweep/sweep.json. Real sweep of the flattened ellipsoid at 0,
  5, 10 deg: CL -0.0002, 0.0233, 0.0408, all criteria met.

Tasks 6.4 and 6.5 are complete on this branch (Part B, the freestream far field, was stopped at
the validation step and waits for review). Next candidates: unsteady runs (pimpleFoam), MRF
rotating zones for propellers (PLAN 8.2), STEP import (PLAN 3.2), STL repair (PLAN 3.3). Open: docs/QUESTIONS.md items 67 (an
offscreen worker crash), 69 (the core cap), 70 (ship suite time), 71 (freestream far field), 72
(actual refinement ratio), 73 (an intermittent offscreen test).

## Phases

| Phase | Title | State |
|---|---|---|
| 0.1 | STAR-CCM+ reference inventory | not started |
| 0.2 | Open-source landscape survey | done for geometry and meshing (docs/reference/oss_survey.md); other modules not surveyed |
| 0.3 | Repo, environment, architecture | done (no CI service: scripts/ship.sh runs the suite before publishing) |
| 1.1 | Simulation data model | done |
| 1.2 | Case writer | done for the cavity reference case; the cylinder and wing reference cases were not written |
| 1.3 | Runner and log parsing | done for serial and parallel (mpirun) runs; solver run states (D-046, D-063) |
| 1.4 | Headless integration test | done (cavity) |
| 2.1 | Main window | done |
| 2.2 | 3D viewer | done for parts, picking, visibility, the mesh scene and the results scene (scalar fields on walls and section) |
| 2.3 | Console and live monitors | done: console streams the solver log (crash block in the error colour), live residual chart (D-048, D-049) |
| 3.1 | Surface mesh import and checks | done (self-intersections not detected) |
| 3.2 | CAD import (STEP/IGES/BREP) | not started (spike pending) |
| 3.3 | Geometry repair | not started |
| 3.4 | Domain and boundary definition | done |
| 3.5 | Surface-to-patch assignment | not started (one patch per part) |
| 4.1 | Physics continua | done for steady incompressible RANS (merged in PR #13) |
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE); docs/reference/turbulence_mapping.md not written |
| 4.4 | Numerics presets | preset "robust" only (merged in PR #13) |
| 5.0 | Meshing benchmark suite | not started |
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing done (D-024, D-026, D-045) |
| 5.2 | M2: surface preparation | not started |
| 5.3 | M3: alternative volume mesher | not started (cfMesh build spike pending) |
| 5.4 | M4: prism layer robustness | not started |
| 5.5 | M5: own mesher (go/no-go) | not started |
| 6.1 | Monitors and reports | done: report slots with Cd, Cl, Cm pitch and wall y+ (D-048); reference values (D-047); stopping criteria (runTimeControl for residuals, app-side range-based asymptotic criterion), convergence banner and oscillation warning (D-058, D-059); force breakdown, body-axis x_cp, mass balance, cellPoint probes (D-060) |
| 6.2 | Scenes and derived parts | Cp along wall sections with CSV export (D-062); Cf / Cf_x and separation highlight (D-061); scalar scenes done (D-053): field/colormap/range selection, scalar bar, section; scene saving, image export, iso-surfaces and streamlines not started |
| 6.3 | Data export and reports | not started (section CSV export only, D-062) |
| 6.4 | Mesh independence study (GCI) | done (D-066): Mesh Study node, three levels, Celik GCI, results window and CSV; flat plate Case B not reproduced through the workflow (item 72) |
| 6.5 | Angle-of-attack sweep (polars) | done (D-067): Polar Sweep node, points on the current mesh initialised from the previous converged point, CL-alpha / drag polar / CM-alpha, CSV; NACA 0012 check waits for the wing case |
| 6.6 | Parallel runs (mpirun) | done (D-063 Accepted): decomposePar / mpirun / reconstructPar, clean stop through mpirun; speedup study and recommended cores (D-064) |
| 7.1-7.3 | Coupled solver analysis | not started |
| 8.1-8.5 | Moving meshes | not started |
| 9.1 | Project management | partly done (save/load, undo/redo); templates, recent projects, cloning not started |
| 9.2 | Scripting API | not started |
| 9.3 | Installer and docs | not started |

## Known debts

- GPU environment variables (GALLIUM_DRIVER=d3d12, MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA) are set in
  the user's ~/.bashrc; the app should set them at startup when they are not set.
- numpy is imported directly (geometry/checks.py, gui/scene.py, gui/viewport.py) but is not declared in
  pyproject.toml (it arrives through pyvista).
- Courant number: parsed from logs (foam/logparse.py) but no warning in the GUI.
- Parallel speedup saturates at about 3 on 8 cores (memory-bandwidth bound, docs/validation/parallel/README.md); the recommended-core cap of 4 is a constant for this machine (item 69).
- Location of user projects and run outputs in the released app (run/ is development only).
- STEP import spike: OCP novtk wheel next to PyVista's VTK (docs/reference/oss_survey.md).
- STL repair: pymeshfix (wrapper licence to confirm) / pytetwild.
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today.
- Per-part surface size (one target surface size for all parts today).
- Task 0.1 (STAR-CCM+ feature inventory) not done.
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
