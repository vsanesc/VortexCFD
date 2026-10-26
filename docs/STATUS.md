# Status

Updated 2026-10-26 (task/v1.0.1-pillow: **Pillow 13.0.0 for the Dependabot security alerts**).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/v1.0.1-pillow** (not yet published; no push, no merge). Security update for 1.0.1 (D-180):
- pillow 12.3.0 -> 13.0.0 in scripts/requirements-v1.txt and THIRD_PARTY_LICENSES.md: fixes all 41 open Dependabot
  alerts (5 critical, 23 high, 13 moderate; alert 1 of 42 withdrawn by GitHub); none affects 13.0.0. CHANGELOG 1.0.1
  (unreleased).
- Checks: the fast suite; the image-export, report and branding tests; scripts/brand/make_logo.py byte-identical;
  scripts/install.sh in a temporary HOME and prefix (`vortexcfd --version`: 1.0.0); the public benchmarks'
  dictionaries byte-identical to main's (`diff -r`, 51 files, exit status 0). No OpenFOAM run.
- Other pins against the GitHub advisory database (pip-audit is not installed): certifi==2026.7.22 is affected by
  GHSA-6q48-6c7w-9gw2 (critical, fixed in 2026.10.18); not changed (QUESTIONS 247).

## Previous branch

**task/gui-2** (merged). A second round of GUI work the owner asked for after using the
app; one commit per item:
- Item 7 (D-165): stopping criteria the user removes no longer "come back": the monitors show the run's own criteria
  ("Criteria of the last run", kept in the run record) apart from the project's; Run Solver saves the project first
  (the owner's ~/simulation_2 showed a run from edits that were never saved); the properties panel hides every row
  before showing the selected node's (the leftover rows were not reproduced offscreen: QUESTIONS 238).
- Item 9 (D-166): readable values (labels, not identifiers) and every number with its unit; a test walks every node.
- Item 8 (D-167): the angle of attack in the Free stream (with a link), on the Geometry node, the Body attitude
  explained.
- Item 1 (D-168): the Reynolds and Mach numbers, live; the speed of sound (schema v24); the warning above Mach 0.3.
- Item 3 (D-169): 1-2-5 ticks, minor ticks, a light grid and zoom and pan on every chart.
- Item 4 (D-170): report charts in their own windows (history, windowed mean and band, PNG / CSV, live).
- Item 5 (D-171, [NUMERICS-REVIEW]): Continue Solver from the latest written time.
- Item 2 (D-172, [NUMERICS-REVIEW]): the live view of walls and planes during a run, and Write Fields Now.
- Item 6 (D-173): the Solution menu (F5, Shift+F5, F6), one action shared with the top bar and the tree.
- Item 10 (D-174, D-079 amended): Save As copies the mesh and results (progress, Cancel).
- Item 11 (D-175): the logo: the generator ported (byte-identical to the saved mark), icons, lockups, used in the app,
  the installer, the README, the manual and the report.
- Item 12: the manual (2.4, 2.5, 2.7, 5.1, 9), CHANGELOG, ARCHITECTURE, QUESTIONS 237 to 244.
- The public benchmarks' meshing and solver dictionaries (scripts/validation/public_dicts.py): byte-identical to main's
  (`diff -r`, 51 files, exit status 0).
- Screenshots: run/gui_review/gui2/<item>/ (scripts/gui_review_sizes.py, its new `main:<node>[@<setup>]`,
  `report_chart`, `solution_menu` and `save_as` screens).
- Machine time: two real runs through the app, nice 15, under 2 minutes each: the coarse sphere on 4 cores stopped at
  iteration 32 and continued to 80 (43,299 cells; 13.5 s mesh, 4.7 s + 5.9 s solve), and 100 iterations with the
  live view every 10 and one Write Fields Now (8.6 s solve); no OpenFOAM process left running.

Owner review of gui-2 (2026-10-24): D-165 to D-175 accepted, with the [NUMERICS-REVIEW] parts of D-171 and D-172;
QUESTIONS 237, 242, 243 and 244 accepted; 236, 238 and 240 closed (checked by the owner on the real display). Done
after it, one commit each:
- Item 1 (D-176, QUESTIONS 241): Continue Solver after "Criteria met" too; one dialog asks how many more iterations
  and shows each criterion's threshold or tolerance to tighten (saved in the project, one undoable edit); the run then
  continues as in D-171 (tests/test_continue_met.py, fake runners).
- Item 2 (D-177, QUESTIONS 239): the logo is CC BY-SA 4.0, separately from the code: assets/branding/LICENSE (the full
  text), THIRD_PARTY_LICENSES.md, the README (and its line asking forks not to pass as the official project).
- Item 3: version 1.0.0 in its single source; CHANGELOG 1.0.0 lists everything since 1.0.0rc1 (the release polish,
  both GUI rounds, the branding, the two fixed intermittent failures, D-163 and D-164); "no restart" dropped from the
  known limitations (CHANGELOG, manual 8, RELEASE_v1); docs/RELEASE_v1.md: everything done except the owner's tag and
  the decision whether the repository becomes public.

Owner review 2 (2026-10-24): D-176 and D-177 accepted; the logo's copyright line "Copyright 2026 Víctor Sánchez
Escalante"; the licence review signed off (foamlib GPL-3.0-only, pymeshfix AGPL-3.0 accepted; pytetwild 0.4.2 and
certifi 2026.7.22 checked: no "Incompatible With Secondary Licenses" notice, only the template inside the MPL-2.0
text). Done after it, one commit each:
- Item 1 (D-178): the convergence panel. "Satisfied" showed "holds and may stop the run now"; the owner's run
  (~/simulation_4: two stages switched at 1502, minimum 2000, stopped at 2831) could stop in stage 2 only from 3502,
  so every row said "no". Now "Satisfied now": whether it holds at the last iteration, a window's progress, "yes
  (stops from 3,502)". The warning "Residuals met, but Cl is still changing". The mass imbalance was no reading bug:
  both fluxes are written to 7 digits and cancel (true imbalance from the log about 1e-8 %); below the files'
  resolution it shows "< 4.7e-05". QUESTIONS 245 ([NUMERICS-REVIEW]): stage 2's minimum.
