# Status

Updated 2026-10-21 (task/validation-ahmed: ground plane boundary and the Ahmed 25 degree force validation; round 2).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/validation-ahmed** (not yet published). Done on it:
- Part A ([NUMERICS-REVIEW], D-116, schema v16): the box domain's ground plane: the z-min face as the wall
  patch "ground" (stationary noSlip or moving at U_inf along +x; at the parts' lowest z or a set z; the
  parts' wall functions; prism layers optional, off by default); forces and the part y+ leave it out;
  presets store it; tree node and properties rows. D-117: the mesh study levels keep the refinement
  volumes and junction curves (they were dropped before).
- Part B: docs/validation/ahmed/SETUP.md: the half Ahmed body (25 degrees) and two 30 mm stilts generated
  by code (tests/validation/ahmed_case.py), Ahmed et al. (1984)'s 60 m/s, Re_L 4.29e6, stationary ground
  from 1.35 L ahead, A_ref the body's frontal area; wake helper and slant volumes;
  scripts/validation/ahmed_study.py.
- Part C: three levels through the app's mesh study (202,717 / 524,785 / 1,338,191 cells, all checkMesh
  OK), 1500 iterations each; the steady solution oscillates about a stationary mean, so no level met the
  app's stopping criteria and the values are last-1000-iteration means (QUESTIONS 170).
- Part D: docs/validation/ahmed/RESULT.md: fine-grid body Cd 0.3250 against 0.285 (+14.0 %), oscillatory
  GCI (no extrapolation), published SST 0.284-0.313: **verdict FAIL** (V6); Cl 0.38, pressure share
  85.9 %; the fine grid's slant bubble reattaches at 80 % of the slant (coarser grids separate to the
  base). tests/validation/test_ahmed.py (marker validation, not run) re-checks the verdict inputs.
  Machine time about 2 h 17 min.
- QUESTIONS 163 to 166 are closed (accepted as implemented by the owner); 167 stays open.
- Round 2 (owner review of round 1; QUESTIONS 168 b, 169, 170, 173 decided):
  - Part A ([NUMERICS-REVIEW], D-118, schema v17): the ground's slip strip (`Ground.wall_start_x`: the
    bottom face split into `ground_slip` and `ground` by two blockMesh blocks at a background cell face)
    and the mean-stable stopping criterion (W 500, tol 0.5 %, from round 1's Cd histories: it would have
    stopped them at 1002 / 1003 / 1036); windowed mean and oscillation in the report slots and the Forces
    table; the oscillation warning suggests the criterion. D-116 and D-117 Accepted.
  - Part B: no reference papers supplied (`~/vortexcfd-geometry/refs/` absent): 0.285 kept as quoted.
  - Part C: SETUP.md "Round 2" (inlet 5 L, ground wall from 1.35 L ahead, ground layers, mean-stable stop,
    8 + 8 cores; project run/validation/ahmed/ahmed25_r2, round 1 untouched); the driver runs one level
    per command with a deadline guard (`prepare_study(only=...)`).
  - Part D: coarse and medium run (RESULT.md "Round 2"): body Cd 0.3003 / 0.3272 (round 1 0.3409 /
    0.3468), both stopped by the mean-stable criterion (1162 / 1004); ground y+ under the body 316 / 602
    (round 1 1,707 / 1,240); the slant still separated on both.
  - Part E: the fine level (1,614,529 cells, mean-stable stop at 1021, 70 min on 8 cores): body Cd
    0.3246, +13.9 % against 0.285, above the published SST range: **verdict FAIL** (V6), as round 1. GCI
    oscillatory (+9.0 % / -0.8 %: medium and fine agree within the oscillation, coarse is the outlier);
    the fine slant has a closed bubble reattaching at 0.6-0.7 of the slant (40 % of its area reversed).
    The set-up fixes change Cd by -11.9 / -5.7 / -0.1 % (coarse / medium / fine). The separating coarse run
    without ground layers (`--round 3`, QUESTIONS 177): 0.3189, about half of the coarse drop each from
    the inlet and the ground layers, but that run converged steady (indicative only). D-118 Accepted;
    QUESTIONS 176 and 178 accepted.

