# ARCHITECTURE.md

## 1. Overview and Target
`vortexcfd` is a Python-based desktop application providing a STAR-CCM+-style workflow (single simulation tree, integrated geometry → mesh → physics → solve → post-processing) orchestrating OpenFOAM as its numerical backend.

## 2. Runtime Environment
- The entire application runs inside **WSL2** running **Ubuntu 24.04**.
- The graphical user interface is displayed on the host operating system (**Windows 11**) via **WSLg**.

## 3. Numerical Backend
- **OpenFOAM ESI v2606 only**, installed at `/usr/lib/openfoam/openfoam2606`.
- OpenFOAM is **never assumed to be on `PATH`**.
- Every OpenFOAM process is launched through `vortexcfd.foam.runner`, which sources `/usr/lib/openfoam/openfoam2606/etc/bashrc` explicitly.

## 4. Technology Stack
- **Python**: >= 3.11 (developed on 3.12)
- **GUI Framework**: PySide6 (Qt)
- **3D Viewer / Visualization**: PyVista + pyvistaqt
- **Testing**: pytest + pytest-qt

## 5. Package Layers
All application code resides under `src/vortexcfd/` and is strictly partitioned into three layers:

```
src/vortexcfd/
├── core/   # Simulation data model
├── foam/   # OpenFOAM integration
├── geometry/  # Surface loading and checks (pyvista, no Qt)
└── gui/    # Presentation and 3D viewer
```

### Layer Constraints
- **`core/`**:
  - Encapsulates the simulation data model.
  - `core/model.py`: defines the simulation tree data models validated via Pydantic.
  - `core/project_io.py`: handles saving, loading, validation, and migration of JSON project files.
  - `core/project.py`: Qt-free `Project` document wrapping a `Simulation` with validated edits, snapshot undo/redo, dirty tracking and change observers.
  - `Project` is not thread-safe: only the GUI thread may call its methods.
  - Must **NOT** import Qt (`PySide6`), `pyvista`, `pyvistaqt`, or anything GUI-related.
  - Must **NOT** import `vortexcfd.gui`.
