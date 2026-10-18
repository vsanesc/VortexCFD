# Status

Updated 2026-10-18 (Task 6.1 review fixes, Task 6.6). Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/6.1-monitors** (not yet published; Task 6.2 was merged in PR #14). Done on it:
- Part A (D-058, D-059; schema v6): stopping criteria under Solvers (residual and asymptotic criteria,
  "all"/"any", minimum iterations; the iteration limit always applies); a Stopping Criteria node;
  a convergence banner and a per-criterion table (value, threshold, satisfied) in the monitors
  column; the oscillation warning.
- Part B (D-060, D-061): Cd and Cl split into pressure and viscous parts per part and in total, Cm,
  centre of pressure, mass balance (warning above 0.1 %), probes (reports and asymptotic criteria),
  wallShearStress written at write times, Cf and Cf_x in the Results Scene with a separation
  highlight, and the y+ histogram on the Reports & Monitors node.
- Part C (D-062): Sections tool in the Results Scene: Cp against x/c on y or z wall sections (one position
  or N stations), two branches per loop, CSV export.
- Review fixes (2026-10-18, D-058 to D-062 Accepted; docs/QUESTIONS.md items 60-65 closed): the
  asymptotic criterion is (max - min) / max(|mean|, floor) over the window, evaluated by the app,
  which stops the solver with the clean stop (residual-only criteria keep runTimeControl); the
  oscillation check uses the same normalisation; the end state is "Criteria met: <names>" (old
  records migrated); x_cp in body axes with a 1e-3 threshold; probes interpolated with cellPoint;
  sections ordered along the cut and split at min/max x. Real run: Cd (window 20, 2 %) met at
  iteration 144 on the coarse sphere, run ended cleanly at 146.

- Task 6.6 (D-063, Proposed): parallel solver runs: `Solvers.cores` (limited to the physical cores
  at run time), decomposePar -force (scotch), mpirun -np N simpleFoam -parallel, reconstructPar
  -latestTime (also after a clean stop); SIGUSR1 to mpirun stops all ranks cleanly (Open MPI
  forwards it); timeout and escalation kill the whole session. Serial and 4 cores agree on the
  converged low-Re sphere (dCd 5e-7, dCl 1.6e-4 relative; speedup 2.0); on the oscillating 20 m/s
  sphere they do not (docs/QUESTIONS.md item 66).

Tasks 6.1 and 6.6 are complete on this branch. Next steps (docs/PLAN.md): 6.4 mesh independence
study with the GCI, then 6.5 angle-of-attack sweep (polars), which can use the parallel runs.
Open: docs/QUESTIONS.md items 66 (serial / parallel acceptance, speedup), 67 (an offscreen worker
crash) and 68 (fixture logs ignored by .gitignore).

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
| 6.4 | Mesh independence study (GCI) | not started |
| 6.5 | Angle-of-attack sweep (polars) | not started |
| 6.6 | Parallel runs (mpirun) | done (D-063, Proposed): decomposePar / mpirun / reconstructPar, clean stop through mpirun |
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
- Parallel speedup only 2.0 on 4 cores for the 192k-cell sphere (process binding not tried, item 66).
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
