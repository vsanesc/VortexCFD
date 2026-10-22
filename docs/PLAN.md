# Open-source CFD GUI on OpenFOAM — Development Plan

Working name: VortexCFD. Target: an integrated CFD workflow (single simulation tree, integrated geometry → mesh → physics → solve → post) running on OpenFOAM as the numerical backend.

Progress marks after the sub-phase titles (*done*, *partly done*) follow docs/STATUS.md, which is the
source of truth for the state of each sub-phase.

## 0. Ground rules (apply to every task)

**Scope principles**
- OpenFOAM stays the solver. The GUI orchestrates it via subprocess (WSL/Linux). We do not fork or rewrite solvers unless a phase explicitly says so.
- Reuse before build. Every module starts with a survey of existing tools (decision: reuse / wrap / build).
- Numerical behaviour that is plain OpenFOAM is NOT re-validated. Anything we add or modify numerically (own mesher, layer extrusion, new BC, own turbulence setup logic, own solver variant) gets a simple validation case before it is considered done.

**Validation policy**
| What changed | Minimum validation |
|---|---|
| GUI/templates only (reproduces a known OpenFOAM setup) | Generated case must match a hand-written reference case dictionary-by-dictionary (diff test) |
| Mesher / layers | Benchmark suite (Phase 5.0): checkMesh metrics, layer coverage, y+ distribution |
| Turbulence setup logic (k, omega, nut, wall treatment) | Flat plate (Cf, y+) |
| New/modified solver, BC or numerics | Lid-driven cavity and/or NACA 0012 vs reference data |
| Moving mesh feature | Simple prescribed-motion case with known behaviour |

**Agent workflow (Antigravity implements, Claude reviews)**
- Everything lives in a Git repo. One branch per task, small PRs (< ~400 changed lines).
- Each task below has: Goal, Deliverables, Acceptance criteria. A task is done only when acceptance criteria pass in CI/pytest.
- Tasks tagged `[NUMERICS-REVIEW]` must be reviewed by Claude/Vic before merge (units, BCs, wall treatment, schemes).
- The agent must stop and ask if a task requires an architectural change not in `ARCHITECTURE.md`.
- Keep `ARCHITECTURE.md`, `DECISIONS.md` and the agent rules file updated whenever an interface changes.
- Code and docs in English.

**Open decisions (block Phase 1 until answered)**
1. OpenFOAM flavour/version: ESI (openfoam.com) vs Foundation (openfoam.org).
2. Repo visibility (public/private) and GUI license.
3. Keep the backend abstraction open for SU2 or OpenFOAM-only.

---

## Phase 0 — Reference analysis & foundation

### 0.1 Commercial reference workflow inventory
- Goal: precise map of what a commercial reference workflow does that we want to match.
- Deliverable: a feature inventory (kept by the owner outside the repository) covering: simulation tree structure, object types, meshing operations (surface wrapper, remesher, trimmer, polyhedral, thin mesher, prism layers), mesh controls (base size, relative sizes, custom controls, volumetric controls), physics continua and model selection, turbulence models and wall treatments, solvers (segregated/coupled), reports/monitors/scenes, automation.
- Acceptance: each item has a column "OpenFOAM equivalent", "Gap" (none/partial/missing) and "Priority" (P1/P2/P3).

### 0.2 Open-source landscape survey
- Goal: decide reuse vs wrap vs build per module.
- Candidates to evaluate (verify current status, license and maintenance before relying on them): CfdOF (FreeCAD), SALOME, cfMesh, snappyHexMesh, fTetWild, Gmsh, MMG, CGAL meshing, OpenCASCADE (pythonOCC/cadquery), trimesh/pymeshfix, ParaView/PyVista, Code_Saturne and SU2 GUIs, existing OpenFOAM GUIs.
- Deliverable: `docs/reference/oss_survey.md` with per-tool: purpose, license, last activity, strengths, weaknesses, integration effort, recommendation.
- Acceptance: every gap marked P1/P2 in 0.1 has a recommended source (reuse/wrap/build).

