# Status

Updated 2026-10-19 (task/5.1-sizing: sizing defaults after the meshing baseline, and the owner review follow-up). Phases and sub-phases
are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/5.1-sizing** (not yet published; task/5.0-mesh-benchmark was merged in PR #19). Done on it:
- Part A (D-083): the Qt-free orchestration (meshing, solving, part_ops, mesh_study, polar_sweep) moved
  from gui/ to the new package vortexcfd/workflow/; bench/ imports nothing from gui/; gui/__init__.py
  imports MainWindow eagerly again.
- Part B (D-084, [NUMERICS-REVIEW]): confirmed that the seed lines attracted the wing's wall points
  (max deviation 2.664 mm with seeding, 1.849 mm without); seeded cases now castellate in a first
  snappyHexMesh run with the seed lines and snap / add layers in a second one without them.
- Part C (D-085, [NUMERICS-REVIEW], schema v10): the surface cell size comes from l_ref (warning when l_ref
  is automatic); curvatureLevel refinement up to 2 levels above each part's surface level; older projects
  keep L and no curvature (migration, v9 fixture).
- Part D (D-086, [NUMERICS-REVIEW]): new simulations use absolute layer sizing for y+ 50; relative mode
  disables the y+ field with a tooltip; older projects keep their layer settings.
- Part E (D-087): strict coverage is the benchmark's headline; full run against the baseline in
  benchmarks/RESULT_5.1.md: all meshes valid, y+ means 27.0 / 33.9 / 67.8 against the target 50, wing
  964,710 cells (over 500k) and the full run 1,477 s (over 12 min), not tuned; baseline.json unchanged.

Owner review of 5.1 (same branch): D-084, D-085 and D-086 accepted. Follow-up done:
- D-088 ([NUMERICS-REVIEW]): the y+ first layer takes Re on l_ref (L for projects made before schema v10).
- D-089: the Layers field is disabled with absolute sizing and shows the computed count.
- D-090: presets carry schema_version (file format 2); a preset written before v10 keeps the v9 mesh.
- D-091: fidelity in mm with its reference (the 5.1 comparison was like-for-like); layer diagnostics
  (mean / target, >= 80 % of target, no layer, area per count, the layer phase from the log).
- D-092: the benchmark wing is a 1.5 m half wing on a y_min symmetry plane; y+ runs on cells / 50,000
  cores (at most 10). One full run: 632 s, every mesh under 340k cells (benchmarks/RESULT_5.1b.md,
  benchmarks/baseline_candidate.json; baseline.json unchanged). Ahmed layers: half the wall within two
  layers of the 10-layer target, a third collapsed to 1-5 layers at the sharp edges (item 106).
- The slow and long tests touched in 5.1 were re-run and pass.

Next candidates: promoting baseline_candidate.json; 5.4 prism layers
(item 87); 5.2 surface preparation. Open: docs/QUESTIONS.md items 67, 69, 70, 71, 72, 73, 75, 82, 87,
89 to 92, 93, 94, 96, 97, 98 and 103 to 107.

## Phases

| Phase | Title | State |
|---|---|---|
| 0.1 | Commercial reference workflow inventory | done (feature map kept by the owner outside the repository) |
| 0.2 | Open-source landscape survey | done for geometry and meshing (docs/reference/oss_survey.md); other modules not surveyed |
| 0.3 | Repo, environment, architecture | done (no CI service: scripts/ship.sh runs the suite before publishing) |
| 1.1 | Simulation data model | done |
| 1.2 | Case writer | done for the cavity reference case; the cylinder and wing reference cases were not written |
| 1.3 | Runner and log parsing | done for serial and parallel (mpirun) runs; solver run states (D-046, D-063) |
| 1.4 | Headless integration test | done (cavity) |
| 2.1 | Main window | done |
| 2.2 | 3D viewer | done for parts, picking, visibility, the mesh scene and the results scene (scalar fields on walls and section) |
| 2.3 | Console and live monitors | done: console streams the solver log (crash block in the error colour), live residual chart (D-048, D-049) |
| 3.1 | Surface mesh import and checks | done: multi-solid STL, self-intersections (D-069) |
| 3.2 | CAD import (STEP/IGES/BREP) | done (D-070): OCP, face names and colours, assemblies, editable deflections |
| 3.3 | Geometry repair | done (D-072): pymeshfix + fTetWild envelope, before / after report |
| 3.4 | Domain and boundary definition | done; box, bullet and C-type shapes, Generate domain operation (D-078) |
| 3.5 | Surface-to-patch assignment | done (D-071): regions, angle split, patches in the meshing dictionary |
| 4.1 | Physics continua | done for steady incompressible RANS (merged in PR #13) |
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE); docs/reference/turbulence_mapping.md not written |
| 4.4 | Numerics presets | preset "robust" only (merged in PR #13) |
| 5.0 | Meshing benchmark suite | done (D-081, D-082): sphere, wing, Ahmed-type body; baseline in benchmarks/BASELINE.md; the dirty-STL set and solver convergence are not in it |
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing done (D-024, D-026, D-045); sizing defaults revised after the baseline (D-084 to D-086, task 5.1-sizing) |
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
| 9.1 | Project management | partly done: save/load, undo/redo, start screen, recent projects, project folders, presets (D-077); cloning not started |
| 9.2 | Scripting API | not started |
| 9.3 | Installer and docs | not started |

## Known issues

- Results at angle of attack != 0 are biased by the angled-inlet method with slip far field (QUESTIONS 71, open).

## Known debts

- GPU environment variables (GALLIUM_DRIVER=d3d12, MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA) are set in
  the user's ~/.bashrc; the app should set them at startup when they are not set.
- numpy is imported directly (geometry/checks.py, gui/scene.py, gui/viewport.py) but is not declared in
  pyproject.toml (it arrives through pyvista).
- Courant number: parsed from logs (foam/logparse.py) but no warning in the GUI.
- Parallel speedup saturates at about 3 on 8 cores (memory-bandwidth bound, docs/validation/parallel/README.md); the recommended-core cap of 4 is a constant for this machine (item 69).
- Location of user projects and run outputs in the released app (run/ is development only).
- Changing a CAD part's deflection re-tessellates from the CAD and drops an earlier repair (D-072).
- Preset boundary types are stored but there is one boundary type per role today (QUESTIONS 78, for the internal-flow task).
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today (curvature refinement is reported as its finest level, D-085).
- Per-part surface size (one target surface size for all parts today).
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
