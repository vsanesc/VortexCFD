# Open-source survey for geometry import, repair and meshing (Task 0.2)

Date: 2026-10-16. Scope: tools needed for Phase 3 (geometry) and Phase 5 (meshing).
Status column: "verified" = checked against the project page during this survey;
"to verify" = from general knowledge, must be confirmed before adoption.

Project constraint: VortexCFD is GPL-3.0-or-later, so dependencies must be GPL-3 compatible
(GPL-3, LGPL, MPL-2.0, Apache-2.0, BSD, MIT are fine; AGPL-3 is combinable with GPL-3).

| Tool | Purpose | License | Install route | Status | Recommendation |
|---|---|---|---|---|---|
| PyVista / VTK | Read STL/OBJ/PLY, surface checks (boundary and non-manifold edges, normals, areas), rendering, picking | MIT / BSD | already a dependency | to verify readers per format | **Use now** (3.1, 2.2). No new dependency. |
| snappyHexMesh | Hex-dominant volume mesh with prism layers | GPL-3 (OpenFOAM) | bundled with ESI v2606 | verified (bundled) | **Mesher level M1** (5.1). |
| cfMesh (cartesianMesh) | Cartesian/cut-cell mesh with boundary layers, input is a surface triangulation | GPL-3-or-later | no longer bundled with recent ESI releases; compiles from develop.openfoam.com Community/integration-cfmesh (reported working with v2506) | verified (license, build route); v2606 build to test | **Candidate for M3** (5.3). Spike: build against v2606 in WSL. |
| fTetWild via pytetwild | Robust tetrahedralisation of dirty/non-manifold surfaces; its envelope output can serve as a "wrapper" for leaky STLs | MPL-2.0 | `pip install pytetwild`, wheels for Python 3.10-3.14 on Linux, maintained under the PyVista org | verified | **Candidate for M2 surface preparation** (5.2) and repair fallback (3.3). |
| MeshFix via pymeshfix | Hole filling and repair of triangle surfaces | MeshFix is GPL-3 (or commercial contract); wrapper licence reported inconsistently (permissive vs AGPL) | `pip install pymeshfix` | partially verified: confirm wrapper licence | **Candidate for repair** (3.3). Acceptable for a GPL project once the wrapper licence is confirmed. |
| OpenCASCADE via OCP (CadQuery bindings) | STEP/IGES/BREP import, face names, tessellation, sewing | OCCT LGPL-2.1 with exception; CadQuery Apache-2.0 | PyPI wheels for Linux | verified (wheels exist); licences to verify | **Use for CAD import** (3.2). RISK: OCP wheels come in "vtk" and "novtk" builds; the vtk build pins its own VTK version and may conflict with PyVista's VTK. Spike first with the novtk build. |
| Gmsh | Surface/volume meshing, CAD import | GPL-2-or-later with exceptions | pip wheels | to verify | Keep as alternative; not planned. |
| CfdOF (FreeCAD workbench) | Existing open-source GUI front-end for OpenFOAM (snappyHexMesh, cfMesh, gmsh, HiSA) | GPL | FreeCAD addon | verified (scope); supported OpenFOAM versions to verify | **Reference, not a dependency.** Study its case templates and meshing dictionaries; code reuse is licence-compatible if ever needed. |

## Decisions proposed

1. Phase 3.1 (STL/OBJ/PLY import and checks) and 2.2 (viewer) use PyVista/VTK only. No new dependency.
2. Phase 3.2 (STEP) starts with a spike: OCP novtk wheel + PyVista in the same venv; adopt only if both import and render without VTK conflicts.
3. Phase 3.3 (repair): pymeshfix first, pytetwild envelope as fallback for badly broken inputs. Confirm pymeshfix wrapper licence before adding it.
4. Phase 5: M1 snappyHexMesh; M3 cfMesh after a build spike on v2606; pytetwild evaluated for M2.

## Open items

- Self-intersection detection is not covered by PyVista checks; defer to 3.3 (pymeshfix or fTetWild).
- Confirm CfdOF's currently supported OpenFOAM ESI versions before borrowing templates.
