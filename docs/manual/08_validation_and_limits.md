# 8. Validation and known limitations

## 8.1 The validated cases

Each case was run through the app's own pipeline and is recorded in docs/validation/ (set-up, numbers, verdict).

| Case | What it checks | Verdict | Record |
|---|---|---|---|
| Flat plate, zero pressure gradient (NASA TMR) | k-omega SST with wall functions: skin friction | **PASS WITH NOTE**: Cf(0.97) 3.3 % below the TMR reference, the gap not explained | docs/validation/flat_plate/README.md |
| Ahmed body, 25 degree slant, in ground proximity | external aerodynamics with a ground plane: body drag against Ahmed et al. (1984) | **FAIL**, a documented known limitation accepted for v1: body Cd 0.3246, +13.9 % against the experiment (+5.6 % against Guilmineau 2008's steady SST) | docs/validation/ahmed/RESULT.md |
| NACA 0012, 2D, Re 6e6, 0 / 10 / 15 degrees (NASA TMR) | wall-resolved SST, the angle of attack by rotation, the 2D mode | **PASS** at every angle: CL -0.0 / -1.8 / -2.3 %, CD -6.9 / -2.5 / +3.9 % against the TMR SST codes; the 10 degree study converges (CL GCI 1.9 %, CD 0.86 %) | docs/validation/naca0012/RESULT.md |
| Turbulent smooth pipe, Re 1e5 | internal flow: mass-flow and total-pressure inlets, static outlet | **PASS**: Darcy f +1.36 % against Prandtl-Karman, mass balance 0.0 %, the total-pressure inlet within 0.03 %; one mesh level (no GCI) | docs/validation/pipe/RESULT.md |
| Backward-facing step, 2D, Re_H 36,000 (NASA TMR) | internal 2D wall-resolved flow: reattachment length | **PASS WITH NOTE**: x_r 6.434 H on the finest level, +2.8 % against the experiment (-1.0 % against TMR SST); three valid levels, oscillatory, no GCI | docs/validation/bfs/RESULT.md |
| Parallel speed-up | the solver's speed-up with the MPI ranks | a measurement: about 3 on 8 cores (memory bound) | docs/validation/parallel/README.md |

## 8.2 Known limitations of v1

- **Steady incompressible RANS only.** One solver (simpleFoam), one turbulence model (k-omega SST). No transient
  runs, no compressible flow, no heat transfer, no moving meshes or rotating zones.
- **Bluff bodies with strong separation.** Steady SST with wall functions over-predicts the drag of the Ahmed body
  at 25 degrees by about 14 % (body Cd 0.325 against the experimental 0.285); no set-up tried reproduced the slant's
  reattachment, and steady SST oscillates there. Use the mean-stable criterion (chapter 7) and treat drag of such
  bodies as indicative.
- **The 3D mesh independence study's GCI is indicative.** A 3D study's levels refine the walls and the background by the level
  ratio but not the transition zones around the parts (D-127, Proposed): its GCI covers the wall cells and the
  background, not the near field. The 2D study refines everywhere and its GCI stands.
- **Flat plate skin friction** is 3.3 % below the TMR reference, unexplained (the wall-function blending or
  OpenFOAM's SST implementation are candidates).
- **NACA 0012 at 0 degrees** gives CD 6.9 % below TMR SST (inside PASS; likely SST-2003 against TMR's SSTm, not
  established).
- **One layer specification for all walls** (per-part layers are a post-v1 item); one boundary type per domain
  role in external flow.
- **Every run starts from the initial fields**: there is no restart from the latest time.
- **One platform**: WSL2 Ubuntu 24.04 with Python 3.12 (the install script refuses others unless `--ignore-os`).
  The installation was tested in isolation and by the owner in a clean WSL2 Ubuntu 24.04; that WSLg lists the
  desktop entry in the Windows Start menu has not been seen yet.
