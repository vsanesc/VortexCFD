# 5.3 evaluation: cfMesh against snappyHexMesh

## Part A: availability

Checked by sourcing /usr/lib/openfoam/openfoam2606/etc/bashrc as the app does
(`foam/cfmesh_case.cfmesh_executables`, tests/test_cfmesh_case.py):

- Present in the v2606 platform bin/ (package openfoam2606 2606.0~rc2-1, build `_481094f-20260618`):
  cartesianMesh, tetMesh, pMesh, cartesian2DMesh, generateBoundaryLayers, improveMeshQuality,
  improveSymmetryPlanes, surfaceFeatureEdges, surfaceToFMS, FMSToSurface, checkSurfaceMesh,
  mergeSurfacePatches, preparePar and the other cfMesh utilities, with libmeshLibrary.so. Missing:
  extrudeEdgesInto2DMesh, subsetFMS (not needed).
- Version: the binaries print only the OpenFOAM banner ("(cfmesh)" in `cartesianMesh -help`); the
  sources and tutorials are not in the packages. It is ESI's "cfmesh" module, the community
  integration of cfMesh v1.1 (GPL-3): its repository (develop.openfoam.com/Community/integration-cfmesh,
  read-only clone at commit 3ff8555, 2024-12-18, outside the repository) carries the "cfMesh v1.1"
  user guide.
- Parallel options: OpenMP (libmeshLibrary.so and cartesianMesh link libgomp; a tutorial case,
  asmoOctree, ran at 1354 % CPU with the default threads) and MPI (`-parallel`, linked against
  libPstream/openmpi; the case must first be split with preparePar). `OMP_NUM_THREADS=1` does not
  limit it (591 % CPU): parts of the library size their thread pools from `omp_get_num_procs()`,
  which follows the CPU affinity, so `taskset` is what caps the threads (101 % CPU with one CPU).
  On that small case the single-CPU run was faster (4.5 s) than the default (5.3 s).
