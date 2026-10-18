# Status

Updated 2026-10-18 (task/3-geometry: Phase 3 geometry done). Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/3-geometry** (not yet published). Done on it:
- Part 0 (D-068): display guard (tests and scripts/screenshots.py run offscreen on the WSLg
  display unless VORTEXCFD_ALLOW_REAL_DISPLAY=1) and the targeted testing rule in CLAUDE.md. The
  Task 0.1 feature inventory is kept by the owner outside the repository.
- Part A, Task 3.1 missing items (D-069, schema v8): multi-solid ASCII STL import (one part with a
  region per solid, the default, or one part per solid); self-intersection check (own numpy code:
  pymeshfix's selection returns garbage indices, item 75) with a Checks row and the triangles
  highlighted in the viewer; 1,005,360 triangles in 7.3-7.9 s, skipped above 2M triangles.
- Part B, Task 3.2 (D-070): OCP spike passed (cadquery-ocp-novtk 8.0.1.1.0 next to VTK 9.7.1, no
  conflict); File > Import Geometry reads STEP/IGES/BREP with face names, colours and assemblies;
  tessellation per part with editable linear / angular deflection (cached files, one undo step).
- Part C, Task 3.3 (D-072): Edit > Repair part: pymeshfix with a fidelity check, fTetWild
  envelope fallback, new file version, before / after report; the four broken test surfaces
  (holes, flipped patch, duplicated faces, self-intersection) all end snappy-ready.
- Part D, Task 3.5 (D-071): regions from CAD faces, STL solids or an angle split; rename, merge,
  split, patch assignment (list and viewer picking); one snappyHexMesh region and wall patch per
  patch, lost-part guard per patch; real two-patch cube mesh: front 724 and body 3,888 faces.

- Follow-up (D-073, D-074): CAD reading / tessellation, re-tessellation, self-intersection checks
  and repair run on background threads; per-part forces sum all of a part's patches (checked on a
  real run); THIRD_PARTY_LICENSES.md; pymeshfix kept; repair report shows the fidelity metrics.

Next candidates: unsteady runs (pimpleFoam), MRF rotating zones (PLAN 8.2), the meshing track
(5.0 benchmark suite, 5.2 surface preparation). Open: docs/QUESTIONS.md items 67, 69, 70, 71, 72,
73 and 75 (pymeshfix's broken self-intersection selection).

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
| 3.4 | Domain and boundary definition | done |
| 3.5 | Surface-to-patch assignment | done (D-071): regions, angle split, patches in the meshing dictionary |
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
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today.
- Per-part surface size (one target surface size for all parts today).
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
