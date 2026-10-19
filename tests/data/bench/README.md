# Benchmark metric fixtures (D-082)

- `checkMesh_failed.log`: checkMesh (v2606) of a 6 x 3 x 6 blockMesh block sheared by 78 degrees in x
  along z, with three interior points then moved by (+0.9, +0.55, -0.12) m: five failed checks (aspect
  ratio, negative volumes, non-orthogonality above 90 degrees, face pyramids, skewness). Read by
  tests/test_bench_metrics.py.
- `checkMesh_soft.log`: checkMesh (v2606) of a 2 x 2 x 1 blockMesh block of 1 x 1 x 0.00001 m (cells
  0.5 x 0.5 x 0.00001 m): one failed check, high aspect ratio (50000), a SOFT failure of D-100 that
  does not block the solver. Read by tests/test_solver_gui.py. `checkMesh_failed.log` holds both
  classes (negative volumes, non-orthogonality errors and face pyramids are HARD).
