# Status

Updated 2026-10-20 (task/5.4-layers: prism-layer robustness).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/5.4-layers** (not yet published). Done on it (benchmarks/RESULT_5.4.md):
- Part 0: QUESTIONS 137 closed, D-104 Accepted (renderer "D3D12 (NVIDIA GeForce RTX 3080 Ti)").
- Part A (D-105): the benchmark's layer headline is counted from the mesh, snappyHexMesh's figure beside it,
  hard / soft checkMesh failures per case; starting point benchmarks/baseline_5.4_start.json.
- Part B: diagnosis. The `relaxed` set disables the tet-quality check for the whole layer phase (minTetQuality
  -1e30 from iteration 0, D-045); the aircraft's hard failures come from a failed shrink two cells off the wing
  (the tet check off lets the layer iterations reach it); on the public cases feature-angle termination is the
  dominant collapse mechanism.
- Part C: one-factor study of 30 variants and 5 combined candidates on the half wing, the Ahmed body, the
  aircraft and the sphere (50.5 min of the 75.8 min of runs in the session).
- Part D (D-106, [NUMERICS-REVIEW], schema v13): for y+ layers, a layer cap of 12 with the expansion ratio raised
  up to 1.3 to keep the planned stack (planned / achievable thickness and a warning in the Mesh properties),
  layer featureAngle 130 and nOuterIter 3; projects and presets saved before keep "legacy" controls (fixture
  tests/data/project_v12.json); the slow tests written for the old controls pinned to them (not run).
- Part E: half wing 76.8 -> 95.9 %, Ahmed body 31.1 -> 97.4 % strict coverage, every case without hard
  failures, the aircraft valid (3 -> 0 hard failures) but at 0.0 % strict coverage and an indicative y+ mean of
  619. benchmarks/baseline_candidate.json for the owner (baseline.json unchanged).

Left for later: the aircraft's coverage and y+ (QUESTIONS 141), the y+ band convention (142), feature edges
with normals (124), the junction layers (122), nOuterIter's cost on large stacks (140).

Next candidates: owner review of D-105 / D-106; drag handles for the refinement volumes (item 132). Open:
docs/QUESTIONS.md items 30, 67, 69, 70, 71, 72, 73, 75, 82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131
and 138 to 146.

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
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing done (D-024, D-026, D-045); sizing defaults revised after the baseline (D-084 to D-086, task 5.1-sizing); user refinement volumes and the wake helper (D-103, task 5.x-refinement-volumes; no viewer drag handles) |
| 5.2 | M2: surface preparation | first step done (D-093, D-094): Surface Preparation operation (diagnostics, intersection features, CAD union), local benchmark cases with fidelity against a reference; no shell wrapper; dirty-STL set not in the benchmark |
| 5.3 | M3: alternative volume mesher | cfMesh evaluated (D-102, benchmarks/RESULT_5.3.md): recommendation keep snappyHexMesh, owner decision pending (QUESTIONS 130); benchmark-only `--mesher cfmesh`; Gmsh not evaluated |
| 5.4 | M4: prism layer robustness | first step done (D-105, D-106, benchmarks/RESULT_5.4.md): robust y+ layer defaults (cap 12, ratio up to 1.3, featureAngle 130, nOuterIter 3); half wing and Ahmed body above 85 % strict coverage, aircraft valid but not covered |
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
