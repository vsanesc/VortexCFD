# Status

Updated 2026-10-22 (task/w2-aoa-2d: angle of attack by rotation, 2D mode, wall-resolved layers, NACA 0012).
Phases and sub-phases are those of docs/PLAN.md. Updated at the end of every task (CLAUDE.md).

## Current branch

**task/w2-aoa-2d** (not yet published). Workstream W2, first round. Done on it:
- Part A ([NUMERICS-REVIEW], D-120, schema v18): the angle of attack rotates the parts nose up about the CofR
  (flow always +x, wind-axis forces, body-axis C_A / C_N and x_cp); refinement volumes get a body / wind frame;
  rotated parts that cross the ground or leave the domain block meshing; the viewer shows the rotated parts with a
  note; the angled inlet is removed (v17 projects migrate with a note, their rotated meshes out of date); the polar
  sweep meshes every angle, runs them one at a time and resumes after a stop. Sphere check: Cd at 0 and 20 deg
  within 0.10 %, Cl about 0. QUESTIONS 71 closed.
- Part B ([NUMERICS-REVIEW], D-121): the 2D section mode: Selig / Lednicer airfoil import (scale, trailing-edge
  closure), a one-cell slab refined in x and z only (directional shells), extrudeMesh to one cell with the empty
  frontAndBack, A_ref = chord x span; New simulation dialog option, "2D airfoil" preset, Import Airfoil action.
- Part B2 ([NUMERICS-REVIEW], D-122): the wall-resolved layer controls (stack of one surface cell at ratio 1.2,
  surface cell at most 220 first layers, relaxed minDeterminant 1e-5 and maxNonOrtho 75 in the layer phase); the
  study rows in D-122; the benchmark (mesh only) identical to the baseline. QUESTIONS 180 closed.
- Parts C-E: NACA 0012 (TMR, Re 6e6, SST, y+ 1, C-type 100 chords): 0 deg **PASS** (CD -0.1 %); 10 deg **FAIL**
  (CL -3.0 %, CD +24 %, grid- and domain-independent); 15 deg **FAIL** (separated, CD x4, iteration limit);
  docs/validation/naca0012/RESULT.md. The mesh study gained 2D scaling, per-level wall-resolved stacks, the
  first-cell report per level and a before-solve hook; a 2D level writes its own span's reference area.
- Machine time about 65 min. No OpenFOAM process left running.

Next: the owner's review of D-120 to D-122 and QUESTIONS 183 to 192; a second NACA round on the turbulence numerics
or wall conditions (QUESTIONS 190). Open: docs/QUESTIONS.md items 30, 67, 69, 70, 72, 73, 75, 82, 89 to 94, 96,
97, 122, 124, 125 to 128, 130, 131, 147, 167, 168 (a, c), 174, 183 to 191.

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
- NACA 0012 (2D, wall-resolved SST): drag too high with lift (+24 % at 10 deg; 15 deg separates; QUESTIONS 190).
- The wall-resolved layer mode produced one invalid mesh (the fine 0 deg NACA, QUESTIONS 191).

## Notes for the user manual (draft)

- Bluff bodies with strong separation: steady SST can over-predict drag by 10-15 %; use the mean-stable
  criterion (Ahmed body 25 degrees, docs/validation/ahmed/RESULT.md).
- Steady k-omega SST with wall functions over-predicts the drag of the Ahmed body at 25 degrees by about 14 %
  (body Cd 0.325 against the experimental 0.285; docs/validation/ahmed/RESULT.md).
- Wall-resolved (y+ about 1) layers need Mesh > Layer controls "wall_resolved" (D-122): it refines the surface to
  at most 220 first layers, which is fine for 2D sections and costly on 3D bodies.

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
