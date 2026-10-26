# Changelog

## 1.0.1 (unreleased)

### Security

- Security: Pillow updated to 13.0.0, fixing 41 advisories (the open Dependabot alerts, among them heap overflows in
  the JPEG, TIFF and FlashPix decoders and an argument injection in the Ghostscript call), and certifi updated to
  2026.10.23, fixing 1 advisory (GHSA-6q48-6c7w-9gw2: the emSign ECC Root CA - G3, whose intermediate CAs' keys were
  compromised, is no longer trusted); D-180. VortexCFD does not open user images (Pillow writes the PNG exports and
  the .ico); nothing else changed.

## 1.0.0 (2026-10-24)

The first release of VortexCFD: a desktop workflow for steady, incompressible RANS flow on top of OpenFOAM ESI
v2606, from geometry to report in one simulation tree, without editing OpenFOAM dictionaries by hand. Every case it
writes is a standard OpenFOAM case. The decisions behind each feature are in DECISIONS.md (D-numbers below); the
user manual is docs/manual/.

### Requirements

- Windows 11 with **WSL2, Ubuntu 24.04** (the window appears through WSLg).
- **Python 3.12** (Ubuntu 24.04's own, with `python3.12-venv`).
- **OpenFOAM ESI v2606** (`openfoam2606-default` from the ESI packages). Without it the app opens and shows
  projects, meshes and results, but cannot mesh or solve.
- **ParaView is optional**: "Open in ParaView" uses a configured path, `paraview` on PATH (`sudo apt install
  paraview`) or ParaView for Windows under C:\Program Files (D-138).
- Install: `scripts/install.sh` (a virtual environment with pinned dependencies, the `vortexcfd` command, a desktop
  entry; never uses sudo; D-137). Qt comes from PySide6-Essentials only (D-139).

### Features by area

**Project and workflow**
- One simulation tree: geometry, domain, mesh, physics, run, results; undo/redo of every edit; save/load, project
  folders, recent projects, the start screen and presets: External flow, Internal flow, 2D airfoil, 2D internal
  flow, Empty (D-077).
- A start-up OpenFOAM v2606 check with the install commands shown, never run (D-137); `vortexcfd --version`,
  `vortexcfd --check-openfoam`.

**Geometry**
- STL import (multi-solid, self-intersection check; D-069) and CAD import: STEP, IGES, BREP with face names,
  colours and assemblies (D-070).
- Repair with pymeshfix and an fTetWild envelope, with a before / after report (D-072); surface preparation
  diagnostics, intersection features and CAD union (D-093).
- Regions and patches by angle split (D-071); airfoil import from Selig and Lednicer coordinate files (D-121).
- Angle of attack by rotating the parts about the centre of rotation, forces in wind axes (D-120); in the
  interface the Body attitude of the Geometry node (D-148).

**Domain**
- Box, bullet and C-type domains as an explicit operation, symmetry plane, ground plane on the box (D-078, D-116).
- Internal flow: the inside of a closed geometry, with patch roles (D-129).
- A 2D section mode in the x-z plane (D-121), shown looking along +y with the flow left to right (D-140).

**Meshing (snappyHexMesh)**
- Sizing from the reference length with curvature refinement (D-084 to D-086), refinement volumes and a wake
  helper (D-103); parallel meshing (D-111).
- Prism layers sized from a target y+ at the first cell centre, robust defaults and the achieved first cell
  reported (D-105 to D-109); wall-resolved layer controls below y+ 5 (D-122 to D-125, D-135).
- 2D meshes: one cell across the span by directional refinement and extrudeMesh (D-121).
- A mesh report: checkMesh, quality, layer coverage, first cell against the plan; a mesh scene with a section
  plane; the domain guard against lost patches.

**Physics and solver**
- simpleFoam with k-omega SST; external-aerodynamics boundary conditions (D-022); internal flow with velocity,
  mass-flow and total-pressure inlets and a static outlet (D-129, D-131).
- Two turbulence stages for wall-resolved runs (D-126).
- Serial or parallel runs (decomposePar / mpirun / reconstructPar) with a recommended core count (D-063, D-064).
- Stopping criteria: residuals, the asymptotic criterion and the mean-stable criterion on windowed means (D-058,
  D-059, D-118, D-119).

**Monitoring**
- The console with the solver log, a live residual chart, report slots (Cd, Cl, Cm pitch, wall y+) with windowed
  means and half ranges, force breakdown, mass balance, probes (D-047, D-048, D-060).

**Studies**
- A three-level mesh study with Celik GCI (D-066, D-127, D-128).
- A polar sweep: one mesh per angle, resumable, CL-alpha, drag polar and CM-alpha (D-067, D-120).

**Results and reports**
- Scalar scenes on walls and sections, Cp and Cf, separation highlight, Cp sections with CSV export (D-053, D-054,
  D-061, D-062).
- Results scene objects: clips, isosurfaces, streamlines with their own scalar bar, line plots with PNG and CSV
  export; saved views (D-132, D-136).
- Image export rendered offscreen at the chosen size (D-133).
- A self-contained HTML report: set-up, geometry, mesh, convergence, forces or internal-flow means, the mesh study's
  GCI table, the polar sweep's table and plot, line plots and saved views; sections chosen per project (D-134,
  D-136).
