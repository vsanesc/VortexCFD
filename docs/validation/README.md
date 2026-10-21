# Validation and verification cases

Each case has its own folder with the set-up, the result and the recorded numbers. Validation tests carry
the marker `validation` (or `long`) and are not part of the default test run.

| Case | What it checks | Verdict | Where |
|---|---|---|---|
| Flat plate (TMR), zero pressure gradient | k-omega SST with wall functions: skin friction | Case B: **PASS WITH NOTE** (Cf(0.97) 3.3 % below the TMR reference) | [flat_plate/README.md](flat_plate/README.md) |
| Ahmed body, 25 degree slant, in ground proximity | external aerodynamics with a ground plane: body drag against Ahmed et al. (1984) | **FAIL** (V6) in rounds 1 and 2: fine-grid body Cd 0.325, +14 % | [ahmed/RESULT.md](ahmed/RESULT.md), [ahmed/SETUP.md](ahmed/SETUP.md) |
| Parallel speedup (D-064) | solver speed-up with the number of MPI ranks | measurement, no verdict | [parallel/README.md](parallel/README.md) |

## Ahmed body: reading of round 2 (owner review, 2026-10-21)

Recorded as FAIL under V6. The medium and fine levels agree within 0.8 %, so the grid uncertainty is small
even though no GCI can be computed (oscillatory). Steady k-omega SST with wall functions gives a body Cd of
0.325 (+14 %) on this case. The remaining error is not the set-up (the round 2 fixes moved the fine level by
-0.1 %); the fine level reproduces a reattaching slant bubble, as in the experiment, and why steady SST still
over-predicts the drag is not established (to be checked against Lienhart & Becker's data, QUESTIONS 171).
The verdict depends on unverified SST literature values, which probably used wall-resolved meshes, unlike
this study (V3); it stays FAIL until verified references are read (QUESTIONS 171 and 172).
