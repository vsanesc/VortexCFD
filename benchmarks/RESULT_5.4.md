# 5.4 prism-layer robustness

Task 5.4: make the prism layers robust (owner decisions D1 to D5 of the task). The headline layer metric
is the strict coverage counted from the mesh (bench/layer_walk, D-105): the wall area whose column of
thin prism cells has the full target count. Local aircraft results: numbers only (D-094).

## Starting point (Part A)

Current defaults (as baseline.json: y+ 50 absolute layers, expansion 1.2, surface size from l_ref,
curvature levels 2; the aircraft with the D-094 settings: 30 m/s, surface size 0.1 l_ref, CAD union),
mesh only, at git `d52b99e` plus the D-105 report change (tagged "-dirty"). The four cases ran
concurrently, each on one core under `nice -n 15`; wall-clock 262 s. Public cases:
benchmarks/baseline_5.4_start.json; aircraft: benchmarks/results/5.4/baseline_5.4_start_local.json
(git-ignored).

Columns: hard / soft = checkMesh failures by the D-100 classes; strict coverage, mean layers / target,
zero-layer area and thickness are counted from the mesh; thickness is the stack against the planned y+
stack (first layer x (r^n - 1) / (r - 1)); zones as strict % / mean-over-target %; fidelity RMS in mm
(aircraft: mesh -> reference / reference -> mesh).

| Case | Hard / soft | Cells | Strict cov. % | Mean / target % | Zero-layer % | Thickness % of plan | Zones (strict % / mean %) | Max non-ortho | Fidelity RMS mm | Mesh s | Target layers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sphere | 0 / 0 | 276,078 | 99.5 | 100.2 | 0.0 | 101.1 | - | 46.6 | 0.089 | 59 | 10 |
| wing | 0 / 0 | 337,824 | 76.8 | 87.0 | 3.3 | 90.3 | root 87.4 / 95, tips 0.0 / 11, trailing edge 0.0 / 17 | 64.8 | 0.107 | 62 | 11 |
| ahmed | 0 / 0 | 225,842 | 31.1 | 64.0 | 9.3 | 77.4 | rear edges 0.0 / 4, slant edges 14.5 / 25 | 64.9 | 0.063 | 44 | 10 |
| aircraft (CAD union) | 3 / 2 | 281,113 | 0.0 | 2.2 | 74.8 | 8.4 | wing junction 0.0 / 0, htail junction 0.0 / 1, vtail junction 0.0 / 1, trailing edge 0.0 / 0, tips 0.0 / 0 | 174.4 | 3.54 / 4.43 | 168 | 24 |

The public cases repeat RESULT_5.3 exactly (cells, quality, both layer measures); snappyHexMesh's own
fields give 100.0 / 78.4 / 31.0 / 0.0 % strict coverage. The aircraft's hard failures are the same three
as in 5.2: 4 negative-volume cells, 15 faces above 90 degrees, 40 incorrectly oriented face pyramids; soft: aspect ratio (4 cells) and skewness 25.6 (2 faces).