- Item 2 (D-179): the taskbar icon under WSLg: app id and WM_CLASS "vortexcfd" set before the QApplication; the
  desktop entry (absolute icon path, update-desktop-database, `--desktop-only`); scripts/windows/make_shortcut.ps1
  for the owner (not run here); manual 1.5. QUESTIONS 246: the owner checks the taskbar on the real display.
- Item 3: CHANGELOG and STATUS.

Next: the owner's review (D-178, D-179, QUESTIONS 245 and 246); scripts/ship.sh (the owner), then the tag
(docs/RELEASE_v1.md) and the repository-public decision.
Open: docs/QUESTIONS.md items 30, 67, 69, 70, 72, 73, 75, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167,
168 (a, c), 174, 214, 245, 246.

### Previous branch (task/gui-polish, published in PR #35)

**task/gui-polish** (not yet published; no push, no merge, no tag). The owner found the GUI hard to use; this branch
overhauls it and adds three features a user (Carla) asked for. Done on it, one or more commits per part:
- Part A (D-141): tests and scripts never touch the user's settings (`VORTEXCFD_SETTINGS_DIR`, set by
  tests/conftest.py and by every script through `isolate_settings()`); Recent never records a temporary folder and is
  pruned of missing projects at start-up (10 kept).
- Part B (D-142): the welcome screen (two large buttons; the open panel with the recent projects, Browse, the
  right-click menu).
- Part C (D-143): the New simulation dialog (sections, the presets as a described list, the dimension row, "N / 12",
  inline validation).
- Part D (D-144): the Zinc & Teal theme (owner palette; every text pair WCAG AA, ratios in D-144).
- Part E (D-145, [NUMERICS-REVIEW]): a context menu on every tree node, Delete / F2 / double-click; refinement
  regions from imported closed surfaces or a part (schema v22): triSurfaceMesh refinementRegions, inside or
  distance, in the estimate and the viewer. One real mesh (sphere + imported box region, 38 s): the cells inside at
  the region's level.
- Part F (D-146): one explained Surface Preparation action.
- Part G (D-147 [NUMERICS-REVIEW], D-148): interface size (Small default), compact collapsible properties with "?"
  help (manual chapter 9), a detachable panel; Mesh units / Auto boxes / surface size with its length / curvature
  explained and editable to 4 levels [NUMERICS-REVIEW] / prism layers named and explained; Free stream (renamed) and
  Body attitude; domain extents in L, m or mm; editable boundary types of every domain face (defaults unchanged,
  benchmark dictionaries byte-identical); probes and CofR as vector fields; the mesh independence study explained;
  the polar sweep opt-in; units and tooltips everywhere.
