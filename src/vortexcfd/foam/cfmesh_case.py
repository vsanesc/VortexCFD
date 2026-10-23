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
from dataclasses import dataclass, replace
from pathlib import Path

from vortexcfd.foam.case_writer import FoamFileSpec
from vortexcfd.foam.mesh_case import (
    BOUNDARY_PATCH_TYPES,
    TRI_SURFACE,
    MeshCaseInput,
    control_dict,
    fv_schemes,
    fv_solution,
    part_level_range,
    surface_feature_extract_dict,
)
from vortexcfd.foam import runner

# The executables of the cfMesh module this evaluation needs or reports on.
CFMESH_EXECUTABLES = (
    "cartesianMesh", "tetMesh", "pMesh", "cartesian2DMesh", "generateBoundaryLayers", "improveMeshQuality",
    "improveSymmetryPlanes", "surfaceFeatureEdges", "surfaceToFMS", "FMSToSurface", "checkSurfaceMesh",
    "mergeSurfacePatches", "preparePar",
)


def cfmesh_executables(names: tuple[str, ...] = CFMESH_EXECUTABLES) -> dict[str, str | None]:
    """{name: full path, or None when missing} with the OpenFOAM environment sourced as the app does."""
    script = f"source {shlex.quote(str(runner.bashrc()))} >/dev/null 2>&1; " + "; ".join(
        f"echo {shlex.quote(n)} $(command -v {shlex.quote(n)} || echo -)" for n in names)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False).stdout
    found: dict[str, str | None] = {n: None for n in names}
    for line in out.splitlines():
        name, _, path = line.partition(" ")
        if name in found and path and path != "-":
            found[name] = path
    return found


# The combined surface cartesianMesh meshes (constant/triSurface): the domain surface plus every part,
# one STL solid per patch, named as the snappyHexMesh patches; surfaceFeatureEdges turns it into an
# .fms with the feature edges, which is the surfaceFile.
COMBINED_SURFACE = "vortexcfd_cfmesh"
COMBINED_STL = f"{TRI_SURFACE}/{COMBINED_SURFACE}.stl"
COMBINED_FMS = f"{TRI_SURFACE}/{COMBINED_SURFACE}.fms"
# cfMesh's own defaults for the layer optimisation (cfMesh v1.1 user guide, boundaryLayers ->
# optimisationParameters), written out so the case shows them. [NUMERICS-REVIEW]
LAYER_OPTIMISATION = {
    "nSmoothNormals": 3,
    "maxNumIterations": 5,
    "featureSizeFactor": 0.4,
    "reCalculateNormals": 1,
    "relThicknessTol": 0.1,
}


def level_size(base: float, level: int) -> float:
    """The cell size of an octree (or snappyHexMesh) refinement level."""
    return base / 2 ** level


@dataclass(frozen=True)
class LayerSpec:
    """The layers cfMesh is asked for on every part patch: the snappyHexMesh stack's count and ratio;
    ``max_first`` caps the first layer (None: relative sizing, no cap)."""

    count: int
    ratio: float
    max_first: float | None


def layer_spec(inp: MeshCaseInput) -> LayerSpec:
    """The same stack as snappyHexMesh's (mesh_case._layer_sizing): with absolute (y+) sizing or a
    fixed stack, the y+ first-layer thickness becomes maxFirstLayerThickness. cfMesh splits the one
    boundary cell it already has into the layers (refineBoundaryLayers), so the stack is about one
    boundary cell thick and the first layer is min(maxFirstLayerThickness, the geometric split of
    that cell); it cannot grow a stack thicker than the cell as snappyHexMesh does. [NUMERICS-REVIEW]"""
    m = inp.mesh
    if inp.fixed_layers is not None:
        return LayerSpec(inp.fixed_layers[1], inp.layer_expansion or m.expansion_ratio, inp.fixed_layers[0])
    if m.layer_sizing == "absolute_yplus":
        if inp.first_layer_thickness is None or inp.layer_count is None:
            raise ValueError("layer_sizing 'absolute_yplus' needs first_layer_thickness and layer_count")
        return LayerSpec(inp.layer_count, inp.layer_expansion or m.expansion_ratio, inp.first_layer_thickness)
    return LayerSpec(m.layers, m.expansion_ratio, None)


def part_levels(inp: MeshCaseInput) -> list[tuple[int, int]]:
    """Every part's (min, max) surface levels, as snappyHexMesh gets them."""
    est = inp.estimate()
    return [part_level_range(est.level_min, est.level_max,
                             inp.part_levels[i] if i < len(inp.part_levels) else (None, None))
            for i in range(len(inp.parts))]


def patch_types(inp: MeshCaseInput) -> dict[str, str]:
    """Every patch of the combined surface and its type: the part patches are walls, the domain patches
    those of the snappyHexMesh case (the symmetry plane symmetryPlane)."""
    types = {p: "wall" for p in inp.patches}
    for name in inp.expected_domain_patches():
        types[name] = BOUNDARY_PATCH_TYPES.get(name, "patch")
    return types


