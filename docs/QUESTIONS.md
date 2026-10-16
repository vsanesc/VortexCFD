# Open questions and autonomous decisions

Decisions taken while Vic was away (Tasks 3.4 and 5.1). Each one is reversible; please confirm or correct.

1. **No GUI editor for the mesh controls yet.** `Project.update_mesh` and the model exist (and are undoable and tested), but the Mesh node only shows the checkMesh report. Should the Mesh node also get editable fields (base size, levels, layers, ...)?
2. **Part patch names.** A part's patch is named after the part with every character outside `[A-Za-z0-9_]` replaced by `_` (case kept); names that collide with a domain boundary (`inlet`, `outlet`, `sides`, `top`, `bottom`, `symmetry`) or with each other get a numeric suffix. The tree's wall nodes still show the original part names.
3. **Tree layout of the domain.** Regions > Fluid Domain > inlet, outlet, sides, top, bottom, (symmetry), then one "<part> (wall)" node per part. The old "(none yet)" placeholder under Regions is gone. With the domain disabled only the walls remain. Boundary and wall nodes have no properties yet.
4. **Viewer auto-update is off.** `QtInteractor(auto_update=False)`: the 5 Hz render timer made offscreen test runs abort intermittently (VTK render without GL). The window renders explicitly after every change; interaction still renders through VTK events.
5. **Mesh scene is read on the GUI thread.** `MeshView.load` uses pyvista's OpenFOAM reader after meshing finishes. A multi-million-cell mesh will freeze the window for a moment; moving it to a worker is Phase 5.x work.
6. **Existing case meshes are not reloaded** when a project is opened: the Mesh node shows "No mesh" and the mesh scene is empty until Generate Mesh runs again (the report is not stored in the project file).
7. **checkMesh flags.** Plain `checkMesh` (no `-allGeometry -allTopology`). The report fields are cells, faces, points, max/avg non-orthogonality, max skewness and the failed-check count. A mesh with failed checks is still shown and reported as a warning.
8. **Feature extraction.** `surfaceFeatureExtract` runs on every part STL with `includedAngle = 180 - feature_angle` and the feature level equals `surface_level_max`; `resolveFeatureAngle` equals `feature_angle`.
9. **locationInMesh heuristic.** The point is placed upstream of the parts' union bounding box (midway between the inlet and the box), in the background cell column through the middle of the parts' y/z range, at fixed cell fractions (0.34, 0.41, 0.28) that are at least 0.027 of a cell from every face up to refinement level 4. It is outside all parts by construction; it would fail only if a part reached the inlet region, which the multipliers rule out.
10. **Layers.** One `nSurfaceLayers` entry per part (regex `"<part>.*"`); with `layers = 0` the layer step is switched off (`addLayers no`).
11. **Meshing requires every part file to exist** (not just one); a part whose file is missing blocks Generate Mesh with a tooltip.
12. **No pytest-timeout.** It is not installed (no new dependencies), so OpenFOAM tests use `MeshRun(step_timeout_s=...)` and bounded `wait()`/`waitUntil()` calls (<= 120 s) instead of a marker.
13. **`vortexcfd/meshing.py`** (project -> case orchestration) sits outside the three layers because it needs core, geometry and foam together; `tests/test_layers.py` does not constrain it.
14. **Display test runs are slow** (about 7 minutes for the whole suite on WSLg) compared with offscreen (about 3 minutes).
