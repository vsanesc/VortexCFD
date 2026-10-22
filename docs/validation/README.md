# Validation and verification cases

Each case has its own folder with the set-up, the result and the recorded numbers. Validation tests carry
the marker `validation` (or `long`) and are not part of the default test run.

| Case | What it checks | Verdict | Where |
|---|---|---|---|
| Flat plate (TMR), zero pressure gradient | k-omega SST with wall functions: skin friction | Case B: **PASS WITH NOTE** (Cf(0.97) 3.3 % below the TMR reference) | [flat_plate/README.md](flat_plate/README.md) |
| Ahmed body, 25 degree slant, in ground proximity | external aerodynamics with a ground plane: body drag against Ahmed et al. (1984) | Closed (W1). **FAIL** (V6, round 2), a documented known limitation of steady SST with wall functions at 25 degrees: fine body Cd 0.3246, +13.9 % against the experiment, +5.6 % against Guilmineau 2008; accepted for v1. Round 4 (wall-resolved attempt) inconclusive: its layers collapsed ([Conclusion](ahmed/RESULT.md#conclusion)) | [ahmed/RESULT.md](ahmed/RESULT.md), [ahmed/SETUP.md](ahmed/SETUP.md) |
| Parallel speedup (D-064) | solver speed-up with the number of MPI ranks | measurement, no verdict | [parallel/README.md](parallel/README.md) |
| NACA 0012 (NASA TMR), 2D, Re 6e6, 0 / 10 / 15 degrees | k-omega SST wall-resolved (y+ 1), the angle of attack by rotation, the 2D mode: CL and CD against the TMR SST codes and Ladson | 0 deg **PASS** (CD -0.1 %); 10 deg **FAIL** (CL -3.0 %, CD +24 %); 15 deg **FAIL** (separated, CD x4) | [naca0012/RESULT.md](naca0012/RESULT.md), [naca0012/SETUP.md](naca0012/SETUP.md) |

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
