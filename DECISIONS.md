# DECISIONS.md

Decision records. One entry per decision below the index; an entry is never deleted: when a decision
changes, the old entry is marked "Superseded by D-xxx" and a new entry is added (or, for an entry
still under review, it is updated in place and the change is noted in it).

Status values: **Accepted**; **Proposed** (recorded on a task branch, pending review before the
branch is published); **Superseded by D-xxx**.

Dates are the date of the commit that recorded the decision (D-022 to D-027 previously carried
2026-10-17 / 2026-10-18, later than the commits that added them on 2026-10-16). Entries D-028 to
D-036 were backfilled on 2026-10-17 from docs/QUESTIONS.md items that were published through a
reviewed pull request. "Context: not recorded" means the repository does not show why.

## Index

| ID | Date | Title | Status |
|---|---|---|---|
| D-001 | 2026-10-15 | OpenFOAM ESI v2606 only | Accepted |
| D-002 | 2026-10-15 | Run inside WSL2 with WSLg | Accepted |
| D-003 | 2026-10-15 | Three-layer package structure | Accepted |
| D-004 | 2026-10-15 | OpenFOAM always launched through explicit sourcing | Accepted |
| D-005 | 2026-10-15 | Results stored as standard OpenFOAM cases | Accepted |
| D-006 | 2026-10-15 | Project file: JSON, pydantic, schema_version | Accepted |
| D-007 | 2026-10-15 | License GPL-3.0-or-later | Accepted |
| D-008 | 2026-10-15 | foamlib behind foam/dictfile.py | Accepted |
| D-009 | 2026-10-15 | Clean stop via controlDict stopAt writeNow | Superseded by D-010 |
| D-010 | 2026-10-15 | Clean stop via SIGUSR1 and stopAtWriteNowSignal | Accepted |
| D-011 | 2026-10-15 | Undo/redo as snapshots in core/project.py | Accepted |
| D-012 | 2026-10-15 | Project renamed to VortexCFD | Accepted |
| D-013 | 2026-10-16 | Design tokens, Fusion style, icons drawn in code | Accepted |
| D-014 | 2026-10-16 | Owner palette "Tungsten & Amber" and layout proportions | Superseded by D-041 |
| D-015 | 2026-10-16 | Sidebar layout with stage and view pills | Superseded by D-016 |
| D-016 | 2026-10-16 | Layout follows the mockup; no fake data | Superseded by D-039, D-041 |
| D-017 | 2026-10-16 | Imported surfaces copied into the project | Accepted |
| D-018 | 2026-10-16 | geometry/ layer | Accepted |
| D-019 | 2026-10-16 | Far-field domain box from multipliers of L | Accepted |
| D-020 | 2026-10-16 | Schema v2 adds the domain, with migration | Accepted |
| D-021 | 2026-10-16 | Marker-protected meshing case, background runs | Accepted; results part extended by D-051 |
| D-022 | 2026-10-16 | External-aerodynamics BCs and motorBike numerics | Accepted |
| D-023 | 2026-10-16 | Inlet turbulence from intensity and viscosity ratio | Accepted |
| D-024 | 2026-10-16 | y+ estimator and absolute layer sizing | Accepted |
| D-025 | 2026-10-16 | Validation marker and policy | Accepted |
| D-026 | 2026-10-16 | Layer count from the y+ first layer | Accepted; minTetQuality part superseded by D-044 |
| D-027 | 2026-10-16 | Residual targets as SIMPLE residualControl | Accepted |
| D-028 | 2026-10-16 | Part patch names | Accepted |
| D-029 | 2026-10-16 | Regions tree layout | Accepted |
| D-030 | 2026-10-16 | snappyHexMesh case conventions | Accepted |
| D-031 | 2026-10-16 | foam/ and geometry/ do not import each other | Accepted |
| D-032 | 2026-10-16 | Layer coverage metric and warning | Accepted |
| D-033 | 2026-10-16 | Mesh staleness and persistence | Accepted |
| D-034 | 2026-10-16 | Properties panel and column defaults | Accepted |
| D-035 | 2026-10-16 | Mesh Scene section plane | Accepted |
| D-036 | 2026-10-16 | Flat plate validation cases and criterion | Accepted (updated 2026-10-17) |
| D-037 | 2026-10-17 | Workflow: task branches, ship.sh run only by Vic | Accepted |
| D-038 | 2026-10-17 | Review of numerics; validation failures are reported | Accepted |
| D-039 | 2026-10-17 | No fake data in the UI | Accepted |
| D-040 | 2026-10-17 | Branding | Accepted |
| D-041 | 2026-10-17 | Visual language: owner palette and mockup layout | Accepted |
| D-042 | 2026-10-17 | Meshing defaults | Accepted |
| D-043 | 2026-10-17 | Test conventions | Accepted |
| D-044 | 2026-10-17 | minTetQuality relaxed only in `relaxed` | Accepted; nRelaxedIter part superseded by D-045 |
| D-045 | 2026-10-17 | Relaxed controls from the first layer iteration for y+ layers | Accepted |
| D-046 | 2026-10-17 | Running the solver: run states, run record, results staleness | Accepted |
| D-047 | 2026-10-17 | Reference values for the force coefficients (schema v4) | Accepted (with the A_ref basis) |
| D-048 | 2026-10-17 | Live residuals and report slots | Accepted (face-weighted y+ average) |
| D-049 | 2026-10-17 | Residual chart palette | Accepted |
| D-050 | 2026-10-17 | forceCoeffs projection checked against a forces function object | Accepted |
| D-051 | 2026-10-17 | A new mesh deletes the previous results | Accepted |
| D-052 | 2026-10-17 | Lost-part guard, thin-part warning, per-part levels and seed lines (schema v5) | Accepted (automatic seeding) |
| D-053 | 2026-10-17 | Results Scene | Accepted (wrapping strip, upstream view) |
| D-054 | 2026-10-17 | Colormaps from matplotlib | Accepted |
| D-055 | 2026-10-17 | Open in ParaView | Accepted |
| D-056 | 2026-10-17 | Inward-normals warning at import | Accepted |
| D-057 | 2026-10-17 | Status bar: messages left, selection right | Accepted |

---

## D-001 OpenFOAM ESI v2606 only
- Status: Accepted
- Context: docs/PLAN.md listed the OpenFOAM flavour (ESI vs Foundation) as an open decision blocking Phase 1.
- Decision: support OpenFOAM ESI v2606 only, installed at /usr/lib/openfoam/openfoam2606.
- Alternatives considered: OpenFOAM Foundation (openfoam.org); supporting several versions through an adapter layer (PLAN 1.2).
- Consequences: no flavour adapter is needed; keywords follow the v2606 tutorials.

