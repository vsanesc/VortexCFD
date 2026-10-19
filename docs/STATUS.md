# Status

Updated 2026-10-19 (task/5.2-surface-prep: surface preparation of multi-component models). Phases and
sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/5.2-surface-prep** (not yet published; task/5.1-sizing was merged in PR #20). Done on it:
- Part A (D-094): optional local-only benchmark cases from the git-ignored benchmarks/local_cases.json
  (format in local_cases.example.json; projects outside the repository); a reference analysis (outer
  skin, intersection-curve zones, mean chord as l_ref) and fidelity against it in both directions,
  the wall left inside a component, patch faces and the per-part force partition.
- Part B: the owner's aircraft through the current pipeline (benchmarks/RESULT_5.2_before.md): the
  untrimmed export imports as six compounds of loose (sewable) faces; no check looks across parts;
  the repair is per part (and loses the wings on a one-part import); the trimmed export is four
  overlapping solids, not one skin (QUESTIONS 108).
- Part C (D-093, [NUMERICS-REVIEW], schema v11): the Surface Preparation operation (tree node, Edit >
  Prepare Surfaces, background worker, undoable, stale results block meshing): diagnostics,
  "intersection_features" (crossing curves as snap features) and "cad_union" (sew, fuse, per-part
  shares of the outer skin with their CAD faces; per-part fallback).
- Part D: comparison (benchmarks/RESULT_5.2.md): CAD union is closest to the reference at the
  junctions and leaves the least internal wall; proposed as the default (QUESTIONS 109). Every
  aircraft mesh fails checkMesh at the 24-layer stack (QUESTIONS 111, input for 5.4). Public benchmark
  re-run against baseline.json: no regressions, identical meshes (599 s).

Owner review of 5.2 (same branch): CAD union accepted as the default (D-093 and D-094 Accepted;
QUESTIONS 108-110, 112, 113, 115-118 accepted). Follow-up done:
- D-095: the ~/case and ~/geometry folders of 2026-10-18 came from the old save-first import (the
  project file was saved in the home folder); no path is built from the working directory; regression
  test.
- D-096 ([NUMERICS-REVIEW]): a mesh that fails checkMesh blocks Run Solver and the polar sweep (it did
  not before), with the failed checks in the tooltip and the Mesh report.
- D-097 ([NUMERICS-REVIEW]): intersection features did nothing because the junction curves refined to
  level 5 where the cells were already at level 7; the junction level is now the maximum surface level
  plus the curvature levels. Re-measured: the junctions' reference -> mesh RMS about halves against no
  preparation (benchmarks/RESULT_5.2.md); intersection features stay the CAD union's fallback.
- D-098: CAD component names from the STEP entities (the aircraft: Fuselage_0, Ala_0, ...).
- D-099: the import checks report parts that cross each other and point to Surface Preparation.

Next candidates: 5.4 prism layers (items 87, 106, 111, 122); the CAD union's junction level (item
121); a dirty-STL set for 5.2. Open: docs/QUESTIONS.md items 30, 67, 69, 70, 71, 72, 73, 75, 82, 87,
89 to 94, 96, 97, 106, 111 and 119 to 124.

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
| 5.2 | M2: surface preparation | first step done (D-093, D-094): Surface Preparation operation (diagnostics, intersection features, CAD union), local benchmark cases with fidelity against a reference; no shell wrapper; dirty-STL set not in the benchmark |
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
