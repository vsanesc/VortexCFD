# Whole-codebase review (2026-10-20)

Branch task/5.x-parallel-mesh (the D-111 work is reviewed under the same rules as the rest). Scope: every module
under src/vortexcfd/, the tests, the docs (ARCHITECTURE, DECISIONS, STATUS, QUESTIONS, benchmarks) and the real hot
paths, measured on this PC (Ryzen 9 5900X, WSL2) with the benchmark meshes in run/bench/ and the test fixtures.

Each finding: id, file:line, category, severity, evidence, impact, proposed fix, and whether it is **SAFE** (applied
in Part B when worth it) or **FROZEN** (reported only: dictionaries, numerics, meshing defaults, schema, benchmark
definitions, theme, public GUI behaviour). Measured numbers are in section 4; the Part B commits and the Part C
verification are at the end.

## 1. Correctness

| id | where | severity | finding |
|---|---|---|---|
| R-01 | src/vortexcfd/gui/main_window.py:1305, :1330, :1458, :1473 | medium | **A run of project A can write into project B.** `_on_mesh_done` and `_on_solver_done` write the mesh / run record and delete results with `case_dir_for(self._project)` at the time the signal arrives. `set_project` only *requests* a stop of a running mesh or solver; a run that ends normally in the meantime (the stop arrives between the last step's `stopped` read and the result) reaches the slot after the window switched to another project: its report and record are stored under the new project's case/ and `_clear_results_after_meshing` deletes the new project's results. Impact: a wrong mesh record and lost results, rare (needs a project switch during the last seconds of a run). Fix (SAFE): the worker keeps the case directory of the run it started; the done slots ignore a result whose case directory is not the current project's (logged). Same for `_on_results_loaded` (`data.case_dir`). |
| R-02 | src/vortexcfd/foam/mesh_run.py:150, :158 | medium | **An exception in the meshing thread never reports.** `MeshRun._run` wraps `_run_steps` in try/finally only: an OSError from `FoamRun.start` (log file not writable, disk full), from reading a step log, or from writing the decomposeParDict ends the thread with a traceback and `_result` None, so `on_done` is never called: the top bar keeps "Meshing" / "Stop" until the next project change (`is_running()` is False, so the buttons recover at the next refresh, the badge does not), and `MeshRun.wait()` returns None. Fix (SAFE): catch `Exception` in `_run`, build a failed `MeshRunResult` with the error text, and always call `on_done`. `SolverRun._run` catches only OSError / ValueError / RuntimeError (same shape, lower risk). |
| R-03 | src/vortexcfd/foam/mesh_run.py:181 | low | **A stop requested while a step starts is lost for that step.** `request_stop` signals `_current`, set before `run.start(...)`; `FoamRun.request_stop` on a not yet started run returns False, and the step then runs to its end (the loop breaks only after it). `SolverRun._step` handles this ("requested while starting"); `MeshRun` does not. Fix (SAFE): after `run.start`, check `_stop` under the lock and call `run.request_stop()`. |
| R-04 | src/vortexcfd/core/project_io.py:133, src/vortexcfd/core/presets.py:289 | low | **Project files and presets are written with mode 0600.** The atomic writers create the temporary file with `NamedTemporaryFile` / `mkstemp` (mode 0600) and `os.replace` it over the target, so every .vcfd and preset file the app writes is readable by its owner only (checked: `run/bench/wing/wing.vcfd` is `-rw-------`), unlike every other file it writes (geometry copies, cases: 0644). Fix (SAFE): one shared atomic text writer that applies the process umask (`os.chmod(tmp, 0o666 & ~umask)`) before the replace. |
| R-05 | src/vortexcfd/foam/mesh_record.py:27, run_record.py:56, mesh_study.py:160, polar_sweep.py:126 | low | **The records are not written atomically.** `write_text` truncates then writes; a crash mid-write leaves a half file that `read_*` turns into None (no mesh / no run / no study shown). The project file and presets already use a temporary file plus `os.replace`. Fix (SAFE): the shared atomic writer of R-04 for the four records (same content, same names). |
| R-06 | src/vortexcfd/foam/runner.py:235-239 | low | `FoamRun.start` opens the log file before `Popen`; when `Popen` raises (bad working directory) the handle stays open and `_started` stays True with `_done_event` never set, so `is_running()` is True forever on that instance. Callers discard the instance after the exception (SolverRun classifies the run as crashed), so no user-visible effect. Fix (SAFE, small): open the log inside a try that closes it and resets `_started` on failure. Reported; not applied (no observed impact). |
| R-07 | src/vortexcfd/gui/results_scene.py:73-75, gui/mesh_worker.py, gui/solver_worker.py | low | Signals emitted from worker threads after the owning QObject was deleted raise RuntimeError in the thread (a traceback on stderr, no other effect); `GeometryWorker._emit` guards against it, `ResultsLoader`, `MeshWorker._done` and `SolverWorker` do not. Reported. |
| R-08 | src/vortexcfd/foam/postprocessing.py:379 | low | `ReportMonitor.rho()` re-reads system/controlDict with foamlib on every call until it succeeds: a case whose controlDict has no `forces1` entry (an old case) parses the dictionary at every poll of every breakdown series. Reported (cheap, no wrong result). |
| R-09 | src/vortexcfd/core/project.py:255 (resolve_part_path) | low | Part paths from a project file are joined to the project folder without a check that they stay inside it; a hand-edited .vcfd can read a surface from anywhere. Save As refuses such a project (D-079) and nothing is written outside the project, so the exposure is a read. Reported. |

Checked and found sound: the SIGUSR1 / SIGTERM / SIGKILL escalation and the session sweep of `FoamRun` (D-063), the
`TailReader` truncation and partial-line handling, the `LogParser` block bounding, the marker protection of
`prepare_case_dir` / `remove_results`, the save-target rules, the observer error isolation in `Project._notify`, the
queued-signal rule of every worker (callbacks only emit), the mesh and results staleness hashes (legacy fields left
out as D-085 / D-106 / D-107 record), `criteria_met` ignoring rows that lag behind the log, and `classify`'s order of
end states.

## 2. Robustness and security

| id | where | severity | finding |
|---|---|---|---|
| R-10 | src/vortexcfd/foam/runner.py:78, :228; foam/cfmesh_case.py:44; gui/paraview.py:58-66 | info | Shell construction is safe: every OpenFOAM command is `bash -c "source <quoted bashrc> && exec <shlex.join(command)>"`, cfMesh detection quotes every name, ParaView is started from an argument list with `wslpath -w`. Patch, region, volume, probe, project and preset names are validated or sanitised before they reach a dictionary or a file name. No finding. |
| R-11 | src/vortexcfd/geometry/repair.py:126 | low | fTetWild writes `__tracked_surface.stl` into the current directory; the code deletes it afterwards unless it existed before. Known (D-095). Reported. |
| R-12 | src/vortexcfd/geometry/loader.py:18; workflow/meshing.py:451; workflow/surface_prep.py:48, :93; geometry/checks.py:88-89 | low | **Caches that never evict.** The loader cache keeps every loaded surface (a repaired or re-tessellated part leaves the old mesh in memory until the process ends; `clear_cache` is called only by tests), the report caches likewise, and the hash caches keep one entry per file version. In a session that imports and repairs several large parts the memory grows by every version. Fix (SAFE, not applied: a bounded cache changes which loads are cache hits and the GUI relies on the loader for picking; recommended for the owner with a size bound of a few hundred MB). |
| R-13 | src/vortexcfd/gui/main_window.py:2559, :2890 | low | Save As and closing the window block the GUI thread for up to 30 s (`geometry_worker.wait(30)`) while a geometry job runs. Deliberate (a job may still write into the folder); a message would help. Reported. |

## 3. Architecture

| id | where | severity | finding |
|---|---|---|---|
| R-14 | src/vortexcfd/gui/main_window.py (2933 lines), gui/properties_panel.py (2150 lines) | medium | Two modules hold most of the GUI; `main_window.py` mixes project binding, meshing / solving control, the results scene strip, the section controls, file operations and import. The study and volume parts were already split into mixins; the results strip (`_build_results_controls` to `open_sections`, about 300 lines) and the import flows (`import_surface`, `_import_cad`, `_add_cad_parts`, about 200 lines) are the next candidates. Reported (a move, no behaviour change, but large). |
| R-15 | src/vortexcfd/core/model.py:208-211, workflow/meshing.py:306 | low | Docstrings of `Mesh.cores` and `MeshCores.automatic` still say automatic = "the Solvers cores capped by the recommendation"; QUESTIONS 155 / D-111 as accepted drop the Solvers cores (`mesh_cores` does). Fix (SAFE): docstrings. |
| R-16 | src/vortexcfd/foam/mesh_case.py:411 (`_hex_faces(bounds)`), foam/physics_case.py:305 (`fv_solution(solvers)`), core/model.py:329 (`Solvers.relaxation`) | low | Unused parameters: `_hex_faces` ignores `bounds`, `fv_solution` ignores `solvers`, `Solvers.relaxation` is stored and shown but nothing reads it (the "robust" preset is the only value and the values are constants). The schema field is FROZEN; the two parameters are SAFE to drop (dictionary output unchanged). |
| R-17 | src/vortexcfd/gui/widgets.py:20 (`glyph_pixmap`), gui/scene.py:81 (`PartScene.actor_for`), gui/geometry_worker.py:172 (`IntersectionChecker.is_pending`), gui/properties_panel.py:346 (`ElidedLabel.set_full_width`), :1586 (`refresh_reports`), core/project.py:394 (`Project.replace_simulation`), foam/dictfile.py:62 (`set_foam_entry`), foam/runner.py:121 (`RunResult.stopped_by_user`, an alias of `stop_requested`), geometry/domain.py `BOUNDARY_NAMES`, core/presets.py `BOUNDARY_ROLES`, foam/mesh_study.py `DEFAULT_RATIO`, bench/metrics.py `SKEW_THRESHOLD`, core/model.py `SURFACE_PREP_STRATEGIES` | low | **Dead code**: never referenced outside their definition in src/, tests/, scripts/ or benchmarks/ (an AST scan plus a word search). `HARD_CHECKS` (foam/mesh_report.py:94) is documentation only: `check_class` tests `SOFT_CHECKS` and calls everything else hard, as D-100 says; keep it. Fix (SAFE): remove the unused functions, methods and constants; keep `stopped_by_user` (part of a dataclass tests construct). |
| R-18 | src/vortexcfd/gui/main_window.py:2062, :2376 | low | "Add part (placeholder)" in the Edit menu ("PLACEHOLDER: real geometry import comes in Phase 3") adds a Part with an empty source file; the real import exists since Phase 3. A visible menu item: FROZEN (public GUI behaviour), for the owner. |
| R-19 | src/vortexcfd/workflow/surface_prep.py:245-246 | medium | **The intersection segments are computed twice** by `prepare`: `intersection_curves(meshes, drop_hidden=False)` and then `intersection_curves(meshes)` run the same grid and triangle-pair tests (1.9 s on the 3-sphere fixture of section 4 per call) before the second applies the hidden-segment filter; `diagnose` receives both. Fix (SAFE, provable): `intersection_curves` takes the precomputed `Curves` of the `drop_hidden=False` call and only filters them; the result set is identical (the noise rule drops a pair when its visible length is below the threshold, and a pair dropped on its full length is dropped either way). |
| R-20 | src/vortexcfd/workflow/mesh_study.py:160-163 | low | `prepare_study` runs `plan_study` twice (inside `study_readiness` and again). Harmless duplication (tens of ms). Reported. |
| R-21 | src/vortexcfd/foam/physics_case.py:9-25 | low | `inlet_turbulence` is defined above the module's imports (E402 style; the imports are below it). Cosmetic. Reported. |
| R-22 | tests/test_layers.py | info | The layer rules hold for every module; no violation the test does not catch was found (checked the relative imports of gui/ mixins and bench/). `gui/sections.py` is Qt-free post-processing kept in gui/ by D-083. |

## 4. Performance (measured)

All timings single-threaded under `nice -n 15`, offscreen, this PC; scripts in the session scratchpad (not committed).

**Project load and save** (run/bench/wing): `Project.open` 4.2 ms, `Project.save` 0.6 ms, `Project.sim` (a deep copy
of the whole model) 74 us. The workflow calls one GUI refresh makes (`readiness`, `inputs_hash`, `results_hash`,
`physics_problem`, `layer_warning`, `thin_part_warnings`) cost 1 to 2 ms each; 88 % of that is `Project.sim` deep
copies (70 per refresh). Not hot. The GUI side: `MainWindow` with a meshed 231,606-cell project 1.56 s, of which
pyvistaqt / pyvista.plotting / matplotlib imports 0.73 s (once per process), `MeshView.load` 0.43 s (the OpenFOAM
reader), `QApplication.setStyleSheet` 0.29 s. `_refresh` 32 ms; `show_node(part)` 48 ms, the other nodes 8 to 18 ms.

| id | where | severity | finding |
|---|---|---|---|
| R-23 | src/vortexcfd/gui/main_window.py:373, :699 | medium (tests), low (app) | **The theme is applied twice per window.** `__init__` calls `apply_theme` (needed: the metrics of the default size come from the font) and `_apply_appearance` calls it again with the same theme and size. Measured on a warm process: an empty window without a viewer takes 1.25 s, of which the two `setStyleSheet` calls take 0.72 s and the two `setStyle` calls 0.12 s. The second application is redundant (Qt applies the application stylesheet to widgets created after it). The fast suite builds about 300 windows. Fix (SAFE): skip the re-application on the construction path (`_apply_appearance(reapply_theme=False)`); `set_point_size` keeps it. Expected gain: about 0.4 s per window. |
| R-24 | src/vortexcfd/geometry/surface_prep.py:77, :110 | high | **The hidden-segment filter is brute force.** `winding_numbers` evaluates every segment midpoint against every triangle of every third part (O(points x triangles), chunked). Three crossing spheres of 178,800 triangles each: the segments take 1.9 s, the hidden filter 108.8 s (`norm` 37.8 s, `cross` 19.0 s, `einsum` 15.0 s). On the owner's aircraft (6 parts, 262 junction points) it was within the 1.2 s preparation (RESULT_5.2.md), so it hurts only with fine tessellations or many segments, but then it dominates by two orders of magnitude. Fix (SAFE, exact): a point strictly outside a part's bounding box lies outside the part's convex hull, so the surface subtends at most a half space and the generalised winding number is at most 0.5 in magnitude, never above `INSIDE_WINDING`: skip those points. The classification is unchanged for every input; the remaining points are evaluated as before. |
| R-25 | src/vortexcfd/foam/layer_walk.py:29, :45, :67; foam/polymesh.py:19, :38 | medium | **The layer walk (D-109) takes 4 to 6 s per mesh.** Ahmed (231,606 cells, 11,560 wall faces): `PolyMesh.read` 1.49 s (0.43 s building the comment-free text, 0.37 s parsing the tokens with `np.array`, 0.30 s splitting), `walk_layers` 4.22 s (the per-candidate `pts()` frozenset lookups 1.45 s, the `tops` comprehension 0.43 s, `np.argmax` on a list 0.33 s, the loop body 1.0 s, `face_geometry` 1.2 s). Half wing (300,025 cells): 1.75 s + 6.45 s. The user waits for it after every checkMesh. Fix (SAFE if bit-identical): precompute the per-face point sets once as sorted arrays and the candidate faces per cell, keep the exact scalar formulas of the heights and cosines; verify `np.array_equal` of every output array on the three benchmark meshes and the fixtures before accepting. `_numbers` can strip comments with one regular expression and parse with `np.fromstring` (both parsers are correctly rounded). |
| R-26 | src/vortexcfd/foam/postprocessing.py:402-430 | medium | **The force breakdown is recomputed from scratch at every poll.** `series("Cd_pressure")` (and the viscous parts, x_cp) rebuilds `_last_per_time` of the force and moment rows and calls `breakdown` for every sample: 43 ms per call at 12,000 iterations; the Reports node table (`breakdown_rows`) 11 ms. A simulated `MonitorsPanel.refresh` (poll, chart decimation 13 ms, three slot series, the criteria, two oscillation checks, the mass balance) costs 131 ms per 250 ms poll at 12,000 iterations, on the GUI thread, whenever new rows arrive. `SolverRun._check_criteria` pays 5.6 ms per iteration at that length (its `upto` filter and `unique_by_iteration` are O(n)), i.e. a quadratic 70 s of CPU over a 12,000-iteration run. Fix (SAFE, exact): cache the breakdown values per time and recompute only the times whose rows changed (the last time can be rewritten: `writeAndEnd` repeats the final row); the values come from the same `breakdown` call on the same sample. |
| R-27 | src/vortexcfd/geometry/intersections.py:24, :51 | low | The self-intersection check: 0.53 s at 79,200 triangles, 3.73 s at 498,000, 17.7 s at 1,996,000 (`_cell_pairs` 9.7 s of it: the per-group-size loop with `triu_indices`, the rest the pair tests). It runs on a background thread and is skipped above 2,000,000 triangles (D-069). Reported; no change. |
| R-28 | src/vortexcfd/geometry/cad.py:361-376 | low | STEP import: half_wing.step `read_cad` 0.63 s, `tessellate` 0.39 s for 28,114 triangles, 1.33 s for 61,934 (the Python loops over the triangulation nodes and triangles; BRepMesh itself is most of it); ahmed.step 14 ms + 5 ms. Fine at the benchmark sizes; "a few seconds per million triangles" (D-070) stands. No change. |
| R-29 | src/vortexcfd/foam/logparse.py:150 | info | Log parsing: 3.1 us per line (a 328,276-line, 11,680-iteration log in 1.01 s); `ResidualHistory.extend` 12 ms; `decimated()` 13 ms for six 11,680-point series. Fine. |
| R-30 | src/vortexcfd/gui/scene.py:403, :486; gui/results_scene.py | info | Viewer: `MeshView.load` 0.43 s for 231,606 cells (0.33 s in the VTK reader), a section re-slice 83 ms, a normal change 14 ms; the results scene on the 5-time fixture is a few ms per change. Fine at these sizes; a multi-million-cell mesh scales linearly (QUESTIONS 5, known). |
| R-31 | src/vortexcfd/geometry/loader.py:109, :115 | low | `stl_solid_names` reads the whole file twice for an ASCII STL (`read_bytes()[:4096]`, then `finditer(read_bytes())`). Binary STLs (the common case, and every tessellation) return at the header. Reported. |

## 5. Tests

971 passed, 1 skipped in 68.6 s with `-n 8` (the fast selection, offscreen). The 15 slowest fast tests:

| s | test |
|---|---|
| 9.65 | test_solver_gui.py::test_every_disabled_reason_is_the_tooltip (four windows) |
| 6.26 | test_repair.py::test_pymeshfix_losing_geometry_falls_back_to_the_envelope (fTetWild) |
| 5.71 | test_repair.py::test_each_broken_surface_is_repaired[self-intersection] (fTetWild) |
| 5.68 | test_theme.py::test_zoom_actions_and_persistence (windows at several sizes) |
| 5.59 | test_start_screen.py::test_start_choices |
| 5.52 | test_save_safety.py::test_an_existing_non_project_file_is_never_overwritten |
| 5.37 | test_mesh_gui.py::test_button_disabled_with_a_reason_for_each_missing_precondition (three windows) |
| 4.71 | test_properties_layout.py::test_tree_properties_split_defaults_to_40_60_and_is_restored |
| 3.62 | test_monitors_gui.py::test_slot_values_update_live_from_the_postprocessing_files |
| 3.33 | test_layout.py::test_telemetry_follows_checked_fields_and_persists |
| 3.28 | test_mesh_gui.py::test_last_mesh_is_loaded_when_a_project_is_opened |
| 3.12 | test_save_safety.py::test_save_as_duplicates_the_folder_with_its_geometry |
| 3.12 | test_results_scene.py::test_results_tab_fields_and_stale_strip |
| 3.08 | test_parallel.py::test_solvers_node_shows_the_recommended_cores |
| 2.97 | test_solver_gui.py::test_results_go_out_of_date_and_the_record_reloads |

Except the two fTetWild repairs, every slow test is window construction (1.2 s per window warm, R-23).

| id | where | severity | finding |
|---|---|---|---|
| R-32 | tests/*.py | low | **Duplicated fixtures**: `make_window` is defined in 10 files with near-identical bodies (project in tmp_path, a sphere part, FakeDialogs, `qtbot.addWidget`, show); the autouse `_fresh_cache` (clear the loader cache) in 14 files; `_select(w, kind)` in 6; `_children` in 3. A shared `tests/gui_fixtures.py` (or conftest) would remove about 250 lines. Reported; not changed (each file's fixture differs in the project it builds, and moving them touches 14 files for no behaviour gain). |
| R-33 | tests/test_layout.py (56 private accesses), test_import.py (27), test_domain_operations.py (17), ... | low | **Implementation-coupled tests**: the GUI tests drive the window through private attributes (`w._items`, `w._selection`, `w._select_root`, `properties._mesh_stale`); a rename of an attribute breaks tests without a behaviour change. Reported. |
| R-34 | tests/ | medium | **Missing tests for critical paths**: a `MeshRun` whose step cannot start (R-02: no test reaches `on_done` with a failure); a mesh or solver result arriving after the project changed (R-01); `FoamRun.start` failing; the records' atomicity. Part B adds the first two with their fixes. |
| R-35 | docs/QUESTIONS.md items 67, 73, 82 | medium | **The intermittent offscreen crash under xdist.** Evidence gathered: offscreen, `QOpenGLWidget is not supported on this platform` is printed at every `QtInteractor` construction and `viewer.iren` is None (`install_picking` and the camera observer log a traceback each time, which `test_viewer_refresh` and the window tests tolerate). pyvistaqt then falls back to its non-GL QVTKRenderWindowInteractor path with VTK's own offscreen window; `self.viewer.close()` in `closeEvent` releases it, and the deferred deletes run in the autouse fixture after the test. The crash is therefore a VTK offscreen render window being torn down (or rendered) by the Qt deferred delete while a later test's window already renders, in the same process; it needs two windows alive in one worker, which `-n 8` makes likely and single-process runs rare. Reproduction attempt of this review: the nine viewer test files (110 tests) run six times in a row under `-n 8` offscreen plus the full fast run (971 tests): no crash in 1,631 window tests, so the cause is not confirmed. Fix candidates (FROZEN by the viewer's public behaviour? no: internal): finalize the render window explicitly in `closeEvent` (`self.viewer.ren_win.Finalize()` after `close()`), and in tests destroy the window (`deleteLater` + `sendPostedEvents`) before the next window is built. Not applied without a reproduction. |
| R-36 | tests/conftest.py:58 (`sphere_mesh`) | info | The session sphere mesh (a real snappyHexMesh run of about 30 s per xdist worker) is built once per worker and used by 10 files; with `-n 8` every worker that gets one of those tests pays it. Already the right shape; nothing to do. |

## 6. Consistency

| id | where | severity | finding |
|---|---|---|---|
| R-37 | DECISIONS.md index | low | The index has no rows for D-107 to D-111 (the entries exist; the same omission was fixed for D-077 to D-079 in QUESTIONS 92). Fix (SAFE): add the rows. |
| R-38 | ARCHITECTURE.md section 7 and open question 10.3; docs/STATUS.md "Known debts" first item | low | Say the GPU variables are "not implemented yet" / "set in the user's ~/.bashrc; the app should set them": D-104 implemented `core/gpu_select.select_gpu` (ARCHITECTURE section 5 already describes it). Fix (SAFE): update both. |
| R-39 | DECISIONS.md | low | Entries whose tasks were published and are listed as done in STATUS still carry "Proposed": D-064, D-066, D-067, D-068, D-069, D-070, D-071, D-072, D-073, D-076, D-077, D-080, D-081, D-082, D-088, D-100, D-102, D-105. The status rule in the file's header says Proposed is "pending review before the branch is published". Owner's call (FROZEN: decisions). |
| R-40 | docs/STATUS.md "Known debts" (numpy) | info | numpy is still imported directly (geometry/, gui/, foam/polymesh, foam/layer_walk) and not declared in pyproject.toml; the debt is still true. Declaring it is "a dependency" for CLAUDE.md: owner. |
| R-41 | docs/QUESTIONS.md items 70, 82 | info | Item 70 (ship suite 379 s single-process, 584 tests): the fast selection is now 971 tests in 69 s with `-n 8`; the single-process ship time was not re-measured here (slow tests are not run by agents). Item 82 is R-35. |
| R-42 | ARCHITECTURE.md foam/mesh_run.py entry | info | Describes the D-111 pipeline correctly, including the castellation pass; the Mesh.cores docstring (R-15) is the only stale text found about D-111. |

## 7. Prioritised plan

Part B (SAFE, highest severity first; each one commit with its test):

1. R-24 bounding-box pre-filter of the winding numbers (exact), with a before/after measurement.
2. R-19 compute the intersection segments once in `prepare`.
3. R-26 cache the breakdown values in `ReportMonitor` (exact).
4. R-01 ignore worker results of another project (mesh, solver, results loader), with tests.
5. R-02 / R-03 `MeshRun` always reports, and a stop while a step starts is honoured, with tests.
6. R-04 / R-05 one atomic text writer honouring the umask, used by the project file, presets and the four records.
7. R-23 apply the theme once per window (test-suite speed-up, same assertions).
8. R-25 layer walk and polyMesh reading, only if bit-identical on the benchmark meshes.
9. R-15, R-16, R-17 docstrings, unused parameters and dead code.
10. R-37, R-38 docs consistency.

Needs the owner (FROZEN or policy): R-18 (the placeholder menu item), R-39 (Proposed entries), R-40 (numpy in
pyproject), R-12 (a cache bound), R-14 (splitting the two large GUI modules), R-35 (the xdist crash: a reproduction).
No finding in this review changes a dictionary, a boundary condition, the numerics, the meshing defaults, the y+
estimator, the layer sizing, the stopping criteria, the force calculation, the reference values or the schema; none is
tagged [NUMERICS-REVIEW].

## 8. Part B: what was applied

The review was closed early at the owner's request after three of the ten planned commits; the rest of the
plan stands as written in section 7 (nothing else was changed in src/).

| commit | finding | measured |
|---|---|---|
| 773ed53 Geometry: hidden-segment test skips the points outside a component's hull | R-24 | three crossing spheres (178,800 triangles each, 3,821 segments): hidden filter 115.2 s -> 27.4 s, same mask |
| 1d06183 Surface preparation: the intersection segments are computed once | R-19 | the preparation's two curve calls 1.68 s -> 1.35 s (58,800 triangles), 10.34 s -> 9.52 s (237,600); same segments |
| 6c55b01 Monitors: the force breakdown is kept per time instead of recomputed at every poll | R-26 | at 12,000 iterations: series(Cd_pressure) 43.5 -> 18.6 ms, breakdown_rows 11.3 -> 6.1 ms, a poll 131.5 -> 75.6 ms |

Not applied (still SAFE, in priority order): R-01 (a worker result of another project), R-02 / R-03 (`MeshRun`
always reports; a stop while a step starts), R-04 / R-05 (one atomic writer honouring the umask for the project
file, the presets and the four records), R-23 (the theme applied once per window: about 0.4 s of the 1.25 s a
window costs, about 300 windows in the fast suite), R-25 (the layer walk, only if bit-identical), R-15 / R-16 /
R-17 (docstrings, unused parameters, dead code), R-37 / R-38 (the DECISIONS index rows for D-107 to D-111, the
stale GPU notes in ARCHITECTURE and STATUS).

## 8b. Follow-up (2026-10-21)

| commit | finding | result |
|---|---|---|
| f2bb6a1 a mesh or solver run is bound to the case it started in | R-01 | record to the run's own case folder, open project untouched; results of a closed case ignored (D-112) |
| 946e992 every background run reports its end after an exception | R-02 | MeshRun, SolverRun, mesh study and polar sweep always call on_done; the badge returns, the error is in the console (D-113) |
| 0284468 project files, presets and records written atomically with the umask's mode | R-04, R-05 | one writer, core/atomic_io.py (D-114) |
| 2ef3e3a Edit > Add part (placeholder) disabled with a not-built tooltip | R-18 | D-115 |
| 1cd8b77 numpy declared in pyproject.toml | R-40 | numpy>=2.5.4 (the installed version) |
| c2fb76f DECISIONS statuses and index rows | R-39, R-37 | D-068, D-088 Accepted; D-105, D-106 index rows corrected; rows for D-107 to D-111; 16 entries for the owner in QUESTIONS 162 |
| ba0a337 the layer walk steps all wall faces together | R-25 | bitwise identical (below); Ahmed walk 3.23 s -> 1.35 s, the rest is face_geometry |

Still not applied: R-03, R-06, R-07, R-12, R-14 to R-17, R-23, R-38 and the reported-only findings.

## 9. Verification

Re-run on 2026-10-21 at ba0a337 (supersedes the partial verification of db3bca8).

1. Hidden-segment filter (773ed53, 1d06183) on the owner's untrimmed aircraft (local, not committed): Surface
   Preparation only, both strategies, from a frozen export of e41f7f2 and of the branch head: the junction feature
   file of intersection features (262 segments, 13.32 m; the filter drops the tail pairs inside the fuselage) and
   the 12 prepared surface and region-id files of the CAD union are byte-identical (SHA-256), and so are the
   reports apart from the times. No revert.
2. Benchmark (`--no-solve --compare benchmarks/baseline.json`, serial meshing): "no regressions"; every mesh metric of
   the three cases is equal to baseline.json at full JSON precision (cells 233,534 / 300,025 / 231,606, quality,
   strict coverage 99.59 / 94.37 / 96.55 %, zones, first cell, fidelity); only the times, the y+ block (not run)
   and the new `mesh_cores` key differ.
3. Layer walk (R-25): every output array bitwise equal to the previous implementation on every patch at max_layers
   0, 1, 3, 12 and 30 on the three meshes the benchmark regenerated (40-54 s each), the three cfMesh meshes in
   run/bench, tests/data/results_case and the column fixtures (pinned in tests/test_layer_walk_equality.py).
4. Dictionaries: the meshing case of the three public cases as `prepare_job` writes it, their solver files as
   `prepare_solver_case` writes them, the mesh and results hashes with the mesh cores (sphere 8, wing 7, ahmed 7)
   and the cavity reference case, generated at e41f7f2 and at ba0a337: `diff -r` of the 59 files is empty.
5. Fast suite (`-m "not slow and not validation and not long"`, offscreen, `-n 8`, nice 15) at ba0a337:
   `1039 passed, 1 skipped in 58.93s`.