## D-002 Run inside WSL2 with WSLg
- Status: Accepted
- Context: OpenFOAM is Linux software and the owner works on Windows 11.
- Decision: the whole application runs in WSL2 Ubuntu 24.04 and displays through WSLg.
- Alternatives considered: not recorded (a Windows GUI driving a Linux solver across file systems is implied by the reason).
- Consequences: no cross-OS path translation; rendering relies on Mesa d3d12 (see the GPU debt in docs/STATUS.md).

## D-003 Three-layer package structure
- Status: Accepted
- Context: simulation logic must run headless (tests, scripts) without Qt.
- Decision: core/, foam/ and gui/ layers; core and foam never import Qt, pyvista or vortexcfd.gui (tests/test_layers.py). Extended by D-018 and D-031.
- Alternatives considered: not recorded.
- Consequences: headless pipeline tests; GUI-free automation is possible.

## D-004 OpenFOAM always launched through explicit sourcing
- Status: Accepted
- Context: OpenFOAM is not on PATH and the user's shell environment varies.
- Decision: every OpenFOAM process goes through vortexcfd.foam.runner, which sources /usr/lib/openfoam/openfoam2606/etc/bashrc.
- Alternatives considered: not recorded.
- Consequences: deterministic execution independent of the user's shell.

## D-005 Results stored as standard OpenFOAM cases
- Status: Accepted
- Context: Task 0.6 (ParaView decision).
- Decision: no application-specific result format; every case can be opened in ParaView.
- Alternatives considered: not recorded.
- Consequences: the in-app viewer is a convenience; an "Open in ParaView" button is planned for Phase 6.

## D-006 Project file: JSON, pydantic, schema_version
- Status: Accepted
- Context: Task 1.1 (data model, PLAN 1.1 requires versioning and migration).
- Decision: JSON project files validated with pydantic, carrying schema_version, with a migration hook.
- Alternatives considered: YAML (PLAN 1.1 mentions JSON/YAML); not otherwise recorded.
- Consequences: human-readable files; migrations in core/project_io.py (D-020, schema v3 in Task 4A).

## D-007 License GPL-3.0-or-later
- Status: Accepted
- Context: the foamlib runtime dependency is GPLv3.
- Decision: VortexCFD is GPL-3.0-or-later.
- Alternatives considered: not recorded.
- Consequences: dependencies must be GPL-3 compatible (docs/reference/oss_survey.md).

## D-008 foamlib behind foam/dictfile.py
- Status: Accepted
- Context: Task 1.2 (case writer).
- Decision: read and write OpenFOAM dictionaries with foamlib, only through foam/dictfile.py.
- Alternatives considered: not recorded.
- Consequences: the parser can be replaced in one place.

## D-009 Clean stop via controlDict stopAt writeNow
- Status: Superseded by D-010
- Context: Task 1.3b; a stop must leave a restartable time directory.
- Decision: stop by rewriting system/controlDict with stopAt writeNow.
- Alternatives considered: signals (adopted later in D-010).
- Consequences: measured to be delayed about 5 s by fileModificationSkew (docs/notes/clean-stop-measurements.md).

## D-010 Clean stop via SIGUSR1 and stopAtWriteNowSignal
- Status: Accepted (supersedes D-009)
- Context: measurements in docs/notes/clean-stop-measurements.md: the file-based stop is ignored for about 5 s after start (fileModificationSkew 5).
- Decision: the case controlDict enables stopAtWriteNowSignal and FoamRun sends SIGUSR1 (Task 1.3e).
- Alternatives considered: controlDict edit (D-009); controlDict edit with fileModificationSkew 0 (also about 0.01 s, but mutates case files).
- Consequences: stop latency about 0.01 s without touching case files; single-process runs only (parallel runs: see docs/STATUS.md).

## D-011 Undo/redo as snapshots in core/project.py
- Status: Accepted
- Context: Task 2.1a.
- Decision: snapshots of the validated Simulation instead of QUndoStack.
- Alternatives considered: QUndoStack.
- Consequences: undo works headless and from scripts; the document stays Qt-free.

## D-012 Project renamed to VortexCFD
- Status: Accepted
- Context: final name chosen before the GUI and public API grew.
- Decision: product VortexCFD, Python package vortexcfd. Branding rules: D-040.
- Alternatives considered: not recorded.
- Consequences: package renamed in one commit (665c2f9).

## D-013 Design tokens, Fusion style, icons drawn in code
- Status: Accepted
- Context: Task 2.1c.
- Decision: design tokens in gui/theme.py, Qt Fusion style, tree icons drawn in code, no bundled image assets.
- Alternatives considered: not recorded.
- Consequences: one place to change colours; nothing to license or package.

## D-014 Owner palette "Tungsten & Amber" and layout proportions
- Status: Superseded by D-041
- Context: Task 2.1c; the owner defines the visual identity.
- Decision: dark-only palette "Tungsten & Amber" and layout proportions (tree 14u, properties 17u, viewer stretch), fixed by the owner.
- Alternatives considered: not recorded.
- Consequences: the proportions changed later (D-034); the palette rule continues in D-041.

## D-015 Sidebar layout with stage and view pills
- Status: Superseded by D-016
- Context: Task 2.1c, the owner's first layout reference.
- Decision: left sidebar, stage and view pills in strips above/below the viewer, collapsible property cards; no widgets overlaid on the OpenGL viewer.
- Alternatives considered: pills overlaid on the viewer (unreliable under WSLg).
- Consequences: replaced by the mockup-based layout.

## D-016 Layout follows the mockup; no fake data
- Status: Superseded by D-039 (no fake data) and D-041 (layout)
- Context: the owner supplied the target design, docs/design/mockup-v1.png (named design_preview.png until 2026-10-17).
- Decision: top bar, tree and properties left, scene tabs and viewer, monitors right, console bottom; no fake data; controls for missing features omitted or disabled with a phase tooltip.
- Alternatives considered: the sidebar layout of D-015.
- Consequences: the rules continue unchanged in D-039 and D-041.

## D-017 Imported surfaces copied into the project
- Status: Accepted
- Context: Task 3.1.
- Decision: imported surface files are copied into <project dir>/geometry/ and referenced by a path relative to the project file.
- Alternatives considered: referencing the original file (breaks when it moves or changes).
- Consequences: projects are self-contained and movable.

## D-018 geometry/ layer
- Status: Accepted
- Context: surface loading and checks need VTK but must stay usable headless.
- Decision: src/vortexcfd/geometry/ may import numpy and pyvista, not Qt, pyvistaqt or vortexcfd.gui; core must not import it (tests/test_layers.py).
- Alternatives considered: not recorded.
- Consequences: see also D-031 (foam and geometry are independent).