- Part I (D-149): results snapshots and the Compare tab (overlays, difference tables, PNG / CSV, the report's
  Comparison section).
- Part J (D-150): Show in OpenFOAM file (the map found with the writers, the read-only viewer, a preview when the case
  has none).
- Part K (D-151): Open in ParaView in the top bar and the Results menu.
- Part H: the manual (names, the new features, chapter 9, the window pictures and the re-exported result images),
  CHANGELOG, QUESTIONS 223 to 235.
- Screenshots for the owner's review: run/gui_review/<part>/{before,after}/ and run/gui_review/final/ (offscreen,
  `scripts/gui_review.py`).
- Machine time: one real mesh (38 s, nice 15), the manual's image export (20 s, no OpenFOAM), the fast test run.
  No OpenFOAM process left running.

Follow-up (the owner's 13 items), one commit each:
- Item 10 (D-152): the Results selectors apply after their popup has closed (QUESTIONS 236 asks for a check on the
  real display).
- Item 2 (D-153): text roles in the theme, the only text sizes (a test fails on any other); a role re-applied after
  an interface size change and after a state change (text kept its old size until a restart).
- Item 1 (D-154): New simulation fits its content, only the preset list gives way, a unique default name.
- Item 11 (D-155): the status badge sized from its font (descenders were cut), a compact top bar, a minimum window
  size (66 x 36 font heights).
- Item 9 (D-156): the residual chart and the convergence criteria detach into their own windows (live, remembered,
  docked when their screen is gone).
- Item 5 (D-157): domain extents in m or mm stored in that unit (schema v23).
- Items 3, 4 (D-158): every screen at three window and three interface sizes (scripts/gui_review_sizes.py,
  run/gui_review/fix/<screen>/<window size>_<interface size>.png); fixes (the monitors column scrolls, elided names,
  the legend wraps, minimum sizes, rebuilt rows no longer drawn over); tests/test_screen_layouts.py checks overlaps,
  clipped text and cut widgets at each screen's minimum and each interface size.
- Item 6 (D-159): open surfaces as refinement regions in the distance mode.
- Item 7 (D-160): a snapshot samples every line plot itself.
- Item 8 (D-161, [NUMERICS-REVIEW]): optional prism layers on wall domain faces, off by default; the public
  benchmarks' dictionaries byte-identical to main's (`diff -r`, 51 files).
- Item 12 (D-162): the licence statement, CONTRIBUTING.md, issue and pull request templates, the .gitignore audit.
- Item 13: final screenshots (run/gui_review/final/, run/gui_review/fix/), the manual's window pictures, QUESTIONS
  226, 227, 230, 231 closed and 224, 225, 228, 229, 232 to 235 accepted by the owner.
- Machine time: no OpenFOAM run in the follow-up; offscreen screenshots and the fast test run at nice 15.

Owner review (2026-10-24): D-161 accepted ([NUMERICS-REVIEW]: off by default, benchmarks byte-identical), schema v23
carrying D-157 and D-161 accepted, QUESTIONS 223 accepted; 236 stays open until the colormap is checked on a real
display. Review follow-up, one commit each:
- Item 1 (D-163): the flaky polar sweep test. The run's thread set the record to "finished" and called on_done while
  still alive, so the window handled the end with the run still "running" (status label "Running: n of 3", Run
  button "Stop", never updated again). The end now reaches the window after the thread has ended; the tests wait
  for the label's final text. tests/test_study_gui.py passed 20 runs in a row.
- Item 2 (D-164, QUESTIONS 82 closed): the offscreen teardown crash. Worker threads emitted Qt signals on QObjects
  being deleted with their window (heap corruption; every plotter was closed at each crash). Every worker emits
  through a ThreadGate the window closes before it can be deleted, together with the console and the viewer (also
  after a refused close); scripts dispose of their windows and finish cleanly. The ship.sh test command
  (`QT_QPA_PLATFORM=offscreen pytest -q -m "not validation and not long and not bench"`, at nice 15) passed 3 runs in
  a row in one process: 1366 passed each, 18:33, 18:36, 18:36 (1157 s, 1163 s, 1164 s wall); it crashed in run 2
  of 2 before. The all-screens review script exits 0 in 36 s (81 images).
- Machine time: the ship.sh command 5 times in one process (with its slow tests' real snappyHexMesh runs, as the
  owner chose), about 1 h 45 min at nice 15; no OpenFOAM process left running.

Next: QUESTIONS 236 (the colormap on a real display); then scripts/ship.sh and the v1.0.0 tag (docs/RELEASE_v1.md).
Open: docs/QUESTIONS.md items 30, 67, 69, 70, 72, 73, 75, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167,
168 (a, c), 174, 214, 236.

### Previous branch (task/release-1.0.0, published in PR #34)

**task/release-1.0.0**. **v1.0.0 is ready to tag**
(docs/RELEASE_v1.md). Done on it:
- Owner review recorded: D-138, D-139, D-140 accepted; QUESTIONS 218, 219, 221, 222 accepted as implemented.
- Item 1, QUESTIONS 220 (D-138 amended): a configured ParaView path that does not exist falls back to automatic
  detection, and the button's tooltip says the configured path was not found.
- Item 2: version 1.0.0 in `src/vortexcfd/__init__.py` (the manual, requirements header and licence list follow).
- Item 3: CHANGELOG.md for 1.0.0 (features by area, the validation table, the known limitations, the requirements);
  manual chapter 8's last limitation brought up to date (the clean-install test done).
- Item 4: docs/RELEASE_v1.md: every item done; the owner's last decisions (a public repository, the licence
  sign-off) and the tag command.
