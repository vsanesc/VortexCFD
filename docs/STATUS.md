# Status

Updated 2026-10-17. Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/4a-physics** (not yet published). Task 4A is **done**: physics model and schema v3 with editors,
solver case files (D-022, D-023), y+ estimator (D-024), layer count from y+ (D-026), residual control
(D-027), flat plate verification against TMR (PASS WITH NOTE, -3.3 %, D-036), minTetQuality relaxed only
in `relaxed` (D-044) with the relaxed controls used from the first layer iteration for y+ layers
(D-045: the y+ 30 sphere gets 100 % layer coverage, Mesh OK). D-022, D-023, D-024 and D-027 were
accepted in the review chat on 2026-10-17. Full flat plate study in scripts/validation/flat_plate_study.py
(about 80 min); the pytest `validation` test runs the coarse and medium grids (about 20 min).

Next on it: Task 4B (run the solver from the GUI, reference values, live residuals, report slots).

## Phases

| Phase | Title | State |
|---|---|---|
| 0.1 | STAR-CCM+ reference inventory | not started |
| 0.2 | Open-source landscape survey | done for geometry and meshing (docs/reference/oss_survey.md); other modules not surveyed |
| 0.3 | Repo, environment, architecture | done (no CI service: scripts/ship.sh runs the suite before publishing) |
| 1.1 | Simulation data model | done |
| 1.2 | Case writer | done for the cavity reference case; the cylinder and wing reference cases were not written |
| 1.3 | Runner and log parsing | done for single-process runs (parallel not supported) |
| 1.4 | Headless integration test | done (cavity) |
| 2.1 | Main window | done |
| 2.2 | 3D viewer | done for parts, picking, visibility and the mesh scene; scalar fields not started |
| 2.3 | Console and live monitors | console done; residual chart and report slots are empty states; live plots not started |
| 3.1 | Surface mesh import and checks | done (self-intersections not detected) |
| 3.2 | CAD import (STEP/IGES/BREP) | not started (spike pending) |
| 3.3 | Geometry repair | not started |
| 3.4 | Domain and boundary definition | done |
| 3.5 | Surface-to-patch assignment | not started (one patch per part) |
| 4.1 | Physics continua | done for steady incompressible RANS (task/4a-physics) |
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022, task/4a-physics) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE; task/4a-physics); docs/reference/turbulence_mapping.md not written |
| 4.4 | Numerics presets | preset "robust" only (task/4a-physics) |
| 5.0 | Meshing benchmark suite | not started |
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing done on task/4a-physics (D-024, D-026, D-045) |
| 5.2 | M2: surface preparation | not started |
| 5.3 | M3: alternative volume mesher | not started (cfMesh build spike pending) |
| 5.4 | M4: prism layer robustness | not started |
| 5.5 | M5: own mesher (go/no-go) | not started |
| 6.1 | Monitors and reports | not started (report slots exist as empty states) |
| 6.2 | Scenes and derived parts | not started (the mesh section plane exists) |
| 6.3 | Data export and reports | not started |
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
- Parallel (mpirun) runs are not supported (runner, clean stop).
- Location of user projects and run outputs in the released app (run/ is development only).
- STEP import spike: OCP novtk wheel next to PyVista's VTK (docs/reference/oss_survey.md).
- STL repair: pymeshfix (wrapper licence to confirm) / pytetwild.
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today.
- Per-part surface size (one target surface size for all parts today).
- Task 0.1 (STAR-CCM+ feature inventory) not done.
- Scalar scenes with field and colormap selection (Phase 6.2).
- Report slot assignment and convergence banner (Phase 6.1).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