## D-019 Far-field domain box from multipliers of L
- Status: Accepted
- Context: Task 3.4.
- Decision: box domain from multipliers of the reference length L (largest extent of the union of the parts' boxes); flow along +x; angle of attack through the inlet velocity direction.
- Alternatives considered: absolute domain sizes (break when parts change size or units).
- Consequences: inlet at x_min and outlet at x_max are unambiguous.

## D-020 Schema v2 adds the domain, with migration
- Status: Accepted
- Context: Task 3.4.
- Decision: schema v2 adds `domain`; v1 files are migrated with the default domain; newer versions are rejected.
- Alternatives considered: not recorded.
- Consequences: the migration hook is the single upgrade point (schema v3 added the physics in Task 4A).

## D-021 Marker-protected meshing case, background runs
- Status: Accepted (the results part is extended by D-051: a successful Generate Mesh also deletes the previous solver results)
- Context: Task 5.1.
- Decision: the meshing case lives in <project dir>/case with a marker file .vortexcfd-case; regeneration replaces only constant/polyMesh and generated dictionaries and refuses a non-empty directory without the marker; meshing steps run through FoamRun in the background and reach the GUI only through Qt signals.
- Alternatives considered: not recorded.
- Consequences: user files are never deleted; long runs do not freeze the GUI.

## D-022 External-aerodynamics BCs and motorBike numerics
- Status: Accepted (reviewed 2026-10-17 in the review chat; was Proposed on task/4a-physics, docs/QUESTIONS.md item 37)
- Context: Task 4A, steady incompressible kOmegaSST.
- Decision: inlet fixedValue U/k/omega, p zeroGradient; outlet p fixedValue 0, U/k/omega inletOutlet; sides/top/bottom slip (nut calculated, as the motorBike tutorial); symmetry symmetryPlane; part walls noSlip, kqRWallFunction, omegaWallFunction, nutUSpaldingWallFunction. Schemes and solution settings: motorBike tutorial (preset "robust").
- Alternatives considered: the tutorial's nutkWallFunction (not valid down to y+ about 1).
- Consequences: behaves like a known-good tutorial case. The k wall BC sensitivity is studied in docs/validation/flat_plate/README.md.

## D-023 Inlet turbulence from intensity and viscosity ratio
- Status: Accepted (reviewed 2026-10-17 in the review chat)
- Context: Task 4A.
- Decision: k = 1.5 (V I)^2, omega = k / (nu ratio).
- Alternatives considered: raw k and omega (the motorBike tutorial's fixed values).
- Consequences: the user enters the two numbers an engineer knows.

## D-024 y+ estimator and absolute layer sizing
- Status: Accepted (reviewed 2026-10-17 in the review chat)
- Context: Task 4A.
- Decision: first cell height from Cf = 0.026 / Re^(1/7) (y = y+ nu / u*); with layer_sizing "absolute_yplus" snappyHexMesh uses relativeSizes false with that firstLayerThickness and the reused expansion ratio.
- Alternatives considered: not recorded.
- Consequences: measured y+ on the flat plate is within 6 % of the estimate (docs/validation/flat_plate/README.md). Guidance (added 2026-10-17): the flat-plate verification gives Cf about 6 % low at y+ 1 and about 3.6 % low at y+ 0.5 against the TMR SST reference (docs/validation/flat_plate); the Mesh properties show this as a muted note under Target y+ when the layer sizing is absolute y+.

## D-025 Validation marker and policy
- Status: Accepted (confirmed by D-043)
- Context: validation runs real OpenFOAM cases and takes minutes.
- Decision: validation tests carry the `validation` marker, are skipped unless selected with `-m validation`, are excluded from scripts/ship.sh and are run explicitly after every change to physics or numerics; results live in docs/validation/.
- Alternatives considered: running them as a merge gate (too slow and sensitive).
- Consequences: a numerics change must be accompanied by a validation run.

## D-026 Layer count from the y+ first layer
- Status: Accepted (layer count confirmed by D-042). The minTetQuality part is superseded by D-044.
- Context: Task 4A; thin y+ layers on coarse surfaces collapse.
- Decision: with absolute y+ sizing, n = ceil(ln(0.5 h / t1) / ln r) + 1 clamped to [1, 30] (t1 first layer, r expansion, h surface cell size); the Mesh panel and Generate Mesh warn when 30 layers do not reach 0.5 h. For this sizing minTetQuality is set to -1e30.
- Alternatives considered: a user-entered layer count.
- Consequences: layers blend into the volume cells without the user counting them.

## D-027 Residual targets as SIMPLE residualControl
- Status: Accepted (reviewed 2026-10-17 in the review chat; docs/QUESTIONS.md item 38)
- Context: Task 4A.
- Decision: Solvers settings carry residual targets (p 1e-4; U, k, omega 1e-5) written as SIMPLE residualControl; the validation cases use the same mechanism.
- Alternatives considered: a fixed iteration count.
- Consequences: runs stop when converged.

## D-028 Part patch names
- Status: Accepted (published in PR #11; from docs/QUESTIONS.md items 2 and 20)
- Context: OpenFOAM patch names must be valid words and unique.
- Decision: a part's patch is its name with every character outside [A-Za-z0-9_] replaced by `_` (case kept); a collision with a domain boundary name (inlet, outlet, sides, top, bottom, symmetry) or another part gets the first free numeric suffix (`_1`, `_2`, ...). The tree shows the original part name; the Part properties show the patch name read-only.
- Alternatives considered: not recorded.
- Consequences: patch names are stable and never clash with the far-field patches.

## D-029 Regions tree layout
- Status: Accepted (published in PR #11; item 3)
- Context: Task 3.4.
- Decision: Regions > Fluid Domain > inlet, outlet, sides, top, bottom, (symmetry), then one "<part> (wall)" node per part; with the domain disabled only the walls remain.
- Alternatives considered: not recorded.
- Consequences: boundary and wall nodes carry no properties yet.

## D-030 snappyHexMesh case conventions
- Status: Accepted (published in PR #11; items 7 to 11)
- Context: Task 5.1.
- Decision:
  - checkMesh runs without -allGeometry -allTopology; the report keeps cells, faces, points, max/avg non-orthogonality, max skewness and the failed-check count; a mesh with failed checks is still shown, as a warning.
  - surfaceFeatureExtract on every part STL with includedAngle = 180 - feature_angle; feature level = surface_level_max; resolveFeatureAngle = feature_angle.
  - locationInMesh upstream of the parts' box, midway to the inlet, at cell fractions (0.34, 0.41, 0.28) of the background cell (at least 0.027 of a cell from every face up to level 4).
  - one nSurfaceLayers entry per part (regex "<part>.*"); layers = 0 switches the layer step off (addLayers no).
  - Generate Mesh requires every part file to exist.
- Alternatives considered: not recorded.
- Consequences: deterministic dictionaries from the project.

## D-031 foam/ and geometry/ do not import each other
- Status: Accepted (published in PR #11; item 15)
- Context: foam/ must not depend on pyvista; geometry/ must not depend on OpenFOAM.
- Decision: estimate_mesh takes the domain bounds and L as plain data; orchestration joining core, geometry and foam lives in gui/meshing.py (Qt-free); tests/test_layers.py forbids foam -> geometry and geometry -> foam.
- Alternatives considered: passing a DomainBox into foam/ (would import geometry/).
- Consequences: both layers stay usable on their own.

## D-032 Layer coverage metric and warning
- Status: Accepted (published in PR #11 and PR #12; items 18 and 32)
- Context: snappyHexMesh prints no per-patch count of faces that received layers.
- Decision: per patch, both the average layers present / target (snappy's "mesh" column) and the achieved thickness percentage are shown ("2.1 / 3 (70 %), thickness 64 %"); either below 80 % warns (colour and console WARNING). The overall share of extruded faces (last "Extruding N out of M faces") is shown separately.
- Alternatives considered: thickness percentage alone (item 18, refined by item 32).
- Consequences: a partly collapsed layer stack is visible in the Mesh properties.

## D-033 Mesh staleness and persistence
- Status: Accepted (published in PR #11; item 19, superseding item 6)
- Context: Task 5.1.
- Decision: a "Mesh out of date" badge (next to Saved/Modified), a Status row in the Mesh properties and a VTK text in the Mesh Scene. The hash covers part names, units, part file contents, the domain and the mesh settings (not the project name, view settings or coverage threshold). The last report is stored in case/vortexcfd_mesh.json and shown when the project is opened, even if case/polyMesh was deleted.
- Alternatives considered: not reloading meshes at open (item 6, the earlier behaviour).
- Consequences: the user always sees whether the mesh matches the inputs.

## D-034 Properties panel and column defaults
- Status: Accepted (published in PR #11 and PR #12; items 22 to 24, 30 and 31). Whether the left column should default to 20u is still open (docs/QUESTIONS.md item 30).
- Context: readability of the properties at fonts 11 to 18.
- Decision: left column starts at 18u (min 14u, max 28u); tree / properties split 40 % / 60 % (user drag stored in QSettings layout/left_tree_fraction); monitors column 25 % of the window so the viewer keeps at least 50 %; property rows go side by side when the panel is at least 20u wide (label column clamped to [8u, 50 %], field at least 7u), otherwise they stack; domain size text uses three significant digits.
- Alternatives considered: the mockup's measured proportions (tree split 0.548, monitors 34.7 %).
- Consequences: at the default 18u the rows are stacked.

## D-035 Mesh Scene section plane
- Status: Accepted (published in PR #12; items 27 to 29, 33 and 34)
- Context: Task 5.1 follow-up (section plane through the volume mesh).
- Decision: cut cells in mesh_edge over mesh_surface; framing = parts' box plus 0.3 part extents; the camera looks from the plane's negative side and part walls are clipped behind the plane; default plane normal +y through the centre of the part patches (with symmetry: the symmetry plane nudged 0.2 % of the domain inside); changing the normal resets the offset; controls in their own strip under the scene tabs (Mesh Scene only); domain boundary patches translucent in border_active, off by default; slider re-slices at most every 150 ms while dragging and once on release.
- Alternatives considered: part_edge over elevated (item 26: low contrast).
- Consequences: prism layers are visible as bands at the default zoom on a 1 m sphere.

## D-036 Flat plate validation cases and criterion
- Status: Accepted (updated 2026-10-17: reference changed from White's law to the NASA TMR SST results, decided in the review chat; docs/QUESTIONS.md items 39 and 40)
- Context: PLAN validation policy: turbulence setup logic is validated on a flat plate (Cf, y+). The first Case B failed a 5 % criterion against White's law (Cf(0.97) = 2.556e-3, -11 %). The TMR SST page shows the case is a VERIFICATION case and that verified codes are themselves 5-7 % below White's law at x = 0.97, so White is not a valid pass/fail reference for SST. docs/validation/flat_plate/README.md.
- Decision: Case A (U = 10 m/s, Re_L = 1.3e6) is informative only. Case B (TMR 2D zero pressure gradient flat plate, Re = 5e6 per metre, plate 0 to 2 m) is the arbiter: a wall-normal grid study on three nested grids (first-cell y+ about 1, 0.5, 0.25, at least 30 cells across the boundary layer), Cf(x = 0.97) extrapolated with the Celik GCI procedure, compared with the TMR incompressible SST reference (2.7214e-3, tests/data/tmr/). Bands: |error| <= 3 % PASS; 3-5 % PASS WITH NOTE (citing the TMR note on OpenFOAM's SST implementation); > 5 % FAIL. The validation test asserts the recorded band (a strict xfail only for FAIL). White's law and the TMR Cf(x) distribution are informative. The y+ estimator must be within 30 % at mid-plate. Split in two: the full study (three grids, GCI, TMR distribution, optional k wall BC diagnostic) is `scripts/validation/flat_plate_study.py` (about 80 min, 2 h with --k-wall; writes the Case B files and the README tables, committed); the pytest `validation` test runs Case A and the coarse and medium grids only (about 20 min) and asserts the medium grid within 5 % of the reference, a decreasing error from coarse to medium, reproduction of the committed study within 0.1 %, and the recorded verdict band with the committed finest grid.
- Alternatives considered: White's law 0.455 / ln^2(0.06 Re_x) with mean <= 5 % / max <= 8 % (the first criterion); the power law 0.0592 Re_x^-0.2.
- Consequences: result of 2026-10-17: extrapolated Cf(0.97) = 2.6314e-3 (GCI 0.035 %), -3.31 %: PASS WITH NOTE. After a numerics change the full study must be re-run and its results committed, or the pytest reproduction check fails.

## D-037 Workflow: task branches, ship.sh run only by Vic
- Status: Accepted
- Context: decided in the review chat; agents implement, Vic reviews and publishes.
- Decision: one branch per task, named task/<id>. Agents commit locally on the task branch and never push, merge or delete branches. Only Vic runs scripts/ship.sh, which runs the full test suite offscreen excluding the `validation` marker and publishes through a pull request.
- Alternatives considered: not recorded.
- Consequences: nothing reaches main without Vic's review; CLAUDE.md carries the agent rules.

## D-038 Review of numerics; validation failures are reported
- Status: Accepted
- Context: decided in the review chat.
- Decision: tasks touching numerics, boundary conditions, turbulence or meshing carry [NUMERICS-REVIEW] and need Vic's explicit approval before publishing. Validation failures are reported, never fixed by tuning the app's numerics.
- Alternatives considered: not recorded.
- Consequences: a failed validation is a finding to review, and the validation test records it (xfail) instead of hiding it.

## D-039 No fake data in the UI
- Status: Accepted (continues the rule of D-016)
- Context: decided in the review chat; the mockup's numbers are placeholders.
- Decision: every value shown is real or an explicit empty state; features not built yet are omitted or disabled with a tooltip naming the phase.
- Alternatives considered: not recorded.
- Consequences: placeholder text and numbers from the mockup never reach the screen.

## D-040 Branding
- Status: Accepted
- Context: decided in the review chat.
- Decision: the app is VortexCFD; the Simcenter, STAR-CCM+ and Siemens names and logos are never used in the product.
- Alternatives considered: not recorded.
- Consequences: the GUI shows none of these names. Since 2026-10-17 the pyproject.toml description and the package docstring read "Integrated CFD workflow GUI for OpenFOAM"; "STAR-CCM+-style" stays only in the internal planning docs ARCHITECTURE.md and docs/PLAN.md (docs/QUESTIONS.md item 44).

## D-041 Visual language: owner palette and mockup layout
- Status: Accepted (supersedes D-014 and the layout part of D-016)
- Context: decided in the review chat; the owner defines the visual identity.
- Decision: palette "Tungsten & Amber" fixed by the owner, values asserted in tests/test_theme.py; layout follows the owner's mockup docs/design/mockup-v1.png (renamed from design_preview.png on 2026-10-17, docs/QUESTIONS.md item 45). Owner values change only on his request.
- Alternatives considered: not recorded.
- Consequences: agents do not tune colours or proportions on their own (current proportions: D-034).

## D-042 Meshing defaults
- Status: Accepted (includes docs/QUESTIONS.md items 16 and 17)
- Context: decided in the review chat.
- Decision: the background mesh is sized from a cell budget (100,000 cells); surface refinement from a target surface size of 0.01 L; Generate Mesh is blocked above 2,000,000 background cells (tooltip; warning colour in the Mesh properties); with absolute sizing the layer count is derived from the target y+ (D-026). base_size and surface_level_min/max are optional overrides (None = computed, shown as "auto"; setting only the max gives min = max - 1).
- Alternatives considered: not recorded.
- Consequences: a default domain around a 1 m object gives base 0.269 m, levels 4-5, surface cells 8.4 mm. Only background cells are estimated (debt in docs/STATUS.md).

## D-043 Test conventions
- Status: Accepted (includes docs/QUESTIONS.md items 12 and 35)
- Context: decided in the review chat; the suite had become slow because Qt widgets were never destroyed.
- Decision: markers `slow` (above about 5 s) and `validation` (D-025); validation runs explicitly per numerics change; an autouse fixture flushes pending Qt deferred deletes between tests; pytest-xdist is allowed for local runs (`-n 8`); scripts/ship.sh runs the plain single-process offscreen suite. No pytest-timeout: OpenFOAM tests bound their waits (MeshRun step_timeout_s, wait()/waitUntil() <= 120 s).
- Alternatives considered: pytest-timeout (not installed, no new dependencies).
- Consequences: iterate with `-m "not slow and not validation"`; run the full suite offscreen and on the real display before each commit.

## D-044 minTetQuality relaxed only in `relaxed`
- Status: Accepted (supersedes the minTetQuality part of D-026; decided in the review chat, docs/QUESTIONS.md item 41). The nRelaxedIter 20 part is superseded by D-045.
- Context: D-026 set minTetQuality -1e30 in the main meshQualityControls for absolute y+ layers, which relaxed the tet-quality check for snapping and every layer iteration.
- Decision: the main meshQualityControls keep the install's etc/caseDicts/meshQualityDict values (minTetQuality 1e-15) for every sizing. With absolute y+ layers, only the `relaxed` sub-dictionary sets minTetQuality -1e30, and addLayersControls sets nRelaxedIter 20 (the value of the annotated v2606 snappyHexMeshDict; v2606's default, labelMax, never switches to `relaxed`).
- Alternatives considered: minTetQuality -1e30 in the main controls (D-026); not relaxing at all.
- Consequences: on the coarse test sphere at y+ 30 (13 layers) the layer iterations converge at iteration 11, before nRelaxedIter, so the relaxed controls never apply: coverage 1.74 / 13 layers (13 %), thickness 44.7 %, 68.5 % of faces extruded; checkMesh OK. Not relaxed further; the test is a strict xfail and the options are in docs/QUESTIONS.md item 46.

## D-045 Relaxed controls from the first layer iteration for y+ layers
- Status: Accepted (reviewed and approved in the review chat on 2026-10-17; supersedes the nRelaxedIter part of D-044; docs/QUESTIONS.md item 46)
- Context: with nRelaxedIter 20 (D-044) the layer iterations on the coarse test sphere at y+ 30 (13 layers) converged at iteration 11, before the relaxed controls applied: 13 % of the layers, thickness 44.7 %. The same case with nRelaxedIter 0 gave 100 % with checkMesh "Mesh OK".
- Decision: with layer_sizing "absolute_yplus", addLayersControls writes nRelaxedIter 0, so the layer addition uses the `relaxed` meshQualityControls (only minTetQuality -1e30) from its first iteration while snapping keeps the main (install meshQualityDict) controls. Relative sizing writes no nRelaxedIter and keeps the motorBike tutorial set-up (v2606 default: never relaxed).
- Alternatives considered: nRelaxedIter 20 (D-044, low coverage); an intermediate value such as 5; relaxing the main controls (D-026, also loosens snapping).
- Consequences: the y+ 30 test sphere gets 13 / 13 layers (100 %), thickness 100 % (26.2 mm), 100 % of the faces extruded, checkMesh "Mesh OK" (286820 cells, max non-orthogonality 41.3, max skewness 0.652); the test asserts coverage >= 80 % (both metrics) and "Mesh OK" instead of a strict xfail. checkMesh still judges every final mesh.

## D-046 Running the solver: run states, run record, results staleness
- Status: Accepted (reviewed 2026-10-17 in the review chat; recorded as Proposed on task/4a-physics). The old results left by Generate Mesh are now deleted by D-051.
- Context: Task 4B.1 runs simpleFoam from the GUI on the meshed case.
- Decision:
  - Run Solver is enabled when the project is saved, no meshing is running, a mesh exists (case/vortexcfd_mesh.json loaded), the mesh is not out of date (D-033) and the physics is valid; otherwise it is disabled with the reason as tooltip ("Save the project first.", "Meshing is running.", "Generate the mesh first.", "The mesh is out of date: generate it again.", or the physics problem). "Physics valid" means: the Simulation validates again (a project edited outside the Project API) and the forceCoeffs reference length and area are positive (a flat part with no y extent has a zero bounding-box area). While the solver runs Generate Mesh is disabled ("The solver is running: stop it first.").
  - Running writes the solver files (foam/physics_case.py) with enable_clean_stop into <project dir>/case, which must carry the meshing marker (D-021). Before writing, the previous run's outputs are removed: time directories after 0, postProcessing/, 0/ (rewritten), log.simpleFoam and case/vortexcfd_run.json; constant/polyMesh and the mesh dictionaries' outputs are never touched. simpleFoam runs through FoamRun(clean_stop=True) on a worker thread (foam/solver_run.py); lines and completed iterations reach the GUI only through Qt signals (gui/solver_worker.py). Stop is FoamRun.request_stop (SIGUSR1, then SIGTERM and SIGKILL).
  - End states from the exit code and the LogParser events, in this order: "Crashed" (a stack-trace or FOAM FATAL block, printed in the console in the error colour), "Stopped" (the user stopped it, or a timeout), "Crashed" (any other non-zero exit code), "Converged" ("SIMPLE solution converged in N iterations", i.e. residualControl reached; new LogParser event `Converged`), otherwise "Iteration limit". While running the state badge shows "Solving".
  - case/vortexcfd_run.json keeps the state, iterations, the last initial residual of every solved field, the exit code and a results hash: the mesh inputs hash (D-033) plus the physics, inflow, solver and report settings. It is loaded when the project is opened. When the hash no longer matches, a "Results out of date" badge is shown next to the mesh badge and the Solvers node's Last run status says so.
- Alternatives considered: restarting from the latest time (needs a restart decision and a mapping when the mesh changed); keeping old time directories (ParaView would show results of an earlier set-up next to the new ones).
- Consequences: every run starts from 0 with a clean case. Parallel runs are still not supported (D-010).

## D-047 Reference values for the force coefficients (schema v4)
- Status: Accepted (reviewed 2026-10-17 in the review chat, [NUMERICS-REVIEW]; updated in the same review with the A_ref basis, docs/QUESTIONS.md item 49)
- Context: forceCoeffs needs magUInf, lRef, Aref and a centre of rotation; Task 4A wrote the bounding-box values with no way to change them. The v2606 forceCoeffs reads, with CofR, liftDir as e3 and dragDir as e1 of the coefficient axes and takes the pitch axis as e2 = e3 x e1 (+y at any angle of attack); the `pitchAxis` keyword is not read (src/functionObjects/forces/forces/forces.C setCoordinateSystem, forceCoeffs.C). Output: postProcessing/forceCoeffs1/<start time>/coefficient.dat, columns Time then Cd, Cd(f), Cd(r), Cl, Cl(f), Cl(r), CmPitch, CmRoll, CmYaw, Cs, Cs(f), Cs(r) (checked on a real run, tests/data/sphere_run/).
- Decision: a "Reference Values" node under Reports & Monitors shows rho_ref (Physics.rho_ref, editable there too), U_ref (the inflow speed, read-only), A_ref, l_ref and CofR. A_ref has a basis (`Reports.reference_area_basis`): "planform" (bounding box x * y, the default), "frontal" (bounding box y * z) or "custom" (`Reports.reference_area`, set exactly for custom; choosing custom starts from the area in use). l_ref and CofR are optional overrides (reference_length, center_of_rotation; None = auto: l_ref = x extent, CofR = the box centre of the union of the parts' bounding boxes). The auto labels state the basis exactly ("auto: bounding-box planform, x * y", "auto: bounding-box frontal, y * z", "auto: bounding-box length, x extent", "auto: bounding-box centre"), with the muted note "set the wing area and mean chord for aircraft". The basis was added inside schema v4 (unpublished); a v4 file with only reference_area reads as custom. forceCoeffs uses the resolved values. Schema v4 also adds `Reports.slots` (D-048); v3 files migrate with all overrides unset and empty slots (hand-written fixture tests/data/project_v3.json). Reference values are results inputs (D-046 hash); the slot choice is not.
- Alternatives considered: frontal area as the only default (wrong for wings); a single override without a basis (the first version of this entry); no defaults (Run Solver blocked until the user enters them).
- Consequences: a bluff body uses the frontal basis (the default sphere: planform 0.995 m2, frontal about 0.99 m2 for its box; a true pi r^2 = 0.785 m2 needs custom). A flat part with a zero auto area or length blocks Run Solver until A_ref / l_ref is set (D-046).

## D-048 Live residuals and report slots
- Status: Accepted (reviewed 2026-10-17 in the review chat; updated in the same review: the y+ average across walls is face-count weighted, docs/QUESTIONS.md item 51)
- Context: the monitors column had empty states only (D-039).
- Decision: the residual chart plots the initial residual of every solved field per iteration (the first solve of the field in the iteration), log10 y axis whose decades widen to fit the data (at least 1e0..1e-6), iteration on x always ending at the latest iteration (autoscroll), one line per field, a legend row above the plot, and at most about 2000 points per series (min/max bucket decimation, first and last points kept). Iterations arrive through the SolverWorker step signal. The report slot chevron opens a menu: Not assigned, Cd, Cl, Cm (pitch) (forceCoeffs columns Cd, Cl, CmPitch) and y+ min / avg / max on the walls (yPlus function object, postProcessing/yPlus1/<start time>/yPlus.dat: over all wall patches the minimum of the minima, the maximum of the maxima, and the average weighted by each patch's face count from constant/polyMesh/boundary, i.e. the mean over all wall faces; checked against the yPlus field of a real two-wall run, tests/data/two_walls/). The assignment is saved in the project (Reports.slots, undoable). Values come from tailing the postProcessing files every 250 ms on the GUI thread (only the appended bytes are read; an incomplete last line waits for the next poll) and show the last value (4 significant digits) and a sparkline of the last 200 values. A finished run is shown again when the project is opened (its log and postProcessing files). Without a run the chart keeps its empty state and the values show "—".
- Alternatives considered: polling the files on the worker thread (more signals, no gain for files of a few kB per minute); a plotting library (no new dependencies).
- Consequences: y+ values change only at write times (the yPlus function object runs at writeTime, unchanged from Task 4A).

## D-049 Residual chart palette
- Status: Accepted (reviewed 2026-10-17 in the review chat; colours remain the owner's call, D-041)
- Context: the chart needs one colour per field and the rule is that only owner tokens are used. No set of six owner tokens passes the dataviz palette checks on the dark canvas: every token is lighter than the dark lightness band (OKLCH L 0.48-0.67), text and muted text read as gray, and red / amber and teal / green are too close (normal-vision and CVD separation).
- Decision: three hues derived from owner tokens, each blended over `canvas` (#0A0D12) at the largest weight that puts it at OKLCH L <= 0.66: p = accent at 0.84 (#D87403), Ux / Uy / Uz = axis_z at 0.82 (#309DCF; solid / dashed / dotted), k / omega = axis_y at 0.83 (#28AC61; solid / dashed). Any other field: muted_text, dash-dot. Lines are 2 px; the legend names every series in text colour. Status colours (success, warning, error) are not used. Validator result (all pairs, dark, canvas): lightness, chroma, contrast and normal-vision separation pass; CVD separation WARN (deutan 7.9 between green and amber), allowed because the families also differ by line style and the legend names them. Values in gui/theme.py (RESIDUAL_STYLES), asserted in tests/test_monitors_gui.py.
- Alternatives considered: six separate hues from the tokens (fails the separation checks); the raw tokens (outside the lightness band, too bright on the canvas).
- Consequences: velocity components share one hue; the owner may replace the palette with explicit chart tokens.

## D-050 forceCoeffs projection checked against a forces function object
- Status: Accepted (review of Task 4B on 2026-10-17, [NUMERICS-REVIEW]; docs/QUESTIONS.md item 53)
- Context: v2606 forceCoeffs does not read `pitchAxis`; the review asked whether it also ignores liftDir and dragDir. Source: forces::setCoordinateSystem (with CofR it reads e3 from liftDir and e1 from dragDir, both mandatory) and the coefficient.dat header, which prints the axes it uses.
- Decision: controlDict gets a `forces1` function object next to forceCoeffs1 (same patches, rho rhoInf, CofR, no direction entries, so its force.dat is in the global axes, written every iteration). The check: a flattened ellipsoid (semi-axes 0.5 x 0.5 x 0.15 m, default mesh, 192458 cells) at alpha = 10 deg, 150 iterations; Cd and Cl of forceCoeffs against the total force of forces1 projected onto dragDir = (cos a, 0, sin a) and liftDir = (-sin a, 0, cos a) and divided by 0.5 rho U^2 A_ref. Result at iteration 150: Cd 0.0357514 vs 0.0357514, Cl 0.04125657 vs 0.04125655 (difference below 1e-4 %); every one of the 150 iterations agrees within 0.5 %. The forceCoeffs dictionary did not have to change. The `pitchAxis` entry stays as documentation (the pitch axis is e3 x e1 = +y). Tests: tests/test_force_projection.py on the real output (tests/data/projection_run/) and a slow test that re-meshes the body and repeats the check on 40 iterations.
- Alternatives considered: switching forceCoeffs to an explicit coordinateSystem (not needed: the keywords are read).
- Consequences: one more postProcessing file per run (force.dat and moment.dat, a few kB per 100 iterations).

## D-051 A new mesh deletes the previous results
- Status: Accepted (review of Task 4B on 2026-10-17; docs/QUESTIONS.md item 48)
- Context: Generate Mesh replaced constant/polyMesh but left the old solver results (time directories, postProcessing/), which no longer match the mesh and could be opened in ParaView.
- Decision: after a successful Generate Mesh, the time directories after 0, postProcessing/ and case/vortexcfd_run.json are deleted inside the marker-protected case directory only (foam/mesh_case.remove_results refuses a directory without the marker; 0/, constant/, system/, logs and other files stay), and the console logs what was removed ("Removed the previous results for the new mesh: ..."). The shown run, its monitors and the results badge are cleared. A failed or stopped meshing run deletes nothing.
- Alternatives considered: deleting before meshing (a failed mesh would lose results for nothing); keeping them flagged out of date (the earlier behaviour, D-046).
- Consequences: results always belong to the current mesh; a Run Solver after meshing starts from a clean case.

## D-052 Lost-part guard, thin-part warning, per-part levels and seed lines (schema v5)
- Status: Accepted (review chat 2026-10-17, [NUMERICS-REVIEW]; updated in that review: seeding is automatic, docs/QUESTIONS.md items 54 and 55). The manual-only seeding first recorded here (seed lines only for parts with a level override) is superseded by the automatic seeding below.
- Context: a sphere (radius 0.5 m) plus a flattened ellipsoid (0.6 x 0.4 x 0.4 m) 1.5 m downstream, default sizing, gave a mesh with no patch for the ellipsoid while checkMesh said "Mesh OK"; a solver run would give credible but wrong forces. Root cause (reproduced, logs in the Part A report): snappyHexMesh finds a surface only where the segment between two neighbouring cell centres crosses it (its "Number of edges" equals the number of faces). The two-part domain gives a 0.596 m background cell, so near the ellipsoid those segments run at y, z = +-0.30 m while the ellipsoid spans only +-0.20 m: no segment crosses it, it is never marked for refinement (raising its surface level to 5-6 or 6-7 changed nothing), its interior is never separated from the flow region, and snapping has no faces for its patch. Shifting it off the grid planes, flipping its normals or a distance-mode refinementRegion (shell refinement runs only after surface refinement) did not help either; a finer background (0.375 m) gave only 16 faces.
- Decision:
  - Guard: after every mesh, constant/polyMesh/boundary is read; a part patch that is missing or has 0 faces is a lost part. MeshReport gains `lost_parts` and `valid` (checkMesh OK and no lost part); the summary adds "Part <name> was lost during meshing", logged as an ERROR, shown in the error colour in the Mesh properties (Lost parts row) and in the top-bar mesh badge ("Mesh invalid: Part <name> lost"), and Run Solver is disabled with that reason. The mesh record keeps lost_parts (absent in older records = none).
  - Pre-mesh criterion (foam/mesh_case.needs_seeding): a part whose second-largest bounding-box extent is below sqrt(2) background cells (a convex part is certain to be crossed by the lattice of cell-centre lines only if its largest projection holds a disc of sqrt(2) cells), or that is thinner than 3 surface cells at its maximum level. Such a part is noted in the Mesh properties, the Generate Mesh tooltip (the button stays enabled) and the console when meshing starts: "Part <name> is small relative to the background mesh: refinement seeded automatically".
  - Per-part refinement: Part gains optional surface_level_min / surface_level_max (None = the Mesh levels; only the max set gives min = max - 1; shown as "auto" in the Part properties); its refinementSurfaces entry and its feature level use them; they are meshing inputs (mesh hash). Schema v5 with migration (hand-written v4 fixture).
  - Seed lines, automatic: every part flagged by the criterion gets constant/triSurface/<part>_seed.eMesh, three axis-aligned lines through the centre of its bounding box reaching 20 % beyond it, added to `features` at the part's maximum level (its overrides if set, otherwise the mesh's computed levels), without user action. Explicit feature refinement runs before surface refinement and needs no intersection, so the cells along the lines are refined and the surface is then found. The reproduced case with DEFAULT settings: 135265 cells, Ball 1952 faces, Pod 1304 faces, checkMesh Mesh OK, the guard passes (before seeding: 120709 cells, Pod lost). The lost-part guard stays for any other cause.
- Alternatives considered: raising the part's surface level only (no effect, see Context); a distance-mode refinementRegion around the part (applied after surface refinement: 40 faces); a finer background everywhere (costly, 16 faces at 0.375 m); seeding only parts with a level override (the first version of this entry, superseded in the review).
- Consequences: a lost part can no longer reach the solver; the user is warned before meshing and fixes it with the part's levels. Seed lines add a thin column of refined cells inside the part (removed with the part interior). Test bound: the real meshing tests that build their own mesh (tests/test_lost_parts.py, tests/test_force_projection.py) allow 240 s per OpenFOAM step and 600 s in total instead of the 120 s of D-043, because under `-n 8` they run next to every worker's session sphere mesh and timed out once.

## D-053 Results Scene
- Status: Accepted (review chat 2026-10-17; updated in that review: the control strip wraps and the scene opens from upstream, docs/QUESTIONS.md items 57 and 59)
- Context: PLAN 6.2 scalar scenes: field selector, colormaps, range modes, legend bar.
- Decision: a "Results Scene" tab is shown only when the case has results (a time directory after 0 holding files). Entering it reads the latest time with PyVista's OpenFOAM reader (case.foam, written if missing) on a worker thread (always, so a large case never blocks the GUI); the data reaches the GUI through Qt signals. The wall (part) patches are coloured by the selected field (cell values). Fields: p (kinematic, m2/s2), Cp = p / (0.5 U_ref^2) (U_ref = the inflow speed, p_ref = 0, the outlet value), |U|, Ux, Uy, Uz, k, omega, nut, y+ and |wallShearStress| (kinematic), each listed only when its file in the latest time directory is a volume field of the right kind (default Cp). Range: auto (data range), fixed (min/max fields, seeded with the current range) or symmetric about zero. One vertical VTK scalar bar with "<field> [<units>]", title and labels in the theme `text` colour, font size 1.25 x the UI point size in px (labels at least 10 px). Display Walls / Section / Both: the section uses the Mesh Scene's plane controls (normal buttons and slider; the section and boundary toggles are hidden here) and, as in the Mesh Scene, clips the walls behind the plane. The control strip is a flow layout that wraps onto a second row when its content does not fit, so Open in ParaView is never clipped (checked at fonts 11, 14 and 18). On entering the scene the camera looks at the centre of the parts from upstream and above (direction from target to camera (-1, -1, 1), +z up; telemetry View "Upstream ISO"), so the windward side faces the user. Telemetry gains a checkable "Field range" row (min - max and units of what is shown), present only in the Results Scene. "Results out of date" (the run record's hash, D-046) is a warning strip in the scene's control row. A new mesh removes the results (D-051) and the tab.
- Alternatives considered: point data (interpolated, smoother but not the solver's face values); reading on the GUI thread for small cases (a second code path for little gain).
- Consequences: scene definitions are not saved in the project yet (PLAN 6.2 acceptance) and there is no image export; slices, iso-surfaces and streamlines are not started.

## D-054 Colormaps from matplotlib
- Status: Accepted (review chat 2026-10-17; the dependency exception of Task 6.2)
- Context: the Results Scene needs viridis, plasma, turbo, coolwarm and grayscale. matplotlib 3.11.2 is already in .venv: PyVista 0.49 requires it (pip: "Required-by: pyvista, vtk").
- Decision: use matplotlib's lookup tables, in one module (gui/colormaps.py: names, 256-entry RGB tables, the name passed to PyVista), and declare matplotlib in pyproject.toml dependencies because the app now imports it directly. Licences: matplotlib (PSF-style matplotlib licence), viridis/plasma CC0, turbo Apache-2.0; all GPL-3 compatible.
- Alternatives considered: tables built in code from published control points (more code to maintain and verify, same result); relying on matplotlib only through PyVista (an undeclared direct import, like the numpy debt).
- Consequences: no new package is installed; the colormap list is one dictionary to extend.

## D-055 Open in ParaView
- Status: Accepted (review chat 2026-10-17)
- Context: D-005 promises that every case opens in ParaView; the owner runs the Windows ParaView next to WSL.
- Decision: the Results Scene has "Open in ParaView": it writes case.foam, converts its path with `wslpath -w` and starts paraview.exe with it, detached (new session, no pipes, the GUI never waits). The executable is a setting (Edit > Preferences, QSettings key paraview/executable); when unset, the newest /mnt/c/Program Files/ParaView*/bin/paraview.exe (by the version in the folder name) is used. Without an executable the button is disabled and its tooltip says how to set the path.
- Alternatives considered: a Linux ParaView inside WSL (not installed; slower through WSLg); pvpython scripting (not needed to open a case).
- Consequences: works only when a Windows ParaView is installed or configured (none is installed on the development machine today).

## D-056 Inward-normals warning at import
- Status: Accepted (review chat 2026-10-17; docs/QUESTIONS.md item 56)
- Context: the flattened ellipsoid of item 54 (pv.ParametricEllipsoid) had all its normals pointing inward; nothing told the user.
- Decision: the surface checks compute the signed volume of the triangles; a closed (watertight) surface with a negative signed volume has "normals point inward": a "Normals" row in the Part's Checks shows "point inward" in the warning colour ("outward" otherwise, "-- (open surface)" for an open one), the check summary says so and the import logs a WARNING. The file is never flipped automatically.
- Alternatives considered: flipping on import (changes the user's file silently).
- Consequences: inside-out surfaces are visible before meshing; snappyHexMesh tolerated them in the cases seen so far.

## D-057 Status bar: messages left, selection right
- Status: Accepted (review chat 2026-10-17; docs/QUESTIONS.md item 58)
- Context: a temporary status message was drawn over the "Active selection" label (both on the left).
- Decision: "Active selection" is a permanent status-bar widget, right-aligned; QStatusBar draws temporary messages only in the space left of permanent widgets, so the two never overlap.
- Alternatives considered: hiding the label while a message shows.
- Consequences: in a narrow left column a long message is cut at the label instead of covering it.
