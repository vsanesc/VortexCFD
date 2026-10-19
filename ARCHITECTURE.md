# ARCHITECTURE.md

## 1. Overview and Target
`vortexcfd` is a Python-based desktop application providing an integrated CFD workflow (single simulation tree, integrated geometry → mesh → physics → solve → post-processing) orchestrating OpenFOAM as its numerical backend.

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
All application code resides under `src/vortexcfd/` and is strictly partitioned into layers:

```
src/vortexcfd/
├── core/   # Simulation data model
├── foam/   # OpenFOAM integration
├── geometry/  # Surface loading and checks (pyvista, no Qt)
├── workflow/  # Qt-free orchestration joining core, geometry and foam
├── bench/  # Meshing benchmark (no Qt)
└── gui/    # Presentation and 3D viewer
```

### Layer Constraints
- **`core/`**:
  - Encapsulates the simulation data model.
  - `core/model.py`: defines the simulation tree data models validated via Pydantic.
  - `core/project_io.py`: handles saving, loading, validation, and migration of JSON project files.
  - `core/reports.py`: the report ids (force coefficients of all walls or per part, their pressure/viscous parts, x_cp, mass imbalance, y+, probes), their labels, the lists offered to report slots and asymptotic criteria and the default scale floor of the relative range (D-058, D-060).
  - `core/project.py`: Qt-free `Project` document wrapping a `Simulation` with validated edits, snapshot undo/redo, dirty tracking and change observers.
  - `core/save_rules.py`: `check_save_target` (never a geometry file or a non-project file; enforced by `Project.save`) and the .vcfd extension (D-076). There are no untitled projects: `Project.create` makes <parent>/<name>/ with <name>.vcfd, geometry/ and case/ and saves at once (D-077); `Project.duplicate` (Save As) makes a new folder with the referenced geometry copied and no case content (D-079).
  - `core/presets.py`: analysis presets (analysis type, domain shape and sizes, boundary type per role, mesh settings; never physics), the built-in "External flow" and "Empty", `apply_preset`, and `PresetStore` (versioned JSON files in a folder; broken files listed, never raised) (D-077).
  - `core/display_guard.py`: `apply_display_guard()`, called before Qt is imported by tests/conftest.py and by scripts that open windows: offscreen on the WSLg display unless `VORTEXCFD_ALLOW_REAL_DISPLAY=1` (D-068).
  - `Project` is not thread-safe: only the GUI thread may call its methods.
  - Must **NOT** import Qt (`PySide6`), `pyvista`, `pyvistaqt`, or anything GUI-related.
  - Must **NOT** import `vortexcfd.gui`.
