"""CAD union of the components of a model (surface preparation, D-093). No Qt.

Each component (the faces of one Part's CAD bodies) is sewn into closed solids with a tolerance tied
to the model size, the solids of all components are fused with OpenCASCADE's boolean fuse, and the
result is tessellated. Every face of the union keeps its source component and source CAD face through
the sewing and fuse history, so each component's share of the outer skin becomes that Part's surface
(its patches, region ids and per-part forces stay one per component). A component that cannot be
sewn closed or fused is reported with the reason and left out of the union (the caller falls back to
intersection features for it).
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.geometry import cad

# Sewing tolerance as a fraction of the model's bounding-box diagonal (OpenCASCADE's own default is a
# fixed 1e-6 model units): large enough for faces whose edges were exported a few microns apart,
# small against the 1e-3 default tessellation deflection. [NUMERICS-REVIEW]
SEW_TOLERANCE_FRACTION = 1e-5
# Cell array of the union's tessellation: the index of the component that owns the triangle.
OWNER_ARRAY = "component"


@dataclass(frozen=True)
class ComponentSource:
    """One component: a name (the Part), its CAD file and bodies (None: all of them) and the
    model's metres per unit."""

    name: str
    cad_file: Path
    bodies: list[int] | None
    unit_to_metre: float = 1e-3


@dataclass
class UnionResult:
    """``meshes``: per fused component, its share of the union's tessellation in metres, with the
    source CAD face id of every triangle in cad.FACE_ARRAY (all components share their boundary
    nodes, so together they are watertight). ``failed``: component -> reason. ``sew_tolerance``: per
    component, in metres. ``watertight``: the union's tessellation is closed."""

    meshes: dict[str, pv.PolyData] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    sew_tolerance: dict[str, float] = field(default_factory=dict)
    closed_after_sewing: dict[str, bool] = field(default_factory=dict)
    free_edges_after_sewing: dict[str, int] = field(default_factory=dict)
    volume: float = 0.0  # m3, the union
    watertight: bool = False
    open_edges: int = 0  # of the union's tessellation
    non_manifold_edges: int = 0
    time_s: float = 0.0
    notes: list[str] = field(default_factory=list)


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _valid(shape) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer

    return bool(BRepCheck_Analyzer(shape).IsValid())


def _shells(shape) -> list:
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer

    out = []
    explorer = TopExp_Explorer(shape, TopAbs_SHELL)
    while explorer.More():
        out.append(explorer.Current())
        explorer.Next()
    return out


@dataclass
class SewnComponent:
    """The closed solids of a component and, for each of their faces, the source global CAD face id
    (owner index into ``face_ids`` through ``faces``)."""

    solids: list
    faces: object  # IndexedMap of the sewn faces
    face_ids: list[int]  # global CAD face id per entry of ``faces`` (1-based map order)
    free_edges: int
    closed: bool


def sew_component(model: "cad.CadModel", bodies: list[int] | None, tolerance: float) -> SewnComponent:
    """Sew the faces of ``bodies`` (model units) into shells and make a solid of every closed shell.

    ``closed`` is False when a shell stays open (free edges) or nothing could be made a solid."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRep import BRep_Tool
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS

    chosen = range(len(model.bodies)) if bodies is None else bodies
    sew = BRepBuilderAPI_Sewing(tolerance)
    originals = []
    for b in chosen:
        body = model.bodies[b]
        for fid, face in zip(body.faces, cad._unique_faces(body.shape)):
            sew.Add(face)
            originals.append((fid, face))
    sew.Perform()
    sewn = sew.SewedShape()
    faces, face_ids = ShapeMap(), []
    for fid, face in originals:
        modified = sew.Modified(face)
        if faces.Add(modified) > len(face_ids):
            face_ids.append(fid)
    shells = _shells(sewn)
    closed = bool(shells) and all(BRep_Tool.IsClosed_s(s) for s in shells)
    solids = []
    if closed:
        for shell in shells:
            solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell(shell)).Solid()
            fix = ShapeFix_Solid(solid)
            fix.Perform()  # orients the shell outward
            solid = fix.Solid()
            if _volume(solid) <= 0 or not _valid(solid):
                closed = False
                break
            solids.append(solid)
    return SewnComponent(solids if closed else [], faces, face_ids, int(sew.NbFreeEdges()), closed)


def _fuse(shapes: list):
    """BRepAlgoAPI_Fuse of the shapes (the first one is the argument, the others the tools); None on
    failure (not done, invalid or empty result)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.collections import List_TopoDS_Shape

    if len(shapes) == 1:
        return None
    arguments, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
    arguments.Append(shapes[0])
    for s in shapes[1:]:
        tools.Append(s)
    op = BRepAlgoAPI_Fuse()
    op.SetArguments(arguments)
    op.SetTools(tools)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        return None
    result = op.Shape()
    if result.IsNull() or not _valid(result) or _volume(result) <= 0:
        return None
    return op


def _carry_owners(op, owners: list[tuple[object, tuple[int, int]]]) -> list[tuple[object, tuple[int, int]]]:
    """(face, owner) of the result of boolean ``op`` from the (face, owner) pairs of its inputs: a
    face that is not deleted and still in the result keeps its owner, a modified one passes it on.
    Faces of the result without a source (none expected for a fuse) get no entry."""
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap

    result = ShapeMap()
    for f in cad._unique_faces(op.Shape()):
        result.Add(f)
    owner_of: dict[int, tuple[int, int]] = {}
    for face, owner in owners:
        candidates = list(op.Modified(face))
        if not op.IsDeleted(face):
            candidates.append(face)
        for g in candidates:
            if result.Contains(g):
                owner_of.setdefault(result.FindIndex(g), owner)
    return [(result.FindKey(i), owner_of[i]) for i in range(1, result.Extent() + 1) if i in owner_of]