Next: QUESTIONS 175 (the mesh study's values from the mean-stable window; owner: fix it next); the owner's
review of the Ahmed round 2 verdict and QUESTIONS 177. Then the
aircraft's zones (QUESTIONS 147); drag handles for the refinement volumes (item 132). The owner runs
scripts/ship.sh (the slow tests, item 161). Open: docs/QUESTIONS.md items 30, 67, 69, 70, 71, 72, 73, 75,
82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 171, 172, 174, 175 and 177.

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
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE; Ahmed body 25 degrees: FAIL in rounds 1 and 2, docs/validation/ahmed/RESULT.md); docs/reference/turbulence_mapping.md not written |
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
| 6.5 | Angle-of-attack sweep (polars) | done (D-067): Polar Sweep node, points on the current mesh initialised from the previous converged point, CL-alpha / drag polar / CM-alpha, CSV; NACA 0012 check waits for the wing case |
| 6.6 | Parallel runs (mpirun) | done (D-063 Accepted): decomposePar / mpirun / reconstructPar, clean stop through mpirun; speedup study and recommended cores (D-064); parallel snappyHexMesh reconstructed to a serial mesh, also for the mesh study levels (D-111 accepted) |
| 7.1-7.3 | Coupled solver analysis | not started |
| 8.1-8.5 | Moving meshes | not started |
| 9.1 | Project management | partly done: save/load, undo/redo, start screen, recent projects, project folders, presets (D-077); cloning not started |
| 9.2 | Scripting API | not started |
| 9.3 | Installer and docs | not started |

## Known issues

- The Ahmed body 25 degree validation FAILS V6 in both rounds (round 2: body Cd +13.9 % on the finest of
  three grids, above the published SST range; no GCI, oscillatory; the steady run oscillates;
  docs/validation/ahmed/RESULT.md).

- Results at angle of attack != 0 are biased by the angled-inlet method with slip far field (QUESTIONS 71, open).

## Notes for the user manual (draft)

- Bluff bodies with strong separation: steady SST can over-predict drag by 10-15 %; use the mean-stable
  criterion (Ahmed body 25 degrees, docs/validation/ahmed/RESULT.md).

## Known debts

- GPU environment variables (GALLIUM_DRIVER=d3d12, MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA) are set in
  the user's ~/.bashrc; the app should set them at startup when they are not set.
- Courant number: parsed from logs (foam/logparse.py) but no warning in the GUI.
- Parallel speedup saturates at about 3 on 8 cores (memory-bandwidth bound, docs/validation/parallel/README.md); the recommended-core cap of 4 is a constant for this machine (item 69).
- Location of user projects and run outputs in the released app (run/ is development only).
- Changing a CAD part's deflection re-tessellates from the CAD and drops an earlier repair (D-072).
- Preset boundary types are stored but there is one boundary type per role today (QUESTIONS 78, for the internal-flow task).
- cfMesh build spike on v2606.
- Total cell estimate: only background cells are estimated today (curvature refinement is reported as its finest level, D-085).
- Per-part surface size (one target surface size for all parts today).
- Solver restart from the latest time: every run starts from 0 (D-046).
- The mesh scene is read on the GUI thread after meshing (MeshView.load): a multi-million-cell mesh
  freezes the window for a moment (docs/QUESTIONS.md item 5).
- Flat plate Cf is 3.3 % below the TMR incompressible SST reference (grid-extrapolated Cf(0.97),
  D-036) and the gap is not explained. Candidates: the omegaWallFunction blending, OpenFOAM's SST
  implementation (TMR's note on standard OpenFOAM), nutUSpaldingWallFunction.