- Item 5: this file and docs/PLAN.md: v1.0.0 ready to tag; the post-v1 backlog is the next plan (docs/PLAN.md,
  "Next plan").
- No OpenFOAM run; the fast test run only.

Next: the owner's decisions on a public repository and the licence sign-off; scripts/ship.sh; the tag (command in
docs/RELEASE_v1.md); then the post-v1 backlog in the owner's order. Open: docs/QUESTIONS.md items 30, 67, 69, 70,
72, 73, 75, 82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 214.

### Previous branch (task/rc1-polish, published in PR #33)

Done on it:
- Owner review recorded: D-136 and D-137 accepted; the owner's clean-install test of scripts/install.sh in a fresh
  WSL2 Ubuntu 24.04 passed; QUESTIONS 215, 216 accepted, 217 closed, 212 a note in manual 5.4.
- Item 1, ParaView optional (D-138): "Open in ParaView" finds the Preferences path, `paraview` on PATH, or the
  Windows ParaView under C:\Program Files; none: the button is disabled with a tooltip on how to install it
  (`sudo apt install paraview`, or ParaView for Windows through \\wsl$). The install script reports it as optional;
  manual 1.4. Note: /usr/bin/paraview exists on this machine (QUESTIONS 219).
- Item 2 (QUESTIONS 213, D-139): the app uses QtCore, QtGui, QtWidgets, and through pyvistaqt / VTK / matplotlib
  QtOpenGL, QtOpenGLWidgets, QtSvg (all PySide6-Essentials); the dependency is PySide6-Essentials 6.12.0, pinned.
  Isolated install: 1870 MB -> 1442 MB.
- Item 3: QUESTIONS 214 (the Start menu entry) left open for the owner on a real display.
- Item 4: docs/RELEASE_v1.md: the clean install done; left: the public-repository decision, the licence review
  sign-off, tagging v1.0.0.
- Item 5: the NACA 0012 round 3 2D C-type domain is NOT reversed (round inlet at x < 0, flat outlet at +x, from the
  case's domain.stl, snappyHexMeshDict and polyMesh/boundary; QUESTIONS 222); no fix, no validation re-run.
- Item 6 (D-140, [NUMERICS-REVIEW]): 2D projects are shown looking along +y (flow left to right) in the geometry,
  mesh and results scenes; exports copy that camera. Before, the geometry scene kept an ISO view with +x to the left.
- No OpenFOAM run. Machine time: two isolated installs (34 s and 27 s), the fast test run.

Next: owner review of D-138 to D-140 and QUESTIONS 214, 218 to 222; the public-repository decision; the licence
review sign-off; tag v1.0.0 after scripts/ship.sh. Open: docs/QUESTIONS.md items 30, 67, 69, 70, 72, 73, 75, 82, 89
to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 214, 218 to 222.

### Previous branch (task/w4-w5, published in PR #32)

The last two workstreams of v1. Done on it:
- Owner review recorded: D-135 accepted, QUESTIONS 210 and 211 accepted, W3 closed by the closure rule (D-127 stays
  Proposed as a known limitation).
- Part A, W4 remainder (D-136, schema v21): the HTML report's mesh study table (each quantity per level, the
  convergence, order, extrapolated value and GCI, or why there is none; a 3D study flagged indicative) and polar sweep
  table with a CL / CD / CM plot; a "Line plot" results object (two points, samples, fields) with its chart embedded
  in the properties rows, PNG and CSV export, the line drawn in the viewer, its chart in the report; the streamlines'
  own colormap, colour range and scalar bar; File > Create Report asks for the sections and remembers them per
  project.
