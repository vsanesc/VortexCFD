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

## Review round on Task 5.1 (cell budget, layers, staleness)

15. **`estimate_mesh` takes the domain bounds and L**, not a `DomainBox`: `foam/` must not import `geometry/` (which imports pyvista), so the box fields are passed as plain data. Same reason `gui/meshing.py` (not `foam/`) holds the orchestration; `tests/test_layers.py` now also forbids foam -> geometry and geometry -> foam.
16. **Default sizing and levels.** Defaults are 100 000 background cells and 0.01 L surface cells; the levels follow from them (default domain around a 1 m object: base 0.269 m, levels 4-5, surface cells 8.4 mm). `surface_level_min/max` and `base_size` are optional overrides (None = computed); setting only the max gives min = max - 1. The editor shows "auto" for an unset override (spin box minimum).
17. **Background cell limit** is 2,000,000 (`MAX_BACKGROUND_CELLS`): Generate Mesh is disabled with a tooltip above it; the Mesh properties show the cells in warning colour.
18. **Layer coverage basis.** snappyHexMesh prints no per-patch count of faces that received layers, so the per-patch coverage is the achieved fraction of the target layer *thickness* (the column "[%]" of its final table) and the report says so (`basis = "thickness"`). The overall share of extruded faces (from the last "Extruding N out of M faces" line) is shown separately. Coverage below 80 % is a warning (colour and console WARNING).
19. **Out-of-date mesh** is shown as a separate badge ("Mesh out of date") next to the Saved/Modified badge (so the file state is not hidden), in the Mesh properties (Status row) and as a VTK text in the Mesh Scene. The hash covers part names, units, part file *contents*, the domain and the mesh settings; it ignores the project name, view settings and layer-coverage threshold. A mesh found at project open is shown even if its case/polyMesh was deleted (the report is kept, the viewer logs the load error).
20. **Patch names** use the first free numeric suffix (`_1`, `_2`, ...), also against the domain boundary names; the Part properties show the patch name read-only.

## Readable properties (scroll area, label column)

21. **Rows stack when the panel is narrow.** The label column is the widest visible label clamped to [9u, 55 % of the panel] (longer labels are elided with a tooltip). The default left column is only 14u wide (max 22u), which would leave a field narrower than 12u beside a 9u+ label, so below that field width every row stacks instead: label above the field, full width. The side-by-side layout is used when the column is wider than about 35u (e.g. after raising the left column's cap). Say if you would rather widen the left column than stack.
22. **Stylesheet quirk.** `QAbstractSpinBox::setButtonSymbols(NoButtons)` combined with a stylesheet collapses the spin box's edit field to 1 px (the "slivers" with invisible values); the buttons are now hidden by the stylesheet (`::up-button/::down-button { width: 0 }`) and the inner QLineEdit of spin boxes is unstyled, so the box is drawn once.
23. **Tree/properties split.** The default is now 40 % / 60 % of the left column (`LAYOUT.tree_split`, previously 0.548 measured on the mockup); the user's drag is stored in QSettings (`layout/left_tree_fraction`).
24. **Domain box size text** uses three significant digits (e.g. `16 × 11 × 11 m`) so it fits the field at font 14.

## Mesh Scene section plane

25. **Branch.** The previous branch (`task/3.4-domain`) was merged and `main` was checked out, so this work is on a new local branch `task/5.1-mesh-section-plane` (nothing was committed on `main`).
26. **Section contrast.** With the owner tokens (cut cells with edges in `part_edge` #2A3446 over `elevated` #1A202C) the section is legible but low-contrast: the nested refinement boxes and the dense cells around the part are clear, the prism layers only when zoomed in. A brighter edge token (for example `border_active`) would help; I did not change the tokens.
27. **Section framing and clipping.** The camera looks at the plane from its negative side and frames the parts' box plus 0.75 part extents; the part walls are clipped to the side behind the plane so they do not hide it (the section's hole where the part is shows the inside of the far half). With the section off the whole walls are shown.
28. **Plane defaults.** Normal +y through the centre of the part patches; with symmetry on, the symmetry plane nudged 0.2 % of the domain inside it (a plane exactly on the boundary face gives no cut). Changing the normal resets the offset to the same default for that axis. The slider re-slices the internal mesh on every step, which is instant for the coarse meshes but may lag on multi-million-cell meshes.
29. **Controls** are in their own strip under the scene tabs (visible in the Mesh Scene only), because they did not fit beside the tabs in the default window. The domain boundary patches (inlet, outlet, sides, top, bottom, symmetry) are translucent faces in `border_active`, off by default.

## Wider left column, side-by-side rows

30. **Rows are stacked at the default width.** The left column now starts at 18u (min 14u, max 28u), but the property rows only go side by side when the panel is at least 20u wide (label column clamped to [8u, 50 %], field at least 7u), so at the default 18u the rows are still stacked; they switch to side by side as soon as the column is dragged past 20u (screenshots `v5_mesh_side_by_side_font*.png` show 24u). Say if the default should be 20u instead.
31. **Monitors column** default width is now 25 % of the window (was 34.7 % measured on the mockup) so that the viewer keeps at least 50 % at 78u next to the 18u sidebar (tests for fonts 11, 14 and 18).

## Layer metric, section contrast, slider, test speed

32. **Layer warning** uses both numbers per patch: layers present / target (from snappy's "mesh" layers column, an average) and the achieved thickness percentage; either below 80 % warns. They are shown as "2.1 / 3 (70 %), thickness 64 %".
33. **Section look.** Cells use `mesh_edge` (#526077) over `mesh_surface` (#1A202C); framing is the parts' box plus 0.3 part extents, which makes the three prism layers visible as parallel bands along the wall at the default zoom (checked at 1:1 pixels on a 1 m sphere; they are 3-4 px thick).
34. **Slider.** Dragging re-slices at most every 150 ms (leading edge, then trailing flushes) and once more on release; keyboard and programmatic changes slice at once.
35. **Test speed.** The big slowdown was windows never being destroyed between tests (pytest-qt only calls deleteLater and nothing ran the deferred deletes), so each test got slower; an autouse fixture now flushes them. pytest-xdist is added as a dev dependency: `-n 8` passed the full suite 6 times (offscreen and real display) with the Qt and OpenFOAM tests; each worker builds its own session sphere mesh (tmp_path_factory), QSettings are per-test temp dirs, so nothing is shared. `scripts/ship.sh` still runs the plain single-process offscreen suite.