- Open in ParaView (D-055, D-138).

### Since 1.0.0rc1

What changed between 1.0.0rc1 (task w4-w5) and the tag.

#### Release polish (tasks rc1-polish and release-1.0.0)

- ParaView is optional: found on PATH, from Preferences or as ParaView for Windows, with an install tip on the
  disabled button; a configured path that does not exist falls back to detection (D-138, QUESTIONS 220).
- Qt from PySide6-Essentials only (pinned): the install 1870 MB -> 1442 MB (D-139).
- 2D cases shown and exported looking along +y, the flow left to right (D-140, [NUMERICS-REVIEW]).

#### The first interface round (task gui-polish)

- A welcome screen with two large buttons and an open panel listing the recent projects (name, folder, last
  opened; right-click to remove one); a New simulation dialog with the presets as a described list, inline
  validation and the cores as "N / physical" (D-142, D-143). Recent projects never record temporary folders and
  missing ones are pruned; tests and scripts never touch the user's settings (D-141).
- The Zinc & Teal theme: teal selection and primary actions, amber for highlights and warnings, every text pair
  at least WCAG AA (D-144).
- A right-click menu on every tree node, Delete (after asking), F2 and double-click (D-145); refinement regions
  from imported closed surfaces or from a part (D-145); one explained Surface Preparation action (D-146).
- Every domain face's boundary type editable: velocity inlet, pressure outlet, slip, symmetry, wall, moving wall,
  or the ground plane (D-147).
- The properties panel: View > Interface size (Small by default), compact rows, collapsible sections with a "?"
  to the manual's new chapter 9, detachable into its own window, units on every value, Auto boxes showing the
  values in use, the free stream (renamed from Inflow) and the angle of attack as the body attitude, domain
  extents in L, m or mm, probes and the centre of rotation as one "(x, y, z)" field, the mesh independence study
  explained, the polar sweep opt-in (D-148).
- Results snapshots and a Compare tab: overlays, value and set-up difference tables, PNG / CSV export and a
  Comparison section in the report (D-149); Show in OpenFOAM file on every written property (D-150); Open in
  ParaView in the top bar (D-151).
- One set of text roles for every text (D-153); every screen checked, and tested, at three window and three
  interface sizes, with a sensible minimum size, the monitors column scrolling and nothing clipped (D-154, D-155,
  D-158); the residual chart and the convergence criteria in windows of their own, remembered (D-156).
- Domain extents in m or mm kept as fixed lengths (schema v23, D-157); open surfaces as distance-mode refinement
  regions (D-159); snapshots sample every line plot (D-160); optional prism layers on wall domain faces, off by
  default (D-161).

#### The second interface round (task gui-2)

**Running and continuing**
- Continue Solver: a stopped run, or one at its iteration limit, goes on from its latest written time; the iteration
  count, the residual and report histories and the stopping criteria's windows continue; the run record keeps each
  run; the limit is the total (asked for more at the limit); two stages resume in their stage; a parallel case keeps
  its decomposition on the same cores; a changed set-up asks to continue from the current solution or start over; a
  changed mesh offers Clear Solution (D-171, [NUMERICS-REVIEW]).
- Continue Solver after "Criteria met" too: more iterations and, in the same dialog, tighter criteria (each threshold
  or tolerance editable, saved in the project) (D-176).
- Results while the solver runs: the live view of the walls and the Results Scene's planes every N iterations
  ("Live · iteration N"; Solvers > Live view, default 50), and Write Fields Now (SIGUSR2, the run goes on; parallel:
  read decomposed, reconstructed at the end) (D-172, [NUMERICS-REVIEW]; the benchmark and validation dictionaries are
  unchanged).
- The Solution menu (Generate Mesh F6, Clear Mesh, Run / Continue F5, Stop Shift+F5, Clear Solution, Write Fields Now,
  the studies, ParaView): the same actions as the top bar and the tree; disabled entries say why (D-173).
- Run Solver saves the project first (D-165).

**Reading the results**
- The Reynolds and Mach numbers, live, with what they are taken on; the speed of sound (schema v24); a warning above
  Mach 0.3; internal flow on each inlet's hydraulic diameter; in the report and the snapshots (D-168).
- A readable iteration axis on every chart: 1-2-5 ticks, minor ticks, a light grid, thousands separators, zoom and pan
  (D-169).
- Report charts in their own windows: the whole history, the windowed mean and the oscillation band, PNG and CSV,
  live (D-170).

**Clarity**
- The monitors show the criteria of the run they judge, apart from the project's; the properties panel shows only the
  selected node's rows (D-165).