- Part B, W5 installation (D-137): the start-up OpenFOAM v2606 check (environment variable, configured path,
  standard ESI places; a dialog with the ESI commands as text and a path field; without OpenFOAM the app opens and
  meshing, solving, the study and the sweep are disabled with the reason); scripts/install.sh (Ubuntu 24.04,
  Python 3.12, OpenFOAM printed not run, a venv with the pinned scripts/requirements-v1.txt, the launcher and
  desktop entry, never sudo; idempotent); `vortexcfd --version` / `--check-openfoam` without Qt; version 1.0.0rc1 in
  one place (About, --version). Proof in isolation (temporary HOME and prefix, pip's existing cache): exit 0,
  `vortexcfd 1.0.0rc1`, the OpenFOAM check passing; run again: reused, exit 0. **A second-machine test is owed by the
  owner.**
- Part C, the user manual docs/manual/ (8 chapters, 11 images exported by the app from a new sphere run through the
  window, the NACA 0012 round 3 case and the pipe validation case; `scripts/manual_images.py`), linked from README
  and Help > User Manual. Found and fixed on the way: image export ignored the viewer's camera (every export and
  report view used PyVista's default view; D-133 note, QUESTIONS 212), exported scalar bars lost their fixed font
  size, and a UI refresh failure with the "Section" display and any scene object (D-132 note, QUESTIONS 217).
- Part D: docs/RELEASE_v1.md (the v1 checklist with its evidence and what the owner owes), THIRD_PARTY_LICENSES.md
  refreshed with every pinned dependency and a licence review (no incompatible licence; points to confirm),
  docs/validation/README.md brought up to the last rounds.
- Machine time: OpenFOAM about 2.5 min (the sphere meshed twice, 29 s each, solved once, 75 s, 8 cores, nice 15);
  install proofs about 1.5 min; the image script about 5 min; the fast test run. No OpenFOAM process left running.

Next: owner review of D-136, D-137 and QUESTIONS 212 to 217; the second-machine install; the decision on making the
repository public; the licence review. Open: docs/QUESTIONS.md items 30, 67, 69, 70, 72, 73, 75, 82, 89 to 94, 96,
97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 212 to 217.

### Previous branch (task/w3-close)

**task/w3-close** (published in PR #31). **W3 closed** by the owner's closure rule (both items below failed their
pass conditions inside the time box; the limitations are recorded and accepted for v1). Done on it:
- Item 1 ([NUMERICS-REVIEW], D-127 rewritten, still Proposed; QUESTIONS 204 closed): the 3D study's distance shells
  replaced by level-scaled buffers, nCellsBetweenLevels max(1, round(3 r^(k - k_current))) (2 / 2 / 3), so the current
  level is the user's single mesh (dictionaries identical). Check (docs/validation/study3d/RESULT.md, Round 4): every
  level valid, but the geometric means of the cube-mean size ratios are 1.00 / 1.25 (sphere) and 0.94 / 1.24 (wing)
  against 1.414 +- 10 % (1.5 and 2.12 both round to 2): **not passed**; the pipe's three-level study not run.
- Item 2 ([NUMERICS-REVIEW], D-135 Proposed; QUESTIONS 209 closed): the step face's lost layers were snappyHexMesh's
  face-weight check at the step's convex corner (a sliver face on the medium grid); minFaceWeight 0.02 in the
  wall-resolved relaxed set. Coarse and fine meshes identical, the medium level complete: x_r 6.468 / 6.227 / 6.434 H,
  oscillatory, no GCI: **PASS WITH NOTE** (docs/validation/bfs/RESULT.md, Round 3).
- Public benchmark: dictionaries byte-identical to main (51 files), `--compare` mesh only "no regressions".
- Decisions taken while away: QUESTIONS 210 (half-up rounding), 211 (the scaled buffers kept rather than the shells).
- Machine time about 34 min (3D check 4.6 min, step diagnosis and mesh checks 9 min, NACA mesh check 7 min, medium
  level 12.1 min, benchmark 4.7 min, the fast test run). No OpenFOAM process left running.


### Previous branch (task/w3-internal)

**task/w3-internal**. Workstream W3, internal flow (**not closed**, owner review below); the
first W4 slice. Done on it:
- Part 0 ([NUMERICS-REVIEW], D-127, QUESTIONS 204): every 3D study level, the current one included, is meshed with
  the distance shells and nCellsBetweenLevels 1. The check (docs/validation/study3d/RESULT.md, Round 2) does **not
  pass**: valid levels, layers and quality as before, the cell size shrinks with the ratio at 6/6 sphere points but
  2/6 wing points (points within half a coarse cell of a shell edge). D-127 stays Proposed; D-128 accepted.
- Part A ([NUMERICS-REVIEW], D-129, schema v19): the internal analysis type: no domain (the fluid is the inside of
  the closed geometry, locationInMesh found inside, a clear error for an open geometry), a role per surface patch,
  velocity / mass-flow / total-pressure inlets and a static outlet (v2606 types confirmed in the sources and
  TJunction), mass flow and area / mass-averaged static and total pressure per inlet, outlet and cutting plane,
  pressure drops, the "Internal flow" and "2D internal flow" presets, the GUI rows and the Internal flow table.
  Public benchmark: dictionaries byte-identical (51 files), `--compare` no regressions. Found by the validations and
  fixed: planes on mesh faces (D-129), parallel re-meshing of a solved case (D-130), the total-pressure inlet's
  divergence (SIMPLE with a relaxed pressure, D-131), the fluid point and volume of a misoriented surface, the
  study's y+ speed and wall first-cell measurement.
- Part B: turbulent pipe, Re 1e5: **PASS** (f +1.36 % against Prandtl-Karman, mass balance 0.0 %, the total-pressure
  inlet within 0.03 %); single level (docs/validation/pipe/RESULT.md).
- Part C: TMR backward-facing step: **PASS** on the finest of five levels (x_r 6.44 H, +2.8 %; SST -1.0 %), grid
  convergence not established (docs/validation/bfs/RESULT.md, QUESTIONS 209).
- Part D: the W3 docs.
- W4, first slice (no OpenFOAM run): results scene objects (D-132, schema v20: a clip with the side kept, an
  isosurface, streamlines from a line or a plane, saved views; items under a Results node, each edit one undo step);
  image export of the viewer rendered offscreen at the chosen size, optionally transparent, with the scalar bar
  (D-133); the HTML report (D-134).
- Machine time about 1 h 10 min (3D check 6 min, benchmark 3 min, pipe 10 min, step 50 min, the rest tests and
  trials). No OpenFOAM process left running.
- Owner review of W3 (2026-10-22): D-129 to D-134 accepted; QUESTIONS 205, 207, 208 closed. Follow-up:
  - QUESTIONS 204, round 3 ([NUMERICS-REVIEW]): shell distances rounded to whole coarse cells, sizes averaged over a
    cube of 2 coarse cells: 2/6 sphere and 1/6 wing points pass: **not passed**, the rounding reverted, D-127 stays
    Proposed, the pipe's study not run (docs/validation/study3d/RESULT.md, Round 3).
  - QUESTIONS 209, round 2: the inlet moved to x/H = -131 for TMR's 1.5 H boundary layer; the finer family: 6.468
    (valid) / 5.637 (step face kept 69 % of its layers: not counted) / 6.434 H (valid): two valid levels, no GCI:
    **PASS WITH NOTE** (docs/validation/bfs/RESULT.md, Round 2).
  - QUESTIONS 206: no reserved domain patch names in internal projects (closed).
  - Machine time about 1 h 22 min (3D check 13 min, boundary-layer calibration 16 min, step study 53 min).

Next: QUESTIONS 204 (the 3D study's check) and 209 (the step face's layers). Open: docs/QUESTIONS.md items 30, 67, 69, 70,
72, 73, 75, 82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 204, 209.

### Previous branch (task/w2-naca-r2)

Workstream W2, NACA 0012 rounds 2 and 3. **W2 closed.** Done on it:
- Round 2 (owner-reviewed: D-123 to D-125 accepted): the wall-resolved mode follows the y+ target (D-123); the
  cause of round 1's drag error, the 2D staircase's 3-cell buffer, and the 12-cell buffer (D-124); the inverted
  pyramids fixed by the medial-axis walk limit (D-125); the driver's PASS at 0, 10 and 15 deg.
- Round 3, Part A ([NUMERICS-REVIEW], D-126): two turbulence stages in one app run for the wall-resolved mode:
  first-order k, omega to the stopping criteria (or half the iteration limit), the D-058 clean stop, bounded
  linearUpwind k, omega from the latest time to the criteria again; monitors show the stage and the switch; the
  record keeps both stages. Public benchmark: dictionaries byte-identical, `--compare` no regressions.
- Part B ([NUMERICS-REVIEW], D-127): a study level keeps the current settings' refinement regions in metres (2D
  staircase boxes; 3D distance shells, which the 3D study lacked as well), so a finer level is finer everywhere.
