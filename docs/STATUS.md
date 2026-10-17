# Status

Updated 2026-10-17. Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every
task (CLAUDE.md).

## Current branch

**task/6.2-results** (not yet published; Tasks 4A and 4B were merged in PR #13). Done on it:
- Lost parts in meshing (D-052, Proposed, [NUMERICS-REVIEW]; schema v5): post-mesh guard (a part patch
  with 0 faces fails the mesh and blocks Run Solver), pre-mesh thin/small-part warning, per-part
  surface levels with seed lines.
- Task 6.2 (D-053 to D-055, Proposed): Results Scene with field, colormap and range selection, scalar
  bar, walls/section display, field-range telemetry and the stale strip; Open in ParaView with a
  Preferences path.

Next steps: a convergence banner and restarting a run from the latest time (Phase 6.1 / D-046), and a
total cell estimate (today only background cells are estimated). Open items: docs/QUESTIONS.md 55 to 59.

## Phases

| Phase | Title | State |
|---|---|---|
| 0.1 | STAR-CCM+ reference inventory | not started |
| 0.2 | Open-source landscape survey | done for geometry and meshing (docs/reference/oss_survey.md); other modules not surveyed |
| 0.3 | Repo, environment, architecture | done (no CI service: scripts/ship.sh runs the suite before publishing) |
| 1.1 | Simulation data model | done |
| 1.2 | Case writer | done for the cavity reference case; the cylinder and wing reference cases were not written |
| 1.3 | Runner and log parsing | done for single-process runs (parallel not supported); solver run states (D-046) |
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
| 6.1 | Monitors and reports | report slots with Cd, Cl, Cm pitch and wall y+ (D-048); reference values (D-047); convergence banner not started |
| 6.2 | Scenes and derived parts | scalar scenes done (D-053): field/colormap/range selection, scalar bar, section; scene saving, image export, iso-surfaces and streamlines not started |
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
- Convergence banner (Phase 6.1); the run state is in the Solvers node and the status line.
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
- Small parts are seeded only when the user overrides their levels (docs/QUESTIONS.md item 55).
