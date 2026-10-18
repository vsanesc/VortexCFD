# Freestream far field (Part B of the 6.4 / 6.5 task): stopped at the validation step

Status: NOT APPLIED. The app keeps the slip far field of D-022. The complete change is in
`freestream_far_field.patch` (next to this note; `git apply docs/notes/freestream_far_field.patch`
applies it to commit 23af2c5 and later commits that do not touch the same lines). Review question:
docs/QUESTIONS.md item 71. [NUMERICS-REVIEW]

## What the patch does

- `foam/physics_case.initial_fields`: sides, top and bottom get U `freestreamVelocity`
  (freestreamValue = inlet velocity), p `freestreamPressure` (freestreamValue 0), k and omega
  `inletOutlet` with the inlet values, nut `calculated` (as the ESI airFoil2D tutorial's 0.orig/U
  and p; keyword `freestreamValue` read in the v2606 sources
  src/finiteVolume/fields/fvPatchFields/derived/freestreamVelocity and freestreamPressure: mixed
  conditions, valueFraction 0.5 -/+ 0.5 (U . n) / |U|). Inlet, outlet, walls and symmetry
  unchanged.
- Mass balance: `massFlow_sides/top/bottom` function objects; imbalance = 100 (inlet + outlet +
  far field) / |inlet|; a "Far-field flux" row on the Reports & Monitors node.
- tests/test_far_field.py: the slip vs freestream comparison (marker `long`) and a mass-balance
  unit test on the real fixture tests/data/freestream_run/.
- tests/validation/flat_plate_case.py: drops `massFlow_sides` (the 2D plate's sides are empty).

## Results

Slip against freestream, flattened ellipsoid (semi-axes 0.5 x 0.5 x 0.15 m, default mesh,
192,458 cells), 20 m/s, alpha 10 deg, 4 cores, Cd and Cl asymptotic (window 50, tolerance 1 %),
limit 600 iterations (second of two runs; the first gave slip Cl 0.04143 / Cd 0.03576 at 134
iterations and freestream Cl 0.06904 / Cd 0.03180 at 600):

| Far field | Cl (last) | Cd (last) | Cl last 50: mean, range | Cd last 50: mean, range | Mass imbalance | Iterations | End |
|---|---|---|---|---|---|---|---|
| slip | 0.041082 | 0.035793 | 0.040872, 0.978 % | 0.035726, 0.431 % | 0 % | 132 | criteria met |
| freestream | 0.064967 | 0.034108 | 0.068179, 6.65 % | 0.032568, 7.75 % | -2.71e-05 % | 600 | iteration limit |

With freestream about 607 m3/s enters through the bottom and leaves through the top (27 % of the
inlet flux each); the net far-field flux is -0.07 m3/s.

Flat plate validation (`pytest -m validation`), last line: `5 errors in 1803.53s (0:30:03)`.
The medium Case B grid (first-cell y+ 0.47) did not meet its residual criteria (1e-5) within the
30 min budget: it was killed at iteration 8159 (the committed study stopped it at 3395) with the
Uz initial residual stalled at about 1.6e-5 (p 1.6e-5, Ux 1.5e-8, k and omega 1e-8). The coarse
grid converged at 949 iterations (881 before) with Cf(0.97) = 2.5408e-3 instead of the committed
2.5561e-3 (-0.60 %; error against TMR -6.63 % instead of -6.07 %), beyond the 0.1 % reproduction
check. Case A converged at 510 iterations (494 before). The verdict (PASS WITH NOTE, from the three-grid
extrapolation) could not be recomputed: the suite's shared fixture failed, so all five validation
tests errored.

## Observations for the review (not tested)

- In the validation case the app's `bottom` patch is the leading section ahead of the plate and
  `top` is the upper boundary. TMR's set-up has a symmetry plane ahead of the plate and a farfield
  top; with the patch, the leading section becomes freestream as well (flow tangential to it:
  valueFraction about 0.5).
- Where the flow is nearly tangential to a freestream patch (the leading section, the sides of the 3D
  domain, which are parallel to the free stream) the mixed condition sits at valueFraction near 0.5
  and switches with the sign of U . n; this may explain both the stalled Uz residual on the plate
  and the oscillating ellipsoid run, which settled within 132 iterations with slip.
