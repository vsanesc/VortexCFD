# Status

Updated 2026-10-18 (task/qol-start-domain: start screen, presets, domain shapes). Phases and sub-phases are
those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/qol-start-domain** (not yet published; task/3-geometry was merged in PR #17). Done on it:
- Part A (D-077, schema v9): the app starts with no project (empty window, only File and Help active)
  and a Start dialog (New simulation, Open project..., the last 10 recent projects, missing ones greyed
  and removable); the New simulation dialog (name, parent folder, preset, parallel cores from the
  recommendation rule) creates <parent>/<name>/ with <name>.vcfd, geometry/ and case/ and saves at once;
  untitled projects and their temporary workspace are gone (core/workspace.py is core/save_rules.py,
  the save target rules kept); `Simulation.analysis_type` ("external" for older projects) and
  `preset_name`; presets (analysis type, domain, boundary type per role, mesh; never physics): built-in
  "External flow" and "Empty", user presets saved from the open project as JSON in the config folder,
  validated on load, renamed and deleted in Manage Presets.
- Part B (D-078): domain shapes box, bullet and C-type (closed surfaces with one region per role,
  within 0.22 % of the analytic volume); rounded shapes meshed by cutting a background box with the
  domain surface (createPatch removes the emptied background patch, a guard checks it); the "Empty"
  analysis has a Generate domain operation and every project a Fluid Region node; shape and sizes are
  undoable domain edits that make the mesh out of date; the viewer draws every shape as a wireframe and
  highlights the selected role. Coarse sphere meshes at the same base size: box 17,798 cells, bullet
  11,058, C-type 13,870, all checkMesh OK.

Next candidates: internal flow (mass-flow and total-pressure inlets; after the meshing phase), unsteady
runs (pimpleFoam), MRF rotating zones (PLAN 8.2), the meshing track (5.0 benchmark suite, 5.2 surface
preparation). Open: docs/QUESTIONS.md items 67, 69, 70, 71, 72, 73, 75 and 78 to 82 (80 is a
[NUMERICS-REVIEW] of the rounded domains).

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
- Save As into another folder writes only the project file; the geometry stays behind (QUESTIONS 79).
- Preset boundary types are stored but there is one boundary type per role today (QUESTIONS 78).
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today.
- Per-part surface size (one target surface size for all parts today).
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