### 0.3 Repo, environment, architecture — *done*
- Deliverables: repo skeleton, `ARCHITECTURE.md`, `DECISIONS.md`, agent rules file, pytest + CI, dev environment script (WSL + OpenFOAM detection), smoke test that runs a trivial OpenFOAM tutorial case from Python.
- Proposed stack (revisable after 0.2): Python 3.11+, PySide6, PyVista/VTK, Jinja2, pydantic for the case model.
- Acceptance: `pytest` green; smoke test runs `blockMesh` + a solver on the cavity and returns exit code 0 with parsed log.

---

## Phase 1 — Core: case model, writer, runner

### 1.1 Simulation data model — *done*
- Goal: internal representation of the simulation tree (Geometry, Regions/Parts, Mesh, Physics, Solvers, Monitors, Reports), serializable to JSON/YAML and versioned.
- Acceptance: round-trip save/load tests; schema version field; migration stub.

### 1.2 Case writer (templates → OpenFOAM dictionaries) — *partly done (cavity reference case)*
- Goal: generate `controlDict`, `fvSchemes`, `fvSolution`, `transportProperties`/`physicalProperties`, `turbulenceProperties`/`momentumTransport`, BC files in `0/`, `snappyHexMeshDict`, etc., with differences between OpenFOAM flavours isolated in one adapter layer.
- Acceptance: for 3 reference cases (cavity, external flow around a cylinder, wing), generated dictionaries match hand-written reference cases (normalized diff test); `checkMesh` and a short solver run pass.

### 1.3 Runner and log parsing — *done for single-process runs*
- Goal: run meshing/solver as subprocesses, stream logs, stop/restart, parallel decomposition, parse residuals, courant, force coefficients.
- Acceptance: unit tests on recorded logs; stopping a run cleanly writes a restartable time.

### 1.4 Integration test — *done (cavity)*
- Goal: model → case → mesh → solve → parsed results, headless (no GUI).
- Acceptance: cavity end-to-end headless in CI.

---

## Phase 2 — GUI shell and 3D viewer

### 2.1 Main window — *done*
- Simulation tree (STAR-style), property panel bound to the data model, undo/redo, project save/load.
- Acceptance: editing a property updates the model; undo/redo covers at least property edits and add/remove nodes.

### 2.2 3D viewer — *done (parts, mesh scene, results scene)*
- PyVista/VTK embedded: geometry, surface/volume mesh, clip/slice, scalar fields, part visibility, picking surfaces.
- Acceptance: loads 1M-triangle STL interactively; picking returns the selected surface/patch id.

### 2.3 Console and live monitors — *done*
- Log console, residual plot, coefficient plots updating while the solver runs.
- Acceptance: plots update at least every few seconds on a running case without freezing the UI (solver runs in a separate process/thread).

---

## Phase 3 — CAD import and geometry (priority 1 from the gap analysis)

### 3.1 Surface mesh import — *done*
- STL (ASCII/binary), OBJ, PLY; units selection; multi-part/multi-solid STL splitting.
- Checks: watertightness, non-manifold edges, inverted normals, self-intersections, tiny/degenerate triangles, duplicate faces. Report in GUI with highlight in viewer.
- Acceptance: test corpus of clean and deliberately broken STLs; each defect type detected.

### 3.2 CAD import (STEP/IGES/BREP)
- Via OpenCASCADE (or the best option from 0.2). Preserve part and face names/colors where available. Tessellation with controllable deflection.
- Acceptance: STEP assembly with named faces imports with part tree; faces selectable as patches.

### 3.3 Geometry repair
- Automated repair pipeline (e.g., hole filling, normal fixing, optional robust remesh via fTetWild-style approaches, per 0.2). Always keep the original and show a before/after report.
- Acceptance: a defined fraction of the broken-STL corpus ends up watertight and snappyHexMesh-ready; failures give actionable messages.