- Part C: the NACA 0012 through the app ("2D airfoil" preset, TMR inputs only): the 10 deg study converges
  monotonically (CL GCI 1.9 %, CD 0.86 %); medium level: 0 deg **PASS** (CD -6.9 %), 10 deg **PASS** (CL -1.8 %,
  CD -2.5 %), 15 deg **PASS** (CL -2.3 %, CD +3.9 %); docs/validation/naca0012/RESULT.md, Round 3.
- Machine time: round 2 about 62 min, round 3 about 42 min. No OpenFOAM process left running.

- Follow-up (owner review of round 3: D-126 accepted): D-127's 3D part checked on real mesh-only studies of the
  sphere and the half wing (docs/validation/study3d/RESULT.md): valid, same layers and quality as single meshes, but
  the transition zone is not refined by the level ratio: does not pass, D-127 stays Proposed (QUESTIONS 204); a
  wall-resolved study places the current settings within the first-layer limit itself (D-128).

### Previous branch (task/w2-aoa-2d, published in PR #28)

Angle of attack by rotation (D-120), the 2D section mode (D-121), the wall-resolved layer controls (D-122) and the
NACA 0012 round 1 (0 deg PASS, 10 and 15 deg FAIL); accepted in the owner's review of round 1.

### Previous branch (task/5.x-parallel-mesh, published in PR #26)