- **`foam/`**:
  - Handles OpenFOAM integration (case generation/writing, process execution, log parsing).
  - `foam/dictfile.py`: thin wrapper encapsulating `foamlib` for OpenFOAM dictionary reading and writing.
  - `foam/case_writer.py`: orchestrates writing complete OpenFOAM case directory trees from file dictionaries.
  - `foam/reference_cases/`: generators for standard reference cases (e.g. cavity).
  - `foam/mesh_case.py`: meshing dictionaries (blockMeshDict, surfaceFeatureExtractDict, snappyHexMeshDict, controlDict, fvSchemes/fvSolution) from plain data, `locationInMesh`, and the marker-protected case directory.
  - `foam/physics_case.py`: solver case files (controlDict with forceCoeffs and yPlus, fvSchemes, fvSolution, transport/turbulence properties, 0/ fields) from the physics, inflow and solver settings, and the inlet k/omega formulas.
  - `foam/yplus.py`: first-layer thickness for a target y+ from the flat-plate skin friction, and its inverse.
  - `foam/mesh_run.py`: `MeshRun` runs blockMesh, surfaceFeatureExtract, snappyHexMesh -overwrite and checkMesh in sequence on a worker thread through `FoamRun`.
  - `foam/mesh_report.py`: `parse_check_mesh` turns checkMesh output into a `MeshReport`; `parse_layer_table` reads snappyHexMesh's final layer table (per-patch `LayerCoverage`, overall extruded-face share).
  - `foam/mesh_record.py`: `case/vortexcfd_mesh.json`, the last `MeshReport` plus the hash of the meshing inputs (used to flag an out-of-date mesh).
  - `foam/runner.py`: process execution via `run_foam` and streaming runner `FoamRun` returning `RunResult`. Clean stop works for single-process solvers launched through `FoamRun` with `clean_stop=True`.
  - `foam/logparse.py`: incremental solver log parsing via `LogParser` recording `TimeStep` events (and `Converged` when the SIMPLE residualControl is reached).
  - `foam/solver_run.py`: `SolverRun` runs simpleFoam through `FoamRun(clean_stop=True)` on a worker thread, parses the log and classifies the end state (converged, iteration limit, stopped, crashed).
  - `foam/run_record.py`: `case/vortexcfd_run.json`, the last run's state, iterations, final residuals and results inputs hash.
  - `foam/residuals.py`: `ResidualHistory` (initial residual per field and iteration) and `decimate` (at most about 2000 points per series).
  - `foam/postprocessing.py`: tails the forceCoeffs (`coefficient.dat`) and yPlus (`yPlus.dat`) output files (`ReportMonitor`, `TailReader`), tolerating a partial last line.
  - `foam/physics_case.py` also resolves the forceCoeffs reference values (`reference_values`: overrides from `Reports` or the parts' bounding box).
  - `SolverCrash` (logparse): event for an OpenFOAM `[stack trace]` block. A diverging solver dies with SIGFPE and prints no nan residuals, so the process exit code is the reliable failure signal.
  - `FoamRun.is_running()` is False and `FoamRun.wait()` raises `RuntimeError` before `start()` has been called.
  - Must **NOT** import Qt (`PySide6`) or anything GUI-related.
  - Must **NOT** import `vortexcfd.gui`.
- **`geometry/`**:
  - Surface geometry; may import numpy and pyvista, must **NOT** import Qt, pyvistaqt or `vortexcfd.gui`; `core/` must not import it.
  - `geometry/loader.py`: `load_surface(path, units)` reads STL/OBJ/PLY as a triangulated PyVista mesh in metres (cached by path, mtime and units).
  - `geometry/checks.py`: `check_surface(mesh)` returns a `SurfaceReport` (open and non-manifold edges, degenerate and duplicate triangles, orientation, watertightness).
  - `geometry/domain.py`: `compute_domain(parts_bounds, domain)` returns the far-field `DomainBox` (reference length L, named boundaries, warnings).
- **`gui/`**:
  - Implements UI components, main window, and 3D visualization using PySide6 and PyVista/pyvistaqt.
  - `gui/theme.py`: design tokens (`Theme`), Fusion palette/stylesheet and font zoom; `gui/icons.py` draws tree icons in code.
  - `gui/widgets.py`: shared pieces (section header, badge, search field, glyph pixmaps).
  - `gui/topbar.py`: top bar (brand, project file and state, mesh and results staleness badges, camera buttons, wireframe, Generate Mesh / Run Solver).
  - `gui/monitors.py`: right column: live log-scale residual chart drawn with QPainter (legend, autoscroll, decimated series, palette in `theme.RESIDUAL_STYLES`) and the report slots (assignment menu, last value, sparkline), polled from the postProcessing files on a GUI-thread timer.
  - `gui/viewport.py`: VTK-drawn viewport pieces (ground grid, empty-scene message, telemetry card) and telemetry settings.
  - `gui/settings_store.py`: the shared `QSettings` accessor.
  - `gui/scene.py`: one VTK actor per Part kept in sync with the Project (picking, visibility, selection colour), part file status, cached surface reports, and the translucent domain box (`DomainView`).
  - `gui/meshing.py`: Qt-free orchestration joining core, geometry and foam (it cannot live in `foam/`, which must not depend on `geometry/`): `readiness(project)` says why a project cannot be meshed and `prepare_job(project)` writes <project>/case (dictionaries and part STLs in metres).
  - `foam/mesh_estimate.py`: `estimate_mesh` gives background cells, refinement levels and surface cell size from the sizing targets (limit 2,000,000 background cells).
  - `gui/solving.py`: Qt-free solver orchestration: `readiness` (why Run Solver is disabled), `prepare_solver_case` (clears the previous outputs, writes the solver files) and `results_hash`.
  - `gui/solver_worker.py`: Qt wrapper around `SolverRun` (signals only, like `MeshWorker`).
  - `gui/mesh_worker.py`: Qt wrapper around `MeshRun`; the worker and reader threads only emit signals, slots run in the GUI thread. `gui/scene.py` also holds `MeshView` (part patches of the generated mesh with edges).
  - `gui/console.py`: output console fed by a logging handler on the `vortexcfd` logger.
  - `gui/properties_panel.py`: properties rows (label left, mono value box right) for the selected node, including the Reference Values node; `gui/dialogs.py`: injectable file/confirm dialogs.
  - The viewer runs with `QtInteractor(auto_update=False)`: pyvistaqt's 5 Hz render timer made offscreen test runs abort intermittently (VTK render without GL), so the window renders explicitly after every change; interaction still renders through VTK events.
  - Spin boxes hide their buttons through the stylesheet (`::up-button/::down-button { width: 0 }`) and their inner QLineEdit is unstyled: `setButtonSymbols(NoButtons)` combined with a stylesheet collapses the edit field to 1 px.
  - May import `core` and `foam`.
- **Enforcement Rule**: `core` and `foam` must never import `gui`. This guarantees that simulation data manipulation, case generation, and solver execution remain fully decoupled from the graphical user interface, enabling headless automation and CLI operation.

## 5b. Validation
`tests/validation/` holds numerics validation cases (marker `validation`, run with `pytest -m validation`); `tests/validation/flat_plate_case.py` builds a 2D flat plate with blockMesh and the app's own solver files, and results and verdicts are written to `docs/validation/<case>/`.

## 6. Simulation Outputs
- All simulation output directories, intermediate files, and temporary execution logs are written under `run/` at the repository root.
- The `run/` directory is git-ignored.

## 7. GPU Acceleration
- 3D rendering relies on WSLg + Mesa `d3d12`.
- A future launcher task will set the following environment variables if not already set:
  - `GALLIUM_DRIVER=d3d12`
  - `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`
  *(Note: not implemented yet.)*

## 8. Validation Policy and Agent Workflow
Validation policy and agent workflow: see docs/PLAN.md section 0.

## 9. Results and ParaView
Simulation results are always stored as standard OpenFOAM cases (no app-specific result format), so any case produced by the app can be opened in ParaView. The app's own viewer is a convenience, not a replacement. An "Open in ParaView" button is planned for Phase 6 and is not implemented yet.

## 10. Open Questions
1. Long-term solver backend abstraction: whether to keep the backend open for alternative solvers (e.g., SU2) or remain strictly OpenFOAM-only.
2. Where user projects and simulation outputs live in the released app (run/ in the repo root is a development-only location).
3. Launcher script implementation details for setting `GALLIUM_DRIVER=d3d12` and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`.
4. Parallel (mpirun) solver execution and clean stop are not covered yet.
