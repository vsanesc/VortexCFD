# Turbulent smooth pipe: result

Task w3-internal, Part B (2026-10-22). Set-up in SETUP.md; the numbers in result.json (means over the last 200
iterations); `scripts/validation/pipe_study.py`. Machine time: meshing 18 s (8 ranks), the mass-flow run 60 s (502
iterations, 10 ranks), the total-pressure run 181 s (1,858 iterations); with the runs that found D-130 and D-131 and
the by-hand check of D-131, about 10 min in all.

## Mesh

168,166 cells, checkMesh OK (max non-orthogonality 44.3), 2 layers on 100 % of the wall (snappyHexMesh's table and
the first-cell walk: 1.983 mm against 1.993 mm planned, none above twice the plan), so no layer collapse (I5). y+ on
the wall: mean 47.0, 44.4 to 64.2, every face in the 30-300 band.

## Friction factor (single level)

f = (dp / L) D_h / (0.5 rho U_b^2) from the area-averaged static pressure drop between the planes (D_h = 0.09988 m and
U_b = 1.0016 m/s of the 64-gon; with the nominal D and 1.0 m/s every f is 0.44 % higher).

| Segment | dp (Pa) | f | f / f(Prandtl-Karman) - 1 |
|---|---|---|---|
| 40-50 D | 91.00 | 0.018120 | +0.71 % |
| 50-60 D | 91.59 | 0.018237 | +1.36 % |
| 60-70 D | 91.60 | 0.018239 | +1.37 % |
| **50-70 D** | **183.19** | **0.018238** | **+1.36 %** |

The flow is developed from 50 D: the segments 50-60 D and 60-70 D agree within 0.012 % (40-50 D is 0.6 % lower,
still developing). The pressure drop over 50-70 D changed by 0.044 Pa (0.024 %) over the last 200 iterations.

| Reference at Re = 1.0e5 | f | Simulation (0.018238) against it |
|---|---|---|
| Prandtl-Karman (verdict) | 0.017993 | +1.36 % |
| Colebrook-White, smooth | 0.017990 | +1.38 % |
| McKeon et al. 2004, Princeton, Re = 9.846e4 (measured) | 0.01815 | +0.48 % (at a 1.6 % lower Re: f there is 0.4 % higher) |
| McKeon et al. 2004, Oregon, Re = 8.476e4 (measured) | 0.01805 | +1.04 % (at a 15 % lower Re) |

Mass balance: inlet -7.85398 kg/s, outlet 7.85398 kg/s, imbalance 0.0 % (the written digits; under 0.1 %); the planes
carry 7.85384 to 7.85400 kg/s (within 0.002 %).

## Total-pressure inlet (Part B5)

The same mesh, a total-pressure inlet at the mass-flow run's mass-averaged inlet total pressure, 1257.773 Pa gauge
(D-131: SIMPLE with a relaxed pressure; the default SIMPLEC diverged from rest, see below).

| Inlet | Mass flow (kg/s) | U_b (m/s) | dp 50-70 D (Pa) | f (50-70 D) | inlet p0, mass-averaged (Pa) |
|---|---|---|---|---|---|
| mass flow 7.853982 kg/s | 7.853980 | 1.001608 | 183.185 | 0.018238 | 1257.773 |
| total pressure 1257.773 Pa | 7.852995 | 1.001482 | 183.198 | 0.018244 | 1257.771 |
| difference | -0.0126 % | | +0.007 % | **+0.033 %** (within 1 %) | |

The two inlets give the same friction factor (0.03 %) and a consistent flow: the total-pressure inlet delivers the
mass flow that its total pressure sustained in the mass-flow run within 0.013 % (its last 200 iterations still crept
up by 1e-5 relative; the outlet-flow criterion stopped it at 1,858 iterations).

Findings on the way (both fixed in the app before these runs, commit "Physics: cutting planes off mesh faces;
parallel meshing decomposes the mesh only"; D-131 in the commit of this record):

- a plane at x = 40 D lay on a layer of mesh faces and was sampled twice (368 faces, 105 % of the area, 8.20 kg/s);
  the planes are now written 1e-6 of the parts' extent along their normal (D-129);
- meshing the solved case again in parallel failed in decomposePar on the old 0/ fields (D-130);
- the total-pressure inlet with the app's SIMPLEC diverged from rest (mass flow past 7.85 kg/s at iteration 28, the
  solver crashed at 727); SIMPLE with p 0.3 and U, k, omega 0.7 converged (D-131, QUESTIONS 208).

## Verdict

**PASS**: f = 0.018238 is 1.36 % above the Prandtl-Karman smooth-pipe law (PASS within 5 %), the mass balance is 0.0 %
(within 0.1 %), the layers are complete, and the total-pressure inlet reproduces the friction factor within 0.03 %.
Single level only: no mesh study (QUESTIONS 204), so no GCI; the discretisation error of this level is not
estimated.
