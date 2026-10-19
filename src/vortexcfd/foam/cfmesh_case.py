"""cfMesh evaluation case files (no Qt, no pyvista): phase 5.3, benchmark only.

The app meshes with snappyHexMesh (foam/mesh_case.py). This module writes the equivalent cfMesh
(cartesianMesh) case from the same MeshCaseInput, so the benchmark can compare the two meshers on the
same project inputs (benchmarks/RESULT_5.3.md). Nothing in the app calls it.

cfMesh ships with ESI OpenFOAM v2606 (module "cfmesh", the community integration of cfMesh v1.1,
GPL-3): cartesianMesh, tetMesh, pMesh and the surface utilities are in the platform's bin/, built with
OpenMP (libgomp) and MPI (``-parallel`` after ``preparePar``). The keywords follow the cfMesh v1.1 user
guide and its tutorials (cartesianMesh/asmoOctree, multipleOrifices, elbow_90degree).
"""

import shlex
import subprocess

from vortexcfd.foam.runner import OPENFOAM_BASHRC

# The executables of the cfMesh module this evaluation needs or reports on.
CFMESH_EXECUTABLES = (
    "cartesianMesh", "tetMesh", "pMesh", "cartesian2DMesh", "generateBoundaryLayers", "improveMeshQuality",
    "improveSymmetryPlanes", "surfaceFeatureEdges", "surfaceToFMS", "FMSToSurface", "checkSurfaceMesh",
    "mergeSurfacePatches", "preparePar",
)


def cfmesh_executables(names: tuple[str, ...] = CFMESH_EXECUTABLES) -> dict[str, str | None]:
    """{name: full path, or None when missing} with the OpenFOAM environment sourced as the app does."""
    script = f"source {shlex.quote(str(OPENFOAM_BASHRC))} >/dev/null 2>&1; " + "; ".join(
        f"echo {shlex.quote(n)} $(command -v {shlex.quote(n)} || echo -)" for n in names)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False).stdout
    found: dict[str, str | None] = {n: None for n in names}
    for line in out.splitlines():
        name, _, path = line.partition(" ")
        if name in found and path and path != "-":
            found[name] = path
    return found
