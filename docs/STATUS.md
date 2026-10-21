# Status

Updated 2026-10-21 (task/5.x-parallel-mesh: parallel snappyHexMesh; owner review applied; whole-codebase review and its follow-up).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/5.x-parallel-mesh** (not yet published). Done on it (D-111, benchmarks/RESULT_parallel_mesh.md):
- Part A ([NUMERICS-REVIEW], schema v15): with Mesh cores N > 1 the pipeline is blockMesh, surfaceFeatureExtract,
  decomposePar (scotch), every snappyHexMesh pass through mpirun on one decomposition, reconstructParMesh
  -constant, then createPatch and checkMesh on the serial mesh; processor*/ removed after the reconstruction
  and after a stop or failure; a new meshing case drops the old mesh record. Mesh properties: "Mesh cores"
  (auto = the meshing recommendation, see the owner review below) and "Cores used"; the mesh record keeps the cores.
  Benchmark `--mesh-cores` (default serial) and the summed memory of all ranks.
- Part B: mesh only at 1 / 4 / 8 cores: speedup at 8 cores 2.13 sphere, 1.97 half wing, 1.85 Ahmed body,
  4.13 aircraft (497 -> 120 s); validity, checks, strict coverage (overall and zones), first cell and
  fidelity the same to the noise. Meshing cap rule: background cells / 12,500, at most 8. Machine time
  about 29 min.
- Owner review: D-111 accepted with two changes, QUESTIONS 154 and 157-161 accepted.
  - QUESTIONS 155 ([NUMERICS-REVIEW]): automatic meshing cores = min(physical cores, background cells /
    12,500, 8), independent of the Solvers cores (the solver's cap of 4 measured the solver); the solver
    recommendation is unchanged. Automatic cores of the benchmark cases: sphere 8, half wing 7, Ahmed body 7,
    aircraft 7 (99,200-100,860 background cells).
  - QUESTIONS 156: the mesh study meshes every level on the project's meshing cores, one level at a time,
    processor*/ cleaned per level; a real 2-level sphere study on 4 cores took 34 s.

- Whole-codebase review (docs/REVIEW.md, 2026-10-20): 42 findings, 3 SAFE fixes applied (the surface
  preparation's hidden-segment filter 4.2x faster with the same mask, its segments computed once, the
  monitors' force breakdown cached per time); the dictionaries of the public cases and the cavity are
  byte-identical before and after; the benchmark compare was not run (stopped early). The remaining
  SAFE fixes are listed in REVIEW.md section 8; the FROZEN findings for the owner in section 7.
- Review follow-up (2026-10-21, REVIEW.md sections 8b and 9): runs bound to the case they started in (R-01,
  D-112); every background run reports its end after an exception (R-02, D-113); atomic project, preset and
  record files with the umask's mode (R-04/R-05, D-114); the placeholder Add part item disabled (R-18, D-115);
  numpy declared (R-40); DECISIONS statuses (R-39: D-068, D-088 accepted, 16 entries for the owner in
  QUESTIONS 162); the layer walk vectorised, bitwise identical (R-25). Verified: the aircraft surface
  preparation byte-identical before and after 773ed53; the benchmark mesh metrics equal to baseline.json;
  the dictionaries of the public cases and the cavity identical.

Next: the aircraft's zones (QUESTIONS 147); drag handles for the refinement volumes (item 132). The owner
runs scripts/ship.sh (the slow tests, item 161). Open: docs/QUESTIONS.md items 30, 67, 69, 70, 71, 72, 73,
75, 82, 89 to 94, 96, 97, 122, 124, 125 to 128, 130, 131, 147 and 162.

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
| 3.4 | Domain and boundary definition | done; box, bullet and C-type shapes, Generate domain operation (D-078) |
| 3.5 | Surface-to-patch assignment | done (D-071): regions, angle split, patches in the meshing dictionary |
| 4.1 | Physics continua | done for steady incompressible RANS (merged in PR #13) |
| 4.2 | Boundary condition library | done for the external-aerodynamics set (D-022) |
| 4.3 | Turbulence module | done for kOmegaSST (y+ estimator, flat plate verified against TMR: PASS WITH NOTE); docs/reference/turbulence_mapping.md not written |
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

- Results at angle of attack != 0 are biased by the angled-inlet method with slip far field (QUESTIONS 71, open).

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