### 3.4 Domain and boundary definition — *done (ground plane boundary of the box domain added in task validation-ahmed, D-116)*
- Box/cylinder far-field domain builder from body bounding box with size multipliers; symmetry planes; named boundaries (inlet, outlet, wall, symmetry, far-field).
- Acceptance: domain generated for a wing and a VTOL STL; boundaries exported as patches consistent with the case writer.

### 3.5 Surface-to-patch assignment
- Group triangles/faces into named patches via selection, angle-based feature splitting, or CAD face names.
- Acceptance: patches persist in the project file and reach the meshing dictionary.

---

## Phase 4 — Physics, boundary templates, turbulence

### 4.1 Physics continua — *done for steady incompressible RANS*
- Presets: steady incompressible RANS, transient incompressible, compressible steady/transient, with energy on/off; fluid properties (air with Sutherland/ideal gas, constants), reference values.
- Solver selection logic: continuum choices → OpenFOAM solver + required fields.
- Acceptance: each preset generates a runnable case on a reference geometry.

### 4.2 Boundary condition library — *done for external aerodynamics*
- Inlet (velocity, mass flow, total pressure), outlet (static pressure), walls (no-slip, slip, moving), symmetry, far-field, with the correct OpenFOAM BC per variable and flavour.
- Acceptance: BC table (GUI choice → OpenFOAM BC for U, p, T, k, omega, epsilon, nut, nuTilda) covered by unit tests. `[NUMERICS-REVIEW]`

### 4.3 Turbulence module (STAR-like model selection) — *done for kOmegaSST*
- Goal: model + wall-treatment selector with sane defaults, plus automatic estimate of freestream k/omega/epsilon/nuTilda from turbulence intensity and length scale or viscosity ratio.
- Includes a y+ estimator that proposes first-cell height and layer settings for a target y+.
- Model coverage to map (verify availability in the chosen OpenFOAM version): k-epsilon variants, k-omega SST, Spalart-Allmaras, transition (SST-based), LES/DES options.
- Deliverable: `docs/reference/turbulence_mapping.md` stating, per STAR model/wall treatment, the closest OpenFOAM equivalent and where behaviour differs (e.g., STAR "All y+" vs OpenFOAM wall-function combinations).
- Acceptance: flat-plate case with the generated setup gives Cf and y+ in the expected range. `[NUMERICS-REVIEW]`

### 4.4 Numerics presets — *partly done (preset robust)*
- Schemes/relaxation/linear-solver presets (robust / accurate / fast) per physics type.
- Acceptance: presets converge on the reference cases; any preset change recorded in `DECISIONS.md`. `[NUMERICS-REVIEW]`

---

## Phase 5 — Meshing (staged track; the hardest part)

Reality check: "as powerful as a commercial mesher" is not a deliverable that can be verified. It is replaced here by measurable levels (below). Each level must beat the previous one on the benchmark suite, or it is not adopted.

### 5.0 Benchmark suite and quality metrics (do first) — *done (D-081, D-082: sphere, NACA 0012 wing, Ahmed-type body; baseline in benchmarks/BASELINE.md; the dirty-STL set and solver convergence are not in it)*
- Geometries: simple (sphere, cylinder), aerodynamic (NACA 0012 wing, wing-fuselage with thin trailing edge), complex (VTOL UAV with props/booms), dirty (broken STLs from 3.1).
- Metrics: success/failure, wall time, cell count, `checkMesh` (non-orthogonality, skewness, aspect ratio, negative volumes), prism-layer coverage %, first-cell y+ distribution, solver convergence on the resulting mesh.
- Acceptance: one command runs the suite and outputs a comparison table.