- Readable values everywhere ("Incompressible, steady", "k-ω SST") and every number with its unit (D-166).
- The angle of attack said where users look for it: the Free stream's link, "Geometry · α 4°", the Body attitude
  explained (D-167).

**Convergence panel**
- "Satisfied now" says whether each criterion holds at the last iteration ("yes", "no", "not yet: 40 of 50
  iterations", "yes (stops from 3,502)" before it may stop the run); it said "no" for every criterion of a two-stage
  run stopped before stage 2's minimum, although all held (D-178).
- "Residuals met, but Cl is still changing": a warning when every residual criterion holds while a monitored force
  coefficient still drifts (D-178).
- A mass imbalance below what the postProcessing files resolve shows as "< 4.7e-05" (%), not 0 (D-178).

**Projects**
- Save As copies the mesh and results by default (with the size, progress and Cancel); the duplicate opens with its
  results and can continue (D-174, amending D-079).

#### Branding

- The logo: the generator ported (scripts/brand/make_logo.py, matching the saved mark), the icons (PNG, .ico), the
  lockups with the word as paths (Sora, OFL-1.1), in the window icon, the top bar, the start screen, About, the
  desktop entry, the README, the manual and the report (D-175).
- The logo is licensed under CC BY-SA 4.0, separately from the code's GPL-3.0-or-later (assets/branding/LICENSE,
  Copyright 2026 Víctor Sánchez Escalante); please do not use it in a way that suggests a fork is the official project
  (D-177).
- The taskbar shows the logo under WSLg: the window's app id and WM_CLASS are "vortexcfd", the name of the desktop
  entry install.sh writes (its icon by absolute path; `--desktop-only` writes it again); scripts/windows/make_shortcut.ps1
  makes a Start-menu and desktop shortcut with the logo for Windows (D-179).

#### Fixed

- Two intermittent test failures, both races at the end of a worker thread: a study's or sweep's end now reaches
  the window after its thread has ended (the flaky sweep test, D-163), and worker threads stop emitting before their
  window is deleted, viewers closed first (the offscreen teardown crash, D-164).

### Validation

Each case was run through the app's own pipeline; the records are in docs/validation/ (manual chapter 8).

| Case | What it checks | Verdict |
|---|---|---|
| Flat plate, zero pressure gradient (NASA TMR) | k-omega SST with wall functions: skin friction | **PASS WITH NOTE**: Cf(0.97) 3.3 % below the TMR reference, unexplained |
| Ahmed body, 25 degree slant, in ground proximity | body drag against Ahmed et al. (1984) | **FAIL**, a documented known limitation accepted for v1: body Cd 0.3246, +13.9 % against the experiment (+5.6 % against Guilmineau 2008's steady SST) |
| NACA 0012, 2D, Re 6e6, 0 / 10 / 15 degrees (NASA TMR) | wall-resolved SST, angle of attack by rotation, the 2D mode | **PASS** at every angle: CL -0.0 / -1.8 / -2.3 %, CD -6.9 / -2.5 / +3.9 % against the TMR SST codes; the 10 degree study converges (CL GCI 1.9 %, CD 0.86 %) |
| Turbulent smooth pipe, Re 1e5 | internal flow: mass-flow and total-pressure inlets | **PASS**: Darcy f +1.36 % against Prandtl-Karman, mass balance 0.0 %; one mesh level (no GCI) |
| Backward-facing step, 2D, Re_H 36,000 (NASA TMR) | internal 2D wall-resolved flow: reattachment length | **PASS WITH NOTE**: x_r 6.434 H on the finest level, +2.8 % against the experiment (-1.0 % against TMR SST); three valid levels, oscillatory, no GCI |
| Parallel speed-up | solver speed-up with MPI ranks | a measurement: about 3 on 8 cores (memory bound) |

### Known limitations

- **Steady incompressible RANS only**: one solver (simpleFoam), one turbulence model (k-omega SST); no transient
  runs, compressible flow, heat transfer, moving meshes or rotating zones.
- **Bluff bodies with strong separation**: steady SST with wall functions over-predicts the Ahmed body's drag at 25
  degrees by about 14 %; treat such drag as indicative.
- **The 3D mesh study's GCI is indicative**: its levels do not refine the transition zones around the parts by the
  level ratio (D-127); the 2D study refines everywhere.
- **Flat plate skin friction** 3.3 % below the TMR reference, unexplained.
- **NACA 0012 at 0 degrees**: CD 6.9 % below TMR SST (inside PASS; likely SST-2003 against TMR's SSTm).
- **One layer specification for all walls**; one boundary type per domain role in external flow.
- **One platform**: WSL2 Ubuntu 24.04 with Python 3.12; the WSLg Start menu entry has not been seen yet.

Images and reports made with versions before 1.0.0rc1 used PyVista's default camera (D-133 note): make them again.
