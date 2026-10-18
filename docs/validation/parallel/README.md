# Parallel speedup study (D-064)

Run with nothing else on the machine (marker `long`, about 31 min):

    .venv/bin/pytest -m long -s tests/test_parallel_speedup.py

Machine: AMD Ryzen 9 5900X (12 cores / 24 threads, one socket, two CCDs, two DDR4 memory channels),
WSL2 Ubuntu 24.04, Open MPI 4.1.6, OpenFOAM ESI v2606.

Case: the sphere of the shared test mesh (radius 0.5 m) with the default domain and sizing and a
background cell budget of 900,000 (989,835 cells after snappyHexMesh), the app's simpleFoam set-up at
20 m/s and alpha 4 deg, no stopping criteria, 100 iterations, decomposition scotch. Wall time is the
solver's (mpirun or simpleFoam) only, without decomposePar and reconstructPar. Each configuration
ran once. Binding "default" is Open MPI 4.1's own policy (bind to core for up to 2 ranks, to the
package above); "core" is `--bind-to core --map-by core`. Raw numbers: `speedup.json`.

| Binding | Cores | Wall time [s] | Speedup | Efficiency | Cells per core |
|---|---|---|---|---|---|
| default | 1 | 443.9 | 1.0 | 1.0 | 989,835 |
| default | 2 | 270.6 | 1.64 | 0.82 | 494,917 |
| default | 4 | 175.3 | 2.53 | 0.63 | 247,458 |
| default | 8 | 148.2 | 3.0 | 0.37 | 123,729 |
| core | 2 | 230.0 | 1.93 | 0.96 | 494,917 |
| core | 4 | 164.2 | 2.7 | 0.68 | 247,458 |
| core | 8 | 153.8 | 2.89 | 0.36 | 123,729 |

A first run of the same study with a 500,000 background budget (564,679 cells; 220.1 s serial)
gave default 1.81 / 2.09 / 2.27 and core 1.61 / 2.06 / 2.24 at 2 / 4 / 8 cores. Task 6.6 measured
2.00 on 4 cores for the 192,220-cell sphere (300 iterations, Re 200).

Findings:

- The speedup saturates: 8 ranks give only 3.0 (990k cells) and 2.3 (565k), and the efficiency is at
  least 0.5 up to 4 ranks only, for all three meshes. The efficiency depends on the number of ranks
  more than on the cells per rank (565k cells on 4 ranks, 141k per rank: 0.52; 990k on 8 ranks, 124k
  per rank: 0.37), which points at memory bandwidth (two channels shared by all cores) rather than
  communication.
- The binding is not clearly better either way: `--bind-to core` was faster at 2 and 4 ranks on the
  990k mesh (by 15 % and 6 %) and slower at 8 (4 %), while on the 565k mesh it was slower at 2 ranks
  (11 %). Single runs on a desktop under Windows differ by about that much, so the default is kept.

Decision (D-064): Open MPI's default binding stays; the Solvers node recommends
min(physical cores, cells / 50,000 rounded down, 4), at least 1.
