# Status

Updated 2026-10-17. Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/4a-physics** (Task 4A, [NUMERICS-REVIEW], not yet published). Done on it: physics model and
schema v3 with editors, solver case files (D-022, D-023), y+ estimator (D-024), layer count from y+
(D-026), residual control (D-027), flat plate validation (D-036), decision records and this file.

Pending on it:
- TMR-based flat plate verification (wall-normal grid study, wall BC sensitivity) and the relaxed
  minTetQuality (docs/QUESTIONS.md items 40 and 41).
- Vic's review of D-022, D-023, D-024, D-027 and D-036 (Proposed) and of docs/QUESTIONS.md items 37
  and 38.
- Run Solver in the GUI is still disabled ("Available in Phase 4"): the solver files are generated
  and tested, but not run from the app yet.

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
| 4.1 | Physics continua | in progress on task/4a-physics (steady incompressible RANS only) |
| 4.2 | Boundary condition library | in progress on task/4a-physics (external-aerodynamics set, D-022) |
| 4.3 | Turbulence module | in progress on task/4a-physics (kOmegaSST, y+ estimator, flat plate); docs/reference/turbulence_mapping.md not written |
| 4.4 | Numerics presets | in progress on task/4a-physics (preset "robust" only) |
| 5.0 | Meshing benchmark suite | not started |
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing in progress on task/4a-physics |
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