def mesh_dict(inp: MeshCaseInput) -> FoamFileSpec:
    """system/meshDict of cartesianMesh, mapped from the snappyHexMesh settings (DECISIONS D-102):

    - maxCellSize: the background cell size (snappyHexMesh's blockMesh cells, level 0);
    - localRefinement: each part patch at its part's minimum surface level, the level snappyHexMesh
      gives every cell the surface cuts (the maximum level is reached only where the surface turns more
      than resolveFeatureAngle within a cell, which feature edges and curvature cover below);
    - edgeMeshRefinement: each part's surfaceFeatureExtract edges (the same <part>.eMesh files
      snappyHexMesh refines and snaps to) at the part's maximum level; the surface preparation's
      junction curves at their own level;
    - no minCellSize: snappyHexMesh's curvatureLevel has no working counterpart. cfMesh's automatic
      curvature and proximity refinement (minCellSize at the finest curvature level, maximum surface level
      + Mesh.curvature_levels) marked about 100,000 octree boxes by its curvature criterion on the
      benchmark Ahmed body and gave 5,862,900 cells (snappyHexMesh: 225,842) [NUMERICS-REVIEW];
    - boundaryLayers: the y+ stack on every part patch (layer_spec), optimiseLayer on;
    - renameBoundary: the patch types of the snappyHexMesh case.
    No boundaryCellSize (it would refine the domain boundary too; the parts get theirs per patch) and no
    locationInMesh (cfMesh keeps the region the closed combined surface encloses)."""
    est = inp.estimate()
    base = est.base_size
    levels = part_levels(inp)
    local = {}
    edges = {}
    for i, name in enumerate(inp.parts):
        lo, hi = levels[i]
        for patch in inp.patches_of(i):
            local[patch] = {"cellSize": level_size(base, lo)}
        edges[name] = {"edgeFile": f'"{TRI_SURFACE}/{name}.eMesh"', "cellSize": level_size(base, hi)}
    for file_name, level in inp.extra_features:
        edges[Path(file_name).stem] = {"edgeFile": f'"{TRI_SURFACE}/{file_name}"', "cellSize": level_size(base, level)}
    content: dict = {
        "surfaceFile": f'"{COMBINED_FMS}"',
        "maxCellSize": base,
    }
    content["localRefinement"] = local
    content["edgeMeshRefinement"] = edges
    spec = layer_spec(inp)
    if spec.count >= 2:  # cfMesh splits the boundary cell only into two or more layers
        entry: dict = {"nLayers": spec.count, "thicknessRatio": spec.ratio}
        if spec.max_first is not None:
            entry["maxFirstLayerThickness"] = spec.max_first
        entry["allowDiscontinuity"] = 0
        content["boundaryLayers"] = {
            "patchBoundaryLayers": {p: dict(entry) for p in inp.patches},
            "optimiseLayer": 1,
            "optimisationParameters": dict(LAYER_OPTIMISATION),
        }
    content["renameBoundary"] = {
        "newPatchNames": {p: {"newName": p, "type": t} for p, t in patch_types(inp).items()},
    }
    return FoamFileSpec(content=content)


def build_cfmesh_files(inp: MeshCaseInput) -> dict[str, FoamFileSpec]:
    """Every dictionary of the cfMesh evaluation case: relative path -> spec. surfaceFeatureExtract
    writes the parts' edge files from their own STLs, exactly as for snappyHexMesh."""
    files = {
        "system/controlDict": control_dict(),
        "system/fvSchemes": fv_schemes(),
        "system/fvSolution": fv_solution(),
        "system/meshDict": mesh_dict(inp),
    }
    if inp.parts:
        files["system/surfaceFeatureExtractDict"] = surface_feature_extract_dict(replace(inp, domain_shape="box"))
    return files


def cfmesh_commands(inp: MeshCaseInput, cpus: tuple[int, ...] = ()) -> tuple[tuple[str, list[str]], ...]:
    """The steps of the evaluation run (foam/mesh_run.MeshRun ``steps``). ``cpus``: the logical CPUs
    cartesianMesh may use (taskset; its OpenMP threads follow the affinity, not OMP_NUM_THREADS); empty:
    no limit. improveSymmetryPlanes runs with a symmetry plane, as cfMesh advises."""
    prefix = ["taskset", "-c", ",".join(str(c) for c in cpus)] if cpus else []
    steps: list[tuple[str, list[str]]] = []
    if inp.parts:
        steps.append(("surfaceFeatureExtract", ["surfaceFeatureExtract"]))
    steps.append(("surfaceFeatureEdges", ["surfaceFeatureEdges", "-angle", f"{inp.mesh.feature_angle:g}",
                                          COMBINED_STL, COMBINED_FMS]))
    steps.append(("cartesianMesh", prefix + ["cartesianMesh"]))
    if inp.symmetric:
        steps.append(("improveSymmetryPlanes", ["improveSymmetryPlanes"]))
    steps.append(("checkMesh", ["checkMesh"]))
    return tuple(steps)
