# Status

Updated 2026-10-22 (task/w3-internal: W3 internal flow).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/w3-internal** (not yet published). Workstream W3, internal flow, **closed by the I5 verdicts**; then the first
W4 slice (below, when committed). Done on it:
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
- Machine time about 1 h 10 min (3D check 6 min, benchmark 3 min, pipe 10 min, step 50 min, the rest tests and
  trials). No OpenFOAM process left running.

Next: the owner's review of D-129 to D-131 and QUESTIONS 204 to 209. Open: docs/QUESTIONS.md items 30, 67, 69, 70,
72, 73, 75, 82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 204 to 209.

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
| 6.2 | Scenes and derived parts | Cp along wall sections with CSV export (D-062); Cf / Cf_x and separation highlight (D-061); scalar scenes done (D-053): field/colormap/range selection, scalar bar, section; scene saving, image export, iso-surfaces and streamlines not started |
| 6.3 | Data export and reports | not started (section CSV export only, D-062) |
| 6.4 | Mesh independence study (GCI) | done (D-066): Mesh Study node, three levels, Celik GCI, results window and CSV; flat plate Case B not reproduced through the workflow (item 72) |
| 6.5 | Angle-of-attack sweep (polars) | done (D-067, D-120): Polar Sweep node, one mesh per angle (the parts rotated), resumable, CL-alpha / drag polar / CM-alpha, CSV; NACA 0012 validated at 0 deg, fails on drag at 10 and 15 deg (QUESTIONS 190) |
| 6.6 | Parallel runs (mpirun) | done (D-063 Accepted): decomposePar / mpirun / reconstructPar, clean stop through mpirun; speedup study and recommended cores (D-064); parallel snappyHexMesh reconstructed to a serial mesh, also for the mesh study levels (D-111 accepted) |
| 7.1-7.3 | Coupled solver analysis | not started |
| 8.1-8.5 | Moving meshes | not started |
| 9.1 | Project management | partly done: save/load, undo/redo, start screen, recent projects, project folders, presets (D-077); cloning not started |
| 9.2 | Scripting API | not started |
| 9.3 | Installer and docs | not started |

## Known issues

- The Ahmed body 25 degree validation (W1, closed) FAILS V6: a documented known limitation of steady SST with
  wall functions at 25 degrees, accepted for v1 (round 2's fine body Cd 0.3246, +13.9 % against the
  experiment, +5.6 % against Guilmineau 2008); no round reproduces the experiment's slant reattachment;
  steady SST oscillates here; round 4 (wall-resolved attempt) inconclusive (docs/validation/ahmed/RESULT.md,
  "Conclusion").
- NACA 0012 at 0 deg: CD -6.9 % against TMR SST (PASS; likely SST-2003 against SSTm, not established, QUESTIONS 194).

## Notes for the user manual (draft)

- Bluff bodies with strong separation: steady SST can over-predict drag by 10-15 %; use the mean-stable
  criterion (Ahmed body 25 degrees, docs/validation/ahmed/RESULT.md).
- Steady k-omega SST with wall functions over-predicts the drag of the Ahmed body at 25 degrees by about 14 %
  (body Cd 0.325 against the experimental 0.285; docs/validation/ahmed/RESULT.md).
- 2D airfoils: use the "2D airfoil" preset; it switches to wall-resolved layers and second-order turbulence
  automatically (D-123, D-126): y+ 1 at the first cell centre, a stack one surface cell thick, a 12-cell staircase
  around the airfoil (D-124), then k and omega first order to the stopping criteria and second order to the criteria
  again in the same run (the monitors show the stage). NACA 0012 at Re 6e6 through the preset: CL within 2.3 % and
  CD within 6.9 % of the NASA TMR SST results at 0, 10 and 15 degrees (docs/validation/naca0012/RESULT.md).
- Wall-resolved (y+ about 1) layers are used automatically when the target y+ is below 5 (D-123), or chosen in
  Mesh > Layer controls "wall_resolved" (D-122): the surface is refined to at most 220 first layers, which is fine
  for 2D sections and costly on 3D bodies.
- Internal flow (D-129): New simulation > "Internal flow" (3D, wall functions) or "2D internal flow" (a section,
  wall-resolved). Import ONE closed surface whose solids (multi-solid STL) or CAD faces separate the inlets, the
  outlets and the walls: in an internal project each solid becomes its own patch. Set each patch's role under
  Regions > Fluid Region (a patch is a wall until set); an open geometry is refused with the number of open edges
  (use Surface Preparation or Repair). A region named "inlet" or "outlet" becomes the mesh patch "inlet_1" /
  "outlet_1" (the reports use the mesh names). Add cutting planes and pressure drops under Reports & Monitors >
  Planes & Pressure Drops; the Internal flow table shows the mass flow and the area- and mass-averaged static and
  total pressure per inlet, outlet and plane.
- Which inlet: a mass-flow inlet when the flow rate is known (the most robust: the pipe converged in 502
  iterations); a velocity inlet when the inlet speed is known; a total-pressure inlet for a plenum or reservoir at a
  known pressure, the flow rate then follows from the losses (it solves with SIMPLE and a relaxed pressure, D-131:
  slower, 1,858 iterations on the same pipe). Inlet turbulence: intensity and a length scale (default 0.07 x the
  patch's hydraulic diameter). The outlet is a static pressure, safe on backflow.
- Friction losses: put two planes in the developed region (the pipe: 50 and 70 D) and read the pressure drop
  between them; the planes are written a hair (1e-6 of the parts' extent) along their normal so they never lie on a
  layer of mesh faces.
- A mesh study of a 2D airfoil: set the Mesh Study's "current as" to medium with the preset's mesh, so the coarse
  level stays within the wall-resolved limit (QUESTIONS 199).

## Known debts

- GPU environment variables (GALLIUM_DRIVER=d3d12, MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA) are set in
  the user's ~/.bashrc; the app should set them at startup when they are not set.
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