### 5.1 Level M1 — GUI over snappyHexMesh — *done; sizing defaults revised after the 5.0 baseline (task 5.1-sizing: D-084 seed lines out of snapping, D-085 surface size from l_ref and curvature refinement, D-086 absolute y+ 50 layers; benchmarks/RESULT_5.1.md)*
- Mesh controls: base size, surface target/min size relative to base, per-surface and per-volume refinement (user refinement volumes: box, rotated box, cylinder, sphere, cone; done in task 5.x-refinement-volumes, D-103), feature-edge refinement, wake refinement (the Add Wake Volume box aligned with the free stream, D-103), prism-layer parameters (number, growth, total thickness or first-cell height), automatic `snappyHexMeshDict` + `blockMeshDict` generation, `checkMesh` report in GUI.
- Acceptance: wing and VTOL meshed from the GUI without editing text files; benchmark results recorded as baseline.

### 5.2 Level M2 — Surface preparation ("wrapper-like") pipeline — *first step done (task 5.2-surface-prep): the Surface Preparation operation with diagnostics, intersection features and CAD union (D-093), local benchmark cases with fidelity against a reference surface (D-094); benchmarks/RESULT_5.2_before.md, RESULT_5.2.md. No shell wrapper built (not needed for the owner's aircraft); the dirty-STL set is not in the benchmark yet*
- Goal: robust watertight, quality surface from dirty/CAD tessellation before volume meshing (leak closing, remeshing, feature preservation).
- Acceptance: improves benchmark success rate on the dirty set vs M1 baseline.

### 5.3 Level M3 — Alternative volume mesher evaluation — *cfMesh evaluated (task 5.3-cfmesh, D-102, benchmarks/RESULT_5.3.md): full layer coverage at sharp edges but a one-cell-thick stack, hard checkMesh failures on 4 of 5 layered meshes and worse fidelity on thin geometry; recommendation: keep snappyHexMesh (owner decision pending, QUESTIONS 130); `--mesher cfmesh` stays as a benchmark-only switch. Gmsh and others not evaluated*
- Evaluate and, if better on the benchmarks, wrap: cfMesh (Cartesian/polyhedral/tetra), Gmsh, others from 0.2. Mesher selectable per project.
- Acceptance: written comparison on the benchmark suite; adopt only on measurable improvement.

### 5.4 Level M4 — Prism layer robustness — *closed (owner review of 5.4b): the public cases meet D1; the aircraft is valid with partial layers and the y+ drift warning in place; its zones (QUESTIONS 147) are the next aircraft task. Task 5.4-layers, D-105, D-106, benchmarks/RESULT_5.4.md): diagnosis of the collapse mechanisms, a one-factor study and new defaults for y+ layers (layer cap 12 with the expansion ratio up to 1.3, layer featureAngle 130): strict coverage half wing 77 -> 96 %, Ahmed body 31 -> 97 %, the aircraft valid but far from its target; task 5.4b (D-106 update, D-107 to D-109, benchmarks/RESULT_5.4b.md): y+ target at the first cell centre (public y+ means at the target), nOuterIter 2 with the tet check on, the achieved first cell reported with a y+ drift warning; the aircraft at 0.05 l_ref reaches full stacks on 20 % of its wall, none in its zones; no independent layer module (snappyHexMesh controls only)*
- Goal: better layer generation in concave corners, thin trailing edges and wing-body junctions (layer collapse handling, quality-driven retraction, local layer controls, y+ driven sizing).
- Treat as research: start with the failure-case catalogue from M1/M3, then prototype improvements as an independent module operating on an existing mesh.
- Validation: flat plate (y+, Cf) and NACA 0012; layer coverage % on benchmark. `[NUMERICS-REVIEW]`

### 5.5 Level M5 — Own trimmer/cut-cell mesher (go/no-go gate)
- Only starts if benchmarks after M1–M4 show a gap that justifies it and Vic approves the decision.
- If go: C++ core (octree + cut cells + quality repair), Python bindings, OpenFOAM polyMesh writer.
- Validation: mesh independence on sphere/cylinder/NACA 0012, quality metrics ≥ M3 baseline.