def _face_owners(sewn: SewnComponent, component: int) -> list[tuple[object, tuple[int, int]]]:
    """(face, (component, global CAD face id)) of a sewn component's solids."""
    out = []
    for solid in sewn.solids:
        for f in cad._unique_faces(solid):
            if sewn.faces.Contains(f):
                out.append((f, (component, sewn.face_ids[sewn.faces.FindIndex(f) - 1])))
    return out


def union_components(components: list[ComponentSource], linear_deflection: float, angular_deflection_deg: float
                     ) -> UnionResult:
    """Sew, fuse and tessellate ``components``; ``linear_deflection`` in metres, the angle in degrees.

    All components are fused in one operation; when that fails they are fused one by one in order and
    every component whose addition fails is left out (reported in ``failed``)."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools

    start = time.monotonic()
    out = UnionResult()
    models: dict[Path, cad.CadModel] = {}
    sewn: dict[int, SewnComponent] = {}
    for k, comp in enumerate(components):
        path = Path(comp.cad_file)
        try:
            model = models.get(path) or models.setdefault(path, cad.read_cad(path))
        except (OSError, cad.CadImportError) as exc:
            out.failed[comp.name] = f"cannot read {path.name}: {exc}"
            continue
        tolerance = SEW_TOLERANCE_FRACTION * model.diagonal
        out.sew_tolerance[comp.name] = tolerance * comp.unit_to_metre
        result = sew_component(model, comp.bodies, tolerance)
        out.closed_after_sewing[comp.name] = result.closed
        out.free_edges_after_sewing[comp.name] = result.free_edges
        if not result.closed:
            out.failed[comp.name] = (f"not closed after sewing at {tolerance * comp.unit_to_metre:.3g} m "
                                     f"({result.free_edges} free edges)")
            continue
        sewn[k] = result
    order = list(sewn)
    if not order:
        out.time_s = time.monotonic() - start
        return out
    # One fuse of everything; one component at a time when it fails.
    owners = [pair for k in order for pair in _face_owners(sewn[k], k)]
    solids = [s for k in order for s in sewn[k].solids]
    fused = None
    if len(solids) > 1:
        op = _fuse(solids)
        if op is not None:
            fused, owners = op.Shape(), _carry_owners(op, owners)
    else:
        fused = solids[0]
    if fused is None:
        out.notes.append("the fuse of all components failed; fused one component at a time")
        fused, owners, kept = None, [], []
        for k in order:
            own = _face_owners(sewn[k], k)
            if fused is None and len(sewn[k].solids) == 1:
                fused, owners = sewn[k].solids[0], own
                kept.append(k)
                continue
            op = _fuse(([fused] if fused is not None else []) + sewn[k].solids)
            if op is None:
                out.failed[components[k].name] = ("the boolean fuse with the other components failed"
                                                  if fused is not None else "its solids cannot be fused together")
                continue
            fused, owners = op.Shape(), _carry_owners(op, owners + own)
            kept.append(k)
        order = kept
    if fused is None:
        out.time_s = time.monotonic() - start
        return out
    out.volume = _volume(fused) * components[order[0]].unit_to_metre ** 3
    # Tessellate the union (shared edges: watertight) and split it by owner.
    scale = components[order[0]].unit_to_metre
    BRepTools.Clean_s(fused)
    BRepMesh_IncrementalMesh(fused, linear_deflection / scale, False, np.radians(angular_deflection_deg), True)
    points, tris, ids, comp_of = [], [], [], []
    offset = 0
    for face, (k, fid) in owners:
        got = cad.face_triangulation(face)
        if got is None:
            continue
        nodes, faces = got
        points.append(nodes * scale)
        tris.append(faces + offset)
        ids.append(np.full(len(faces), fid, dtype=np.int32))
        comp_of.append(np.full(len(faces), k, dtype=np.int32))
        offset += len(nodes)
    if not tris:
        for k in order:
            out.failed[components[k].name] = "the union produced no triangles"
        out.time_s = time.monotonic() - start
        return out
    whole = _merged_with_owner(points, tris, ids, comp_of)
    from vortexcfd.geometry.checks import check_surface

    check = check_surface(whole, intersections=False)
    out.watertight, out.open_edges, out.non_manifold_edges = check.watertight, check.open_edges, check.non_manifold_edges
    owner = np.asarray(whole.cell_data[OWNER_ARRAY])
    for k in order:
        cells = np.flatnonzero(owner == k)
        if not len(cells):
            out.failed[components[k].name] = "none of its surface is on the outside of the union"
            continue
        piece = whole.extract_cells(cells).extract_surface(algorithm=None)
        piece = piece.clean(tolerance=0.0)
        mesh = pv.PolyData(piece.points, piece.faces)
        mesh.cell_data[cad.FACE_ARRAY] = np.asarray(piece.cell_data[cad.FACE_ARRAY], dtype=np.int32)
        out.meshes[components[k].name] = mesh
    out.time_s = time.monotonic() - start
    return out



def _merged_with_owner(points: list, tris: list, ids: list, comp_of: list) -> pv.PolyData:
    mesh = cad.merged_surface(points, tris, ids)
    # merged_surface drops collapsed triangles: apply the same filter to the owners.
    pts = np.concatenate(points).astype(np.float32).astype(np.float64)
    _unique, inverse = np.unique(pts, axis=0, return_inverse=True)
    cells = inverse.reshape(-1)[np.concatenate(tris)]
    ok = (cells[:, 0] != cells[:, 1]) & (cells[:, 1] != cells[:, 2]) & (cells[:, 0] != cells[:, 2])
    mesh.cell_data[OWNER_ARRAY] = np.concatenate(comp_of)[ok]
    return mesh
