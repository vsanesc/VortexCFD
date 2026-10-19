# Benchmark metric fixtures (D-082)

- `checkMesh_failed.log`: checkMesh (v2606) of a 6 x 3 x 6 blockMesh block sheared by 78 degrees in x
  along z, with three interior points then moved by (+0.9, +0.55, -0.12) m: five failed checks (aspect
  ratio, negative volumes, non-orthogonality above 90 degrees, face pyramids, skewness). Read by
  tests/test_bench_metrics.py.