---

## Phase 6 — Post-processing (in-GUI)

### 6.1 Monitors and reports — *done (Task 6.1: stopping criteria (runTimeControl for residuals, app-side range-based asymptotic criterion), convergence banner, force breakdown, mass balance, probes, y+ histogram)*
- Residuals, force/moment coefficients (CL, CD, CM with reference area/length/axes defined in GUI), probes, surface integrals, mass flow; convergence criteria and auto-stop.
- Acceptance: coefficients match OpenFOAM `forceCoeffs` output on reference cases.
- Monitor report slots: the residuals panel shows N report slots; the user assigns any defined report (forces, coefficients, probes, y+) to a slot; convergence banner shown only when stopping criteria exist.

### 6.2 Scenes and derived parts — *partly done (scalar scenes, section; no scene saving or image export)*
- Slices, clips, iso-surfaces, streamlines, scalar/vector fields on surfaces, Cp plots along sections, y+ on walls, mesh quality displays.
- Acceptance: scene definitions saved in the project and reproducible; image export.
- Scalar scenes: field selector (p, |U|, Mach, k, omega, nut, y+, any written field), colormap selector with several perceptual maps (e.g. viridis, plasma, turbo, coolwarm, grayscale), range auto/fixed/symmetric, legend bar with field name and units.

### 6.3 Data export and reports
- CSV, VTK/EnSight, image sets, simple HTML/PDF run report (setup summary + results).
- Acceptance: report generated automatically at end of run.

### 6.4 Mesh independence study — *done (Task 6.4: Mesh Study node, three levels with the same absolute layer stack, Celik GCI with oscillatory / divergent cases, results window and CSV, D-066; flat plate Case B not reproduced through the workflow, docs/QUESTIONS.md item 72; the levels keep the refinement volumes since D-117; first force validation through the study: Ahmed body 25 degrees, workstream W1 closed: FAIL (round 2), a documented known limitation accepted for v1; round 4 inconclusive, docs/validation/ahmed/RESULT.md "Conclusion")*
- Goal: a workflow that runs the same physics on a family of systematically refined meshes (at least three, constant refinement ratio, e.g. r = sqrt(2) in cell size) and judges grid convergence of chosen reports (Cd, Cl, Cm, a probe).
- Deliverables: a "Mesh study" node defining the family from the current mesh settings; one case directory per grid; a table of each report per grid with the observed order p, the Richardson-extrapolated value and the Grid Convergence Index (Celik et al. 2008, as in the flat plate validation, D-036); warnings for oscillatory or divergent convergence (non-monotone ratios).
- Acceptance: on the coarse sphere family the GCI table is reproduced by hand from the per-grid values; the flat plate Case B study (docs/validation/flat_plate) is reproduced through the workflow.

### 6.5 Angle-of-attack sweep (polars) — *done (Task 6.5: Polar Sweep node, points on the current mesh initialised from the previous converged point, CL-alpha / drag polar / CM-alpha with flagged points, CSV, D-067; NACA 0012 check waits for the wing case)*
- Goal: run the same mesh and physics for a list of angles of attack and collect Cl, Cd, Cm and L/D per angle (polars), each run judged by its stopping criteria and convergence banner (6.1).
- Deliverables: a sweep definition (start, end, step or explicit list), one run per angle (sequential, then parallel with 6.6), Cl-alpha, Cd-Cl and Cm-alpha charts and a CSV export; runs that end at the iteration limit or oscillate are flagged in the polar.
- Acceptance: the reference values and force directions follow alpha in every run (D-050 check per angle); a NACA 0012 polar against reference data once Phase 1.2's wing case exists.

