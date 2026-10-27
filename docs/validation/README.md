# Validation and verification cases

Each case has its own folder with the set-up, the result and the recorded numbers. Validation tests carry
the marker `validation` (or `long`) and are not part of the default test run.

| Case | What it checks | Verdict | Where |
|---|---|---|---|
| Flat plate (TMR), zero pressure gradient | k-omega SST with wall functions: skin friction | Case B: **PASS WITH NOTE** (Cf(0.97) 3.3 % below the TMR reference) | [flat_plate/README.md](flat_plate/README.md) |
| Ahmed body, 25 degree slant, in ground proximity | external aerodynamics with a ground plane: body drag against Ahmed et al. (1984) | Closed (W1). **FAIL** (V6, round 2), a documented known limitation of steady SST with wall functions at 25 degrees: fine body Cd 0.3246, +13.9 % against the experiment, +5.6 % against Guilmineau 2008; accepted for v1. Round 4 (wall-resolved attempt) inconclusive: its layers collapsed ([Conclusion](ahmed/RESULT.md#conclusion)) | [ahmed/RESULT.md](ahmed/RESULT.md), [ahmed/SETUP.md](ahmed/SETUP.md) |
| Parallel speedup (D-064) | solver speed-up with the number of MPI ranks | measurement, no verdict | [parallel/README.md](parallel/README.md) |
| NACA 0012 (NASA TMR), 2D, Re 6e6, 0 / 10 / 15 degrees | k-omega SST wall-resolved (y+ 1), the angle of attack by rotation, the 2D mode: CL and CD against the TMR SST codes and Ladson | Round 3 (the app's "2D airfoil" preset, W2 closed): **PASS** at 0, 10 and 15 deg (CL -0.0 / -1.8 / -2.3 %, CD -6.9 / -2.5 / +3.9 % against the TMR SST codes; the 10 deg study converges, CL GCI 1.9 %). Round 1: 0 deg PASS, 10 and 15 deg FAIL | [naca0012/RESULT.md](naca0012/RESULT.md), [naca0012/SETUP.md](naca0012/SETUP.md) |
| Turbulent smooth pipe, Re 1e5, 80 D (W3) | internal flow (D-129): mass-flow and total-pressure inlets, static outlet, wall functions; Darcy friction factor over 50-70 D against Prandtl-Karman, mass balance | **PASS**: f = 0.018238, +1.36 % (mass balance 0.0 %); the total-pressure inlet within 0.03 %; single level (no study, QUESTIONS 204) | [pipe/RESULT.md](pipe/RESULT.md), [pipe/SETUP.md](pipe/SETUP.md) |
| Backward-facing step (NASA TMR), 2D, Re_H 36,000 (W3) | internal flow in 2D, wall-resolved y+ 1, two turbulence stages: reattachment length, bottom-wall Cf and Cp against Driver & Seegmiller and the TMR SST codes | **PASS WITH NOTE** (round 3, W3 closed: the step face's layers fixed by D-135; three valid levels 6.468 / 6.227 / 6.434 H, oscillatory, no GCI; the finest +2.8 % against the experiment, SST -1.0 %) | [bfs/RESULT.md](bfs/RESULT.md), [bfs/SETUP.md](bfs/SETUP.md) |
| Circular cylinder, 2D, laminar, Re 100 (1.1) | transient flow (D-181: pimpleFoam, adaptive step, the detected sampling window, time-weighted statistics, the Strouhal number) and the laminar option (D-182) | **PASS** on all three levels: fine St 0.1649 (in the sourced band 0.164-0.165), mean Cd 1.3391 (-0.8 % of 1.35), RMS Cl 0.2309 (-8.7 % of 0.253); St GCI 0.09 %, Cd oscillatory within 0.1 % | [cylinder_re100/RESULT.md](cylinder_re100/RESULT.md), [cylinder_re100/SETUP.md](cylinder_re100/SETUP.md) |
| 3D mesh study family (D-127), sphere and half wing, mesh only | the study levels' cell size at fixed points shrinks with the level ratio | Rounds 2 to 4 **not passed** (round 4, level-scaled buffers: size ratios 1.00 / 1.25 sphere and 0.94 / 1.24 wing against 1.414); closed by the owner's closure rule as a known v1 limitation: a 3D study's GCI is indicative (D-127 Proposed) | [study3d/RESULT.md](study3d/RESULT.md) |

## Ahmed body: reading of round 2 (owner review and the references read after it, 2026-10-21)

Recorded as FAIL under V6. The medium and fine levels agree within 0.8 %, so the grid uncertainty is small
even though no GCI can be computed (oscillatory). Steady k-omega SST with wall functions gives a body Cd of
0.325 (+14 %) on this case; the round 2 set-up fixes moved the fine level by -0.1 %. The one peer-reviewed
SST result read (Guilmineau 2008, steady, wall-resolved) also over-predicts: 0.3074 (+7.9 %), with no
slant reattachment; this study is 5.6 % above it and 3.7 % above the highest vendor result. The fine
level's slant bubble reattaches later on the centre line (0.6-0.7 of the slant) than the experiment as
Guilmineau describes it (about half-way); the bubble's size does not track the drag in the results
compared, and the cause of the gap is not established. Still missing: the real Ahmed et al. (1984) and
Lienhart & Becker (2003) papers (the files supplied under their names are other papers; QUESTIONS 171). After round 4 (owner review, 2026-10-22): this FAIL is the final verdict, a documented known limitation
accepted for v1; the experimental 0.285 is confirmed by Guilmineau 2008 Table 1 (QUESTIONS 171 closed).