Parallel snappyHexMesh (D-111), the whole-codebase review and its follow-up (D-112 to D-115), the owner
review of the Proposed decisions (QUESTIONS 162 to 166).

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
| 3.4 | Domain and boundary definition | done; box, bullet and C-type shapes, Generate domain operation (D-078); ground plane on the box (D-116) |
| 3.5 | Surface-to-patch assignment | done (D-071): regions, angle split, patches in the meshing dictionary |
| 4.1 | Physics continua | done for steady incompressible RANS (merged in PR #13) |
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022) and internal flow: velocity, mass-flow and total-pressure inlets, static outlet (D-129) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE; Ahmed body 25 degrees, W1 closed: FAIL, a documented known limitation; round 4 inconclusive, docs/validation/ahmed/RESULT.md); docs/reference/turbulence_mapping.md not written |
| 4.4 | Numerics presets | preset "robust" only (merged in PR #13) |
| 5.0 | Meshing benchmark suite | done (D-081, D-082): sphere, wing, Ahmed-type body; baseline in benchmarks/BASELINE.md; the dirty-STL set and solver convergence are not in it |
| 5.1 | M1: GUI over snappyHexMesh | done (published in PR #11 and #12); y+ layer sizing done (D-024, D-026, D-045); sizing defaults revised after the baseline (D-084 to D-086, task 5.1-sizing); user refinement volumes and the wake helper (D-103, task 5.x-refinement-volumes; no viewer drag handles) |
| 5.2 | M2: surface preparation | first step done (D-093, D-094): Surface Preparation operation (diagnostics, intersection features, CAD union), local benchmark cases with fidelity against a reference; no shell wrapper; dirty-STL set not in the benchmark |
| 5.3 | M3: alternative volume mesher | cfMesh evaluated (D-102, benchmarks/RESULT_5.3.md): recommendation keep snappyHexMesh, owner decision pending (QUESTIONS 130); benchmark-only `--mesher cfmesh`; Gmsh not evaluated |
| 5.4 | M4: prism layer robustness | closed (owner review of 5.4b; D-105 to D-110, benchmarks/RESULT_5.4.md, RESULT_5.4b.md): robust y+ layer defaults (cap 12, ratio up to 1.3, featureAngle 130, nOuterIter 2, tet check on), y+ target at the first cell centre, achieved first cell reported; half wing and Ahmed body above 85 % strict coverage, aircraft valid but its zones not covered |
| 5.5 | M5: own mesher (go/no-go) | not started |
| 6.1 | Monitors and reports | done: report slots with Cd, Cl, Cm pitch and wall y+ (D-048); reference values (D-047); stopping criteria (runTimeControl for residuals, app-side range-based asymptotic criterion), convergence banner and oscillation warning (D-058, D-059); force breakdown, body-axis x_cp, mass balance, cellPoint probes (D-060) |
| 6.2 | Scenes and derived parts | Cp along wall sections with CSV export (D-062); Cf / Cf_x and separation highlight (D-061); scalar scenes done (D-053): field/colormap/range selection, scalar bar, section; clips, isosurfaces, streamlines (their own scalar bar, D-136), line plots (D-136) and saved views (D-132); image export (D-133) |
| 6.3 | Data export and reports | section and line plot CSV export (D-062, D-136); the HTML report (D-134) with the mesh study, polar sweep and line plot sections and a section choice per project (D-136) |
| 6.4 | Mesh independence study (GCI) | done (D-066): Mesh Study node, three levels, Celik GCI, results window and CSV; flat plate Case B not reproduced through the workflow (item 72) |
| 6.5 | Angle-of-attack sweep (polars) | done (D-067, D-120): Polar Sweep node, one mesh per angle (the parts rotated), resumable, CL-alpha / drag polar / CM-alpha, CSV; NACA 0012 validated at 0 deg, fails on drag at 10 and 15 deg (QUESTIONS 190) |
| 6.6 | Parallel runs (mpirun) | done (D-063 Accepted): decomposePar / mpirun / reconstructPar, clean stop through mpirun; speedup study and recommended cores (D-064); parallel snappyHexMesh reconstructed to a serial mesh, also for the mesh study levels (D-111 accepted) |
| 7.1-7.3 | Coupled solver analysis | not started |
| 8.1-8.5 | Moving meshes | not started |
| 9.1 | Project management | partly done: save/load, undo/redo, start screen, recent projects, project folders, presets (D-077); cloning not started |
| 9.2 | Scripting API | not started |
| 9.3 | Installer and docs | done for v1 (D-137 to D-139): scripts/install.sh, the start-up OpenFOAM check, docs/manual/, CHANGELOG.md, version 1.0.0; the owner's clean-install test passed; the Start menu entry not yet seen (QUESTIONS 214) |

## Known issues

- The Ahmed body 25 degree validation (W1, closed) FAILS V6: a documented known limitation of steady SST with
  wall functions at 25 degrees, accepted for v1 (round 2's fine body Cd 0.3246, +13.9 % against the
  experiment, +5.6 % against Guilmineau 2008); no round reproduces the experiment's slant reattachment;
  steady SST oscillates here; round 4 (wall-resolved attempt) inconclusive (docs/validation/ahmed/RESULT.md,
  "Conclusion").
- NACA 0012 at 0 deg: CD -6.9 % against TMR SST (PASS; likely SST-2003 against SSTm, not established, QUESTIONS 194).

## Notes for the user manual

Written into docs/manual/ (task w4-w5); the draft notes kept here until then are in its chapters 2 to 8.

## Known debts

- Courant number: parsed from logs (foam/logparse.py) but no warning in the GUI.
- Parallel speedup saturates at about 3 on 8 cores (memory-bandwidth bound, docs/validation/parallel/README.md); the recommended-core cap of 4 is a constant for this machine (item 69).
- Location of user projects and run outputs in the released app (run/ is development only).
- Changing a CAD part's deflection re-tessellates from the CAD and drops an earlier repair (D-072).
- Preset boundary types are stored but there is one boundary type per domain role today (QUESTIONS 78); internal flow sets its inlet and outlet types per patch in the project, not in the preset (D-129).
- An internal-flow boundary is keyed by its patch name: renaming a region's patch leaves the old entry behind and the renamed patch becomes a wall until its role is set again.
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today (curvature refinement is reported as its finest level, D-085).
- Per-part surface size (one target surface size for all parts today).
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