### 6.6 Parallel runs — *done (Task 6.6: decomposePar / mpirun / reconstructPar, clean stop through mpirun; serial and parallel compared on the converged low-Re sphere, D-063; speedup study and recommended cores, D-064; parallel snappyHexMesh with reconstruction to a serial mesh, Mesh cores in the Mesh properties, task 5.x-parallel-mesh, D-111, benchmarks/RESULT_parallel_mesh.md)*
- Goal: decomposePar / mpirun / reconstructPar from the runner with a clean stop for parallel solvers (today only single-process runs, D-010, D-046).
- Acceptance: the same results (to solver tolerance) and the same stopping criteria behaviour in serial and in parallel on the coarse sphere.

---

## Phase 7 — Coupled solver: analysis only (no implementation yet)

### 7.1 Inventory
- Document what the chosen OpenFOAM version offers for pressure-velocity coupling (SIMPLE/SIMPLEC/PIMPLE consistent options, density-based compressible solvers, block/coupled options in OpenFOAM variants or extensions).
### 7.2 Comparison
- Run the benchmark cases with available options; record iterations/time to convergence and robustness.
### 7.3 Decision memo
- `docs/decisions/coupled_solver.md`: what is feasible, what it costs, recommendation (adopt / wrap external / defer).
- Acceptance: memo reviewed; no code merged for this phase.

---

## Phase 8 — Moving meshes (lower priority)

Order by relevance to VTOL/UAV work: rotating zones first, 6DOF last.
### 8.1 Survey and capability matrix (dynamicMesh, MRF, AMI/sliding interfaces, overset, sixDoF) in the chosen OpenFOAM version.
### 8.2 MRF / rotating zones in GUI (propellers, rotors). Validation: simple rotating case. 
### 8.3 AMI / sliding mesh in GUI. Validation: prescribed-rotation case.
### 8.4 Overset (only if robust in the chosen version).
### 8.5 6DOF / rigid-body motion (only after 8.2–8.3 are stable).
- Acceptance per subphase: GUI generates a runnable case; one simple validation case documented.

---

## Phase 9 — Packaging and automation

### 9.1 Project management: save/load, templates library, recent projects, case cloning/parametric variants.
### 9.2 Python scripting API over the data model (equivalent to STAR macros) and batch execution.
### 9.3 Installer/docs: reproducible install (WSL + OpenFOAM + app), user guide, tutorials with the benchmark cases.

---

## Dependency overview

`0 → 1 → 2 → 3 → 4 → 5.0/5.1 → 6`. Phases 5.2–5.5 run in parallel to 6 and later. Phases 7 and 8 start after a working end-to-end MVP (external flow on wing/VTOL: STL → mesh → solve → results).

## Definition of MVP

STL/STEP import → domain → snappyHexMesh with layers (M1) → k-omega SST → steady RANS → live residuals/CL/CD → pressure slice, all from the GUI, with no manual dictionary editing.

## v1

Definition (owner, 2026-10-22):

- External and internal steady incompressible flow, stopped on a mean-based criterion (the mean-stable
  criterion, D-118).
- Validations recorded for the flat plate, the Ahmed body (a documented result; PASS not required) and a
  wing at several angles of attack.
- A validated angle-of-attack method.
- Post-processing for a report.
- Installable on another PC, with a short manual.

Workstreams:

| Workstream | Content | State |
|---|---|---|
| W1 | Ahmed body, 25 degrees | **closed** (2026-10-22): FAIL, recorded as a documented known limitation of steady SST with wall functions (+13.9 % against the experiment, +5.6 % against Guilmineau 2008; docs/validation/ahmed/RESULT.md, "Conclusion") |
| W2 | Angle of attack (the validated method, QUESTIONS 71), a 2D mode, a wall-resolved layer mode (QUESTIONS 180, needed before the NACA 0012 runs), NACA 0012 at several angles | open |
| W3 | Internal flow | open |
| W4 | Post-processing for a report | open |
| W5 | Installation and the manual | open |

Post-v1 backlog:

- Per-part (per-wall) prism layer settings (QUESTIONS 179): today one layer specification serves every wall.