- **`foam/`**:
  - Handles OpenFOAM integration (case generation/writing, process execution, log parsing).
  - `foam/dictfile.py`: thin wrapper encapsulating `foamlib` for OpenFOAM dictionary reading and writing.
  - `foam/case_writer.py`: orchestrates writing complete OpenFOAM case directory trees from file dictionaries.
  - `foam/reference_cases/`: generators for standard reference cases (e.g. cavity).
  - `foam/mesh_case.py`: meshing dictionaries (blockMeshDict, surfaceFeatureExtractDict, snappyHexMeshDict, controlDict, fvSchemes/fvSolution) from plain data, `locationInMesh`, and the marker-protected case directory; `part_patch_names` / `wall_patch_names` give every part's wall patches (one snappyHexMesh region per patch, D-071); `part_force_groups` the per-part force objects over all of a part's patches (D-073).
  - `foam/physics_case.py`: solver case files (controlDict with forceCoeffs and yPlus, fvSchemes, fvSolution, transport/turbulence properties, 0/ fields) from the physics, inflow and solver settings, and the inlet k/omega formulas.
  - `foam/yplus.py`: first-layer thickness for a target y+ from the flat-plate skin friction, and its inverse.
  - `foam/mesh_run.py`: `MeshRun` runs blockMesh, surfaceFeatureExtract, snappyHexMesh -overwrite (preceded by the castellation-only run for seeded parts, D-084), createPatch -overwrite (rounded domains only) and checkMesh in sequence on a worker thread through `FoamRun`.
  - `foam/mesh_report.py`: `parse_check_mesh` turns checkMesh output into a `MeshReport`; `parse_layer_table` reads snappyHexMesh's final layer table (per-patch `LayerCoverage`, overall extruded-face share).
  - `foam/results.py`: the latest result time of a case, the fields it holds (`available_fields`, only those written), and derived values (Cp = p / (0.5 U_ref^2) from kinematic p, |U|, components).
  - `foam/mesh_case.py` also resolves per-part surface levels (`part_level_range`) and writes seed lines for small or thin parts automatically (`needs_seeding`, `write_seed_edge_meshes`, D-052); with seeded parts it also writes system/snappyHexMeshDict.castellate (castellation only, the seed lines in `features`) and the main dictionary snaps and adds layers without them (`castellatedMesh false`), so seed lines never act as snap features (D-084); every part surface gets a `curvatureLevel` entry (D-085); `foam/mesh_run.lost_parts` is the post-mesh lost-part guard (part patches with 0 faces in constant/polyMesh/boundary); `workflow/meshing.thin_part_warnings` is the pre-mesh note about seeded parts; `geometry/checks.py` also reports inward normals (signed volume, D-056).
  - `foam/mesh_case.remove_results`: deletes the solver results (time directories after 0, postProcessing/, the run record) of a marker-protected case after a successful mesh.
  - `foam/mesh_record.py`: `case/vortexcfd_mesh.json`, the last `MeshReport` plus the hash of the meshing inputs (used to flag an out-of-date mesh).
  - `foam/runner.py`: process execution via `run_foam` and streaming runner `FoamRun` returning `RunResult`. Clean stop (`clean_stop=True`, SIGUSR1) works for single-process solvers and for `mpirun ... -parallel` (Open MPI forwards SIGUSR1 to the ranks); timeout and escalation signal the process group and every process of the run's session (`signal_session`), and processes left in the session after the main one ends are killed (D-063).
  - `foam/parallel.py`: physical cores, system/decomposeParDict (scotch), the mpirun command line (placement `BINDINGS`, Open MPI's default kept) and the decomposePar summary, the recommended core count (`recommended_cores`, D-064); `SolverRun` runs decomposePar, mpirun and reconstructPar -latestTime when `Solvers.cores` > 1 (D-063).
  - `foam/logparse.py`: incremental solver log parsing via `LogParser` recording `TimeStep` events (and `Converged` when the SIMPLE residualControl is reached).
  - `foam/solver_run.py`: `SolverRun` runs simpleFoam through `FoamRun(clean_stop=True)` on a worker thread, parses the log, evaluates app-side stopping criteria after every iteration (and stops the solver cleanly when they are met) and classifies the end state (criteria met, iteration limit, stopped, crashed).
  - `foam/run_record.py`: `case/vortexcfd_run.json`, the last run's state, iterations, final residuals, results inputs hash and the stopping criteria (all of them, those that stopped the run and the iteration at which they were met); old "converged" records are migrated on read.
  - `foam/convergence.py`: stopping criteria: residual-only sets as the runTimeControl function object (`run_time_control`, `is_native`), otherwise evaluated by the app (`app_side`, `evaluate`, `criteria_met`, the range-based `asymptotic_range`); the oscillation check (`oscillation`) uses the same normalisation (D-058, D-059). `LogParser` reports runTimeControl's stop as the `CriteriaMet` event.
  - `foam/gci.py`: the Celik et al. (2008) grid convergence index (apparent order, extrapolation, GCI fine / medium, asymptotic ratio; oscillatory, divergent and undefined cases get no number, D-066).
  - `foam/mesh_study.py`: mesh study levels (`study_levels`, `scale_mesh`, the shared absolute layer stack `reference_layers`), the record case_study/study.json, the GCI rows, CSV export and `StudyRun`, which meshes and solves the levels in order (D-066).
  - `foam/polar_sweep.py`: the angle-of-attack sweep: point directories with a shared mesh link, initialisation from the previous converged point, the record case_sweep/sweep.json, CSV export and `SweepRun` (D-067).
  - `foam/residuals.py`: `ResidualHistory` (initial residual per field and iteration) and `decimate` (at most about 2000 points per series).
  - `foam/forces.py`: force breakdown (pressure / viscous coefficients from force.dat with the coefficient.dat header), Cm and centre of pressure, mass imbalance (D-060). `foam/wall_fields.py`: Cf and Cf_x from wallShearStress, the y+ histogram and wall face values of a field file (D-061).
  - `foam/postprocessing.py`: tails the forceCoeffs (`coefficient.dat`), forces (`force.dat`) and yPlus (`yPlus.dat`) output files (`ReportMonitor`, `TailReader`), tolerating a partial last line; `ReportMonitor` also finds the per-part forces, massFlow_<patch> and probe_<name> objects by name and serves every report id of core/reports.py; y+ across walls is face-count weighted from `constant/polyMesh/boundary`; `project_coefficients` projects a force onto the drag and lift directions.
  - `foam/physics_case.py` also resolves the forceCoeffs reference values (`reference_values`: overrides from `Reports` or the parts' bounding box).
  - `SolverCrash` (logparse): event for an OpenFOAM `[stack trace]` block. A diverging solver dies with SIGFPE and prints no nan residuals, so the process exit code is the reliable failure signal.
  - `FoamRun.is_running()` is False and `FoamRun.wait()` raises `RuntimeError` before `start()` has been called.
  - Must **NOT** import Qt (`PySide6`) or anything GUI-related.
  - Must **NOT** import `vortexcfd.gui`.
- **`geometry/`**:
  - Surface geometry; may import numpy and pyvista, must **NOT** import Qt, pyvistaqt or `vortexcfd.gui`; `core/` must not import it.
  - `geometry/loader.py`: `load_surface(path, units)` reads STL/OBJ/PLY as a triangulated PyVista mesh in metres (cached by path, mtime and units); STL triangles keep their `solid` block index (`stl_solid_names`, D-069).
  - `geometry/checks.py`: `check_surface(mesh)` returns a `SurfaceReport` (open and non-manifold edges, degenerate and duplicate triangles, orientation, watertightness, self-intersections, `snappy_ready`).
  - `geometry/intersections.py`: self-intersecting triangles (grid broad phase, edge-triangle tests; skipped above 2M triangles, D-069).
  - `geometry/cad.py`: STEP/IGES/BREP through OCP (bodies, face names and colours, assemblies) and `tessellate` with a CAD face id per triangle (D-070).
  - `geometry/regions.py`: per-triangle base ids (.npy files, content-hashed names), region and patch labels, the angle split, id transfer to a changed surface, the multi-solid STL writer (D-071).
  - `geometry/repair.py`: `repair_surface`: pymeshfix with a fidelity check, the pytetwild envelope as the fallback, before / after reports (D-072).
  - `geometry/domain.py`: `compute_domain(parts_bounds, domain)` returns the far-field `DomainBox` (shape box / bullet / c_type, reference length L, boundary roles, exact volume, warnings; D-019, D-078).
  - `geometry/domain_surface.py`: the closed triangulated domain surface with a `role` cell array (viewer, volume checks) and `meshing_surface` (the snappyHexMesh copy of a rounded shape: no symmetry region, its edge continued through the plane) (D-078).
- **`workflow/`** (D-083):
  - Qt-free orchestration that joins core, geometry and foam (it cannot live in `foam/`, which must not depend on `geometry/`); used by gui/ and by the benchmark.
  - May import core, foam and geometry (so numpy and pyvista); must **NOT** import Qt, pyvistaqt, `vortexcfd.gui` or `vortexcfd.bench` (tests/test_layers.py).
  - `workflow/part_ops.py`: Qt-free part geometry operations returning the Part fields of one undoable edit: multi-solid STL and CAD import, re-tessellation, repair into a new file version, region rename / merge / split / patch assignment (D-069 to D-072).
  - `workflow/meshing.py`: Qt-free orchestration joining core, geometry and foam (it cannot live in `foam/`, which must not depend on `geometry/`): `readiness(project)` says why a project cannot be meshed and `prepare_job(project)` writes <project>/case (dictionaries, part STLs in metres, the rounded domain's domain.stl and the domain guard file); `estimate_for(box, mesh)` is the estimate on the actual domain volume.
  - `workflow/solving.py`: Qt-free solver orchestration: `readiness` (why Run Solver is disabled), `prepare_solver_case` (clears the previous outputs, writes the solver files) and `results_hash`.
  - `workflow/mesh_study.py`: Qt-free mesh study orchestration: the plan with estimates, readiness, the level cases in <project>/case_study/level_<n>/ and the solver file writer (D-066); `workflow/polar_sweep.py`: Qt-free sweep orchestration (readiness, the mesh copy into <project>/case_sweep, the point writer, D-067).
  - `workflow/meshing.py` also resolves the surface size length (`surface_length`: l_ref, its automatic value with the Mesh-properties warning, or L for projects made before schema v10) and `project_estimate` (D-085).
- **`bench/`** (D-081, D-082):
  - The meshing benchmark, `python -m vortexcfd.bench`: `geometries.py` (sphere STL, NACA 0012 wing and Ahmed-type body STEP built with OCP, byte-identical, generated into benchmarks/geometries/), `cases.py` (case definitions: the app's defaults plus listed deviations, layer-coverage zones), `runner.py` (one case through the app's pipeline: Project, import, `workflow/meshing.prepare_job`, `MeshRun`, layer fields, face non-orthogonality, fidelity, the indicative y+ run through `workflow/solving.prepare_solver_case` and `SolverRun`), `metrics.py` (pure metric functions), `report.py` (result JSON / Markdown, `--compare` rules), `cli.py` (one process per case). Results in benchmarks/results/ (git-ignored); the baseline is benchmarks/baseline.json.
  - May import core, foam, geometry and workflow; must **NOT** import Qt, pyvistaqt or `vortexcfd.gui` (tests/test_layers.py; a test checks that importing it loads no Qt). Each case sets its l_ref; the headline layer metric is the strict coverage (D-087).
- **`gui/`**:
  - Implements UI components, main window, and 3D visualization using PySide6 and PyVista/pyvistaqt.
  - `gui/theme.py`: design tokens (`Theme`), Fusion palette/stylesheet and font zoom; `gui/icons.py` draws tree icons in code.
  - `gui/widgets.py`: shared pieces (section header, badge, search field, glyph pixmaps, `FlowLayout` for rows that wrap).
  - `gui/topbar.py`: top bar (brand, project file and state, mesh and results staleness badges, camera buttons, wireframe, Generate Mesh / Run Solver).
  - `gui/monitors.py`: right column: the convergence banner, per-criterion table and oscillation warnings (`ConvergencePanel`), live log-scale residual chart drawn with QPainter (legend, autoscroll, decimated series, palette in `theme.RESIDUAL_STYLES`) and the report slots (assignment menu, last value, sparkline), polled from the postProcessing files on a GUI-thread timer.
  - `gui/viewport.py`: VTK-drawn viewport pieces (ground grid, empty-scene message, telemetry card) and telemetry settings.
  - `gui/settings_store.py`: the shared `QSettings` accessor.
  - `gui/scene.py`: one VTK actor per Part kept in sync with the Project (picking, visibility, selection colour), part file status, cached surface reports, and the translucent domain surface with the selected boundary role highlighted (`DomainView`).
  - `gui/geometry_worker.py`: `GeometryWorker` (one geometry job at a time on a background thread: CAD reading and tessellation, re-tessellation, repair) and `IntersectionChecker` (self-intersection reports in the background); signals only, results applied on the GUI thread (D-073).
  - Rounded domains (D-078): `foam/mesh_case.py` writes a background box (patch "background"; the symmetry plane is its y_min face), domain.stl as a level-0 refinement surface whose regions are the patches, and a createPatchDict that removes the emptied background patch; `foam/mesh_run.domain_problems` is the post-mesh guard (`MeshReport.domain_errors`).
  - `foam/mesh_estimate.py`: `estimate_mesh` gives background cells, refinement levels, surface cell size (from the given surface length) and the finest curvature level from the sizing targets (limit 2,000,000 background cells).
  - `gui/results_scene.py`: Results Scene: `read_results` (PyVista OpenFOAM reader, run by `ResultsLoader` on a worker thread, signals only), `ResultsView` (fields on the walls and the section plane, range modes, scalar bar in the `text` token).
  - `gui/sections.py`: Qt-free cuts of the wall patches by y or z planes, ordered along the cut's connectivity and split at min/max x into two branches labelled by the in-plane normal, x/c and Cp, CSV export; `gui/section_tool.py`: the Results Scene's Sections window (D-062).
  - `gui/charts.py`: QPainter charts (y+ histogram, line chart); `gui/report_views.py`: the Forces table of the Reports & Monitors node.
  - `gui/colormaps.py`: the Results Scene colormaps (matplotlib lookup tables, D-054), the one place to add one.
  - `gui/paraview.py`: Open in ParaView (executable from Preferences or detected under /mnt/c/Program Files, `wslpath -w`, detached launch).
  - `gui/study_rows.py` (properties rows of the Mesh Study and Polar Sweep nodes, mixed into PropertiesPanel), `gui/study_control.py` (the study workers and Run / Stop, mixed into MainWindow), `gui/study_windows.py` (results windows).
  - `gui/solver_worker.py`: Qt wrapper around `SolverRun` (signals only, like `MeshWorker`).
  - `gui/mesh_worker.py`: Qt wrapper around `MeshRun`; the worker and reader threads only emit signals, slots run in the GUI thread. `gui/scene.py` also holds `MeshView` (part patches of the generated mesh with edges).
  - `gui/console.py`: output console fed by a logging handler on the `vortexcfd` logger.
  - `gui/start_dialogs.py`: the Start dialog (new, open, recent projects), the New simulation dialog (name, parent folder, preset, cores) and Manage presets; `gui/recent.py`: the recent projects list (QSettings); `gui/domain_dialog.py`: Generate domain; `gui/settings_store.presets_dir()`: <config>/VortexCFD/presets. `MainWindow(None)` is the empty start state (only File and Help active); `main_window.start_window` opens the Start dialog when no path is given (D-077, D-078).
  - `gui/properties_panel.py`: properties rows (label left, mono value box right) for the selected node, including the Reference Values node and the Stopping Criteria node (rows rebuilt per criterion); `gui/dialogs.py`: injectable file/confirm dialogs.
  - The viewer runs with `QtInteractor(auto_update=False)`: pyvistaqt's 5 Hz render timer made offscreen test runs abort intermittently (VTK render without GL), so the window renders explicitly after every change; interaction still renders through VTK events.
  - Spin boxes hide their buttons through the stylesheet (`::up-button/::down-button { width: 0 }`) and their inner QLineEdit is unstyled: `setButtonSymbols(NoButtons)` combined with a stylesheet collapses the edit field to 1 px.
  - May import `core`, `foam`, `geometry` and `workflow`.
- **Enforcement Rule**: `core` and `foam` must never import `gui`. This guarantees that simulation data manipulation, case generation, and solver execution remain fully decoupled from the graphical user interface, enabling headless automation and CLI operation.

## 5b. Validation
`tests/validation/` holds numerics validation cases (marker `validation`, run with `pytest -m validation`); real runs above 60 s carry the marker `long` (`pytest -m long`, e.g. the parallel speedup study, docs/validation/parallel/); `tests/validation/flat_plate_case.py` builds a 2D flat plate with blockMesh and the app's own solver files, and results and verdicts are written to `docs/validation/<case>/`.

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
Simulation results are always stored as standard OpenFOAM cases (no app-specific result format), so any case produced by the app can be opened in ParaView. The app's own viewer is a convenience, not a replacement. The Results Scene has an "Open in ParaView" button (D-055) that starts the Windows ParaView on the case's case.foam.

## 10. Open Questions
1. Long-term solver backend abstraction: whether to keep the backend open for alternative solvers (e.g., SU2) or remain strictly OpenFOAM-only.
2. Where user projects and simulation outputs live in the released app (run/ in the repo root is a development-only location).
3. Launcher script implementation details for setting `GALLIUM_DRIVER=d3d12` and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`.
