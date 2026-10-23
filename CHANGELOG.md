# Changelog

## 1.0.0 (2026-10-23)

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
- Angle of attack by rotating the parts about the centre of rotation, forces in wind axes (D-120).

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
- **No restart**: every run starts from the initial fields.
- **One platform**: WSL2 Ubuntu 24.04 with Python 3.12; the WSLg Start menu entry has not been seen yet.

Images and reports made with versions before 1.0.0rc1 used PyVista's default camera (D-133 note): make them again.
