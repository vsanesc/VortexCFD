"""CAD import through OpenCASCADE (OCP): STEP, IGES and BREP to triangle meshes (no Qt).

``read_cad`` lists the bodies (solids, or shells / faces of a surface model) and their faces with
the names and colours the file carries; ``tessellate`` turns them into a PyVista surface keeping the
CAD face of every triangle (cell array FACE_ARRAY). Coordinates stay in the file's model units:
STEP and IGES are converted by OpenCASCADE to millimetres; BREP files have no units (D-070).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

STEP_EXTENSIONS = (".step", ".stp")
IGES_EXTENSIONS = (".iges", ".igs")
BREP_EXTENSIONS = (".brep", ".brp")
CAD_EXTENSIONS = STEP_EXTENSIONS + IGES_EXTENSIONS + BREP_EXTENSIONS

FACE_ARRAY = "cad_face"
# Defaults (D-070): linear deflection as a fraction of the model's bounding-box diagonal; angular
# deflection in degrees.
LINEAR_DEFLECTION_FRACTION = 1e-3
ANGULAR_DEFLECTION_DEG = 20.0


class CadImportError(Exception):
    """The file cannot be read as CAD, or holds no surface."""


@dataclass(frozen=True)
class CadFace:
    body: int  # index into CadModel.bodies
    name: str | None  # the face's own name in the file (STEP: ADVANCED_FACE name)
    color: str | None  # "#rrggbb" surface colour from the file


@dataclass
class CadBody:
    name: str
    shape: object = field(repr=False)  # located TopoDS_Shape
    faces: list[int] = field(default_factory=list)  # global face ids, in TopExp order


@dataclass
class CadModel:
    path: Path
    units: str | None  # "mm" for STEP / IGES (converted by OpenCASCADE), None for BREP
    bodies: list[CadBody]
    faces: list[CadFace]
    diagonal: float  # bounding-box diagonal, model units

    def default_linear_deflection(self) -> float:
        """LINEAR_DEFLECTION_FRACTION of the bounding-box diagonal, in model units."""
        return LINEAR_DEFLECTION_FRACTION * self.diagonal

    def face_groups(self, bodies: list[int] | None = None) -> list[tuple[str, list[int], str | None]]:
        """Regions of the faces of ``bodies`` (all when None): one per face name (faces sharing a
        name form one group); unnamed faces take their body's name. (name, face ids, colour) in
        order of first appearance; the colour is the group's first coloured face's."""
        chosen = set(range(len(self.bodies)) if bodies is None else bodies)
        groups: dict[str, tuple[list[int], list[str | None]]] = {}
        for fid, face in enumerate(self.faces):
            if face.body not in chosen:
                continue
            key = face.name or self.bodies[face.body].name
            members, colors = groups.setdefault(key, ([], []))
            members.append(fid)
            colors.append(face.color)
        return [(name, members, next((c for c in colors if c), None)) for name, (members, colors) in groups.items()]


def _ext(path: Path) -> str:
    return Path(path).suffix.lower()


# Names OpenCASCADE gives a shape that has none of its own (its type): not a component name.
GENERIC_NAMES = frozenset({"COMPOUND", "COMPSOLID", "SOLID", "SHELL", "FACE", "WIRE", "EDGE", "VERTEX", "SHAPE",
                           "NONE", "OPEN_SHELL", "CLOSED_SHELL", "MANIFOLD_SOLID_BREP"})
# A leading token like "QWERTYUIOP" (upper-case letters and digits, 8 or more) in a comma-separated
# entity name is an identifier, not part of the name.
_ID_TOKEN = re.compile(r"^[A-Z0-9]{8,}$")


def clean_name(text: str | None) -> str | None:
    """A component name from a STEP name: None when empty, XCAF's generated "=>[0:1:1:2]" form or a
    generic type name; a comma-separated name ("<id>, Fuselage, 0") loses a leading identifier token
    and joins the rest with "_" ("Fuselage_0"); characters outside letters, digits, space, "_", "."
    and "-" become "_" (D-098)."""
    if text is None:
        return None
    text = " ".join(str(text).split())
    if not text or text.startswith("=>[") or text.upper() in GENERIC_NAMES:
        return None
    tokens = [t.strip() for t in text.split(",") if t.strip()]
    if len(tokens) > 1 and _ID_TOKEN.match(tokens[0]):
        tokens = tokens[1:]
    name = "_".join(tokens) if len(tokens) > 1 else tokens[0]
    name = re.sub(r"[^A-Za-z0-9 _.-]", "_", name).strip(" ._")
    return name or None


def _name(label) -> str | None:
    """The label's name (cleaned, ``clean_name``); None when it has none."""
    from OCP.TDataStd import TDataStd_Name

    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return clean_name(attr.Get().ToExtString())
    return None


def _entity_name(transfer_reader, shape) -> str | None:
    """The name of the STEP entity a shape was transferred from (e.g. a GEOMETRIC_SET of a surface
    model, whose components carry no product), cleaned; None when there is none."""
    if transfer_reader is None:
        return None
    try:
        entity = transfer_reader.EntityFromShapeResult(shape, 1)
    except Exception:  # an unmapped shape
        return None
    if entity is None or not hasattr(entity, "Name"):
        return None
    try:
        return clean_name(entity.Name().ToCString())
    except Exception:
        return None


def _color(color_tool, label, shape) -> str | None:
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorType

    color = Quantity_Color()
    for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen):
        if (label is not None and not label.IsNull() and color_tool.GetColor_s(label, kind, color)) or \
                color_tool.GetColor(shape, kind, color):
            r, g, b = (max(0, min(255, round(255 * v))) for v in (color.Red(), color.Green(), color.Blue()))
            return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _unique_faces(shape) -> list:
    """The faces of a shape in TopExp order, each once (a face shared by two solids counts once)."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp

    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    return [fmap.FindKey(i) for i in range(1, fmap.Extent() + 1)]


def _bodies_of(shape) -> list:
    """Solids of a shape; otherwise its shells; otherwise the shape itself (loose faces)."""
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp

    for kind in (TopAbs_SOLID, TopAbs_SHELL):
        m = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, m)
        if m.Extent():
            return [m.FindKey(i) for i in range(1, m.Extent() + 1)]
    return [shape]


class _Collector:
    """Builds the bodies and faces of a CadModel."""

    def __init__(self) -> None:
        self.bodies: list[CadBody] = []
        self.faces: list[CadFace] = []
        self._names: set[str] = set()

    def unique(self, base: str) -> str:
        name, n = base, 1
        while name in self._names:
            n += 1
            name = f"{base}_{n}"
        self._names.add(name)
        return name

    def add(self, name: str, body_shape, face_info) -> None:
        """face_info(face) -> (name, colour) for each face of the body."""
        index = len(self.bodies)
        body = CadBody(self.unique(name), body_shape)
        for face in _unique_faces(body_shape):
            fname, fcolor = face_info(face)
            body.faces.append(len(self.faces))
            self.faces.append(CadFace(index, fname, fcolor))
        if body.faces:
            self.bodies.append(body)
        else:
            self._names.discard(body.name)


def _read_xcaf(path: Path, step: bool) -> tuple[list[CadBody], list[CadFace]]:
    from OCP.collections import Sequence_TDF_Label
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    if step:
        from OCP.Interface import Interface_Static
        from OCP.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Reader

        STEPCAFControl_Controller.Init_s()
        Interface_Static.SetIVal_s("read.stepcaf.subshapes.name", 1)  # face names
        reader = STEPCAFControl_Reader()
    else:
        from OCP.IGESCAFControl import IGESCAFControl_Reader

        reader = IGESCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise CadImportError(f"Cannot read {Path(path).name}: not a valid {'STEP' if step else 'IGES'} file")
    if not reader.Transfer(doc):
        raise CadImportError(f"Cannot transfer the shapes of {Path(path).name}")
    try:  # traces a shape back to its STEP entity (component names of surface models)
        transfer = reader.ChangeReader().WS().TransferReader() if step else None
    except Exception:
        transfer = None
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    out = _Collector()

    def face_info_for(proto_label):
        def info(face):
            sub = TDF_Label()
            found = shapes.FindSubShape(proto_label, face, sub) if not proto_label.IsNull() else False
            name = _name(sub) if found else None
            return name, _color(colors, sub if found else None, face)
        return info

    def visit(label, location, inherited: str | None) -> None:
        ref = TDF_Label()
        proto = ref if shapes.IsReference_s(label) and shapes.GetReferredShape_s(label, ref) else label
        name = (_name(proto) or _name(label) or _entity_name(transfer, shapes.GetShape_s(proto)) or inherited
                or Path(path).stem)
        if shapes.IsAssembly_s(proto):
            comps = Sequence_TDF_Label()
            shapes.GetComponents_s(proto, comps, False)
            for i in range(1, comps.Length() + 1):
                comp = comps.Value(i)
                loc = location.Multiplied(shapes.GetLocation_s(comp))
                visit(comp, loc, None)
            return
        shape = shapes.GetShape_s(proto)
        solids = _bodies_of(shape)
        for k, body in enumerate(solids):
            sub = TDF_Label()
            body_name = name
            if len(solids) > 1:
                named = (_name(sub) if shapes.FindSubShape(proto, body, sub) else None) or _entity_name(transfer, body)
                body_name = named or f"{name}_{k + 1}"
            body_located = body.Moved(location) if not location.IsIdentity() else body
            # Face names are found on the prototype (un-located) faces, in the same order.
            proto_faces = _unique_faces(body)
            infos = [face_info_for(proto)(f) for f in proto_faces]
            it = iter(infos)
            out.add(body_name, body_located, lambda _face, it=it: next(it))

    free = Sequence_TDF_Label()
    shapes.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        visit(free.Value(i), TopLoc_Location(), None)
    return out.bodies, out.faces


def _read_brep(path: Path) -> tuple[list[CadBody], list[CadFace]]:
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise CadImportError(f"Cannot read {Path(path).name}: not a valid BREP file")
    out = _Collector()
    bodies = _bodies_of(shape)
    for k, body in enumerate(bodies):
        out.add(Path(path).stem if len(bodies) == 1 else f"{Path(path).stem}_{k + 1}", body, lambda _f: (None, None))
    return out.bodies, out.faces


def _diagonal(bodies: list[CadBody]) -> float:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    for body in bodies:
        BRepBndLib.Add_s(body.shape, box)
    if box.IsVoid():
        return 0.0
    box.SetGap(0.0)
    return float(np.sqrt(box.SquareExtent()))


def read_cad(path: Path) -> CadModel:
    """Read a STEP, IGES or BREP file.

    Raises:
        FileNotFoundError: the file does not exist.
        CadImportError: unsupported extension, unreadable file, or no faces.
    """
    path = Path(path)
    ext = _ext(path)
    if ext not in CAD_EXTENSIONS:
        raise CadImportError(f"Unsupported CAD file type '{path.suffix}'; supported: {', '.join(CAD_EXTENSIONS)}")
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if ext in BREP_EXTENSIONS:
        bodies, faces = _read_brep(path)
        units = None
    else:
        bodies, faces = _read_xcaf(path, step=ext in STEP_EXTENSIONS)
        units = "mm"  # OpenCASCADE converts STEP and IGES lengths to millimetres
    if not faces:
        raise CadImportError(f"{path.name} contains no faces")
    return CadModel(path, units, bodies, faces, _diagonal(bodies))


def tessellate(model: CadModel, linear_deflection: float, angular_deflection_deg: float,
               bodies: list[int] | None = None) -> pv.PolyData:
    """Triangulate ``bodies`` (all when None) with OpenCASCADE's BRepMesh.

    ``linear_deflection`` is in model units, the angle in degrees. Returns a triangle surface in
    model units, coincident points merged, degenerate triangles dropped, with the global CAD face
    id of every triangle in cell array FACE_ARRAY; reversed faces are flipped so the normals follow
    the CAD orientation.
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools

    if linear_deflection <= 0 or angular_deflection_deg <= 0:
        raise ValueError("deflections must be positive")
    chosen = range(len(model.bodies)) if bodies is None else bodies
    points, tris, face_ids = [], [], []
    offset = 0
    for b in chosen:
        body = model.bodies[b]
        BRepTools.Clean_s(body.shape)  # BRepMesh keeps an existing finer triangulation otherwise
        BRepMesh_IncrementalMesh(body.shape, linear_deflection, False, np.radians(angular_deflection_deg), True)
        for fid, face_shape in zip(body.faces, _unique_faces(body.shape)):
            got = face_triangulation(face_shape)
            if got is None:
                continue
            nodes, faces = got
            points.append(nodes)
            tris.append(faces + offset)
            face_ids.append(np.full(len(faces), fid, dtype=np.int32))
            offset += len(nodes)
    if not tris:
        raise CadImportError(f"{model.path.name}: tessellation produced no triangles")
    return merged_surface(points, tris, face_ids)


def face_triangulation(face_shape) -> tuple[np.ndarray, np.ndarray] | None:
    """(nodes (n, 3), triangles (m, 3), 0-based) of a meshed face, in model units, the triangles
    flipped for a reversed face so the normals follow the CAD orientation; None when the face has no
    triangulation."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    face = TopoDS.Face(face_shape)
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return None
    trsf = loc.Transformation()
    identity = loc.IsIdentity()
    n_nodes = tri.NbNodes()
    nodes = np.empty((n_nodes, 3))
    for i in range(1, n_nodes + 1):
        p = tri.Node(i) if identity else tri.Node(i).Transformed(trsf)
        nodes[i - 1] = (p.X(), p.Y(), p.Z())
    faces = np.empty((tri.NbTriangles(), 3), dtype=np.int64)
    for i in range(1, tri.NbTriangles() + 1):
        faces[i - 1] = tri.Triangle(i).Get()
    faces -= 1
    if face.Orientation() == TopAbs_REVERSED:
        faces = faces[:, ::-1]
    return nodes, faces


def merged_surface(points: list, tris: list, face_ids: list) -> pv.PolyData:
    """One surface from per-face nodes and triangles (``tris`` already offset into the concatenated
    ``points``), with the CAD face id of every triangle in FACE_ARRAY."""
    pts, cells, ids = np.concatenate(points), np.concatenate(tris), np.concatenate(face_ids)
    # Merge coincident points (faces share their edge nodes) at the float32 precision of binary STL,
    # so the written tessellation reads back with the same triangles, and drop collapsed triangles.
    pts = pts.astype(np.float32).astype(np.float64)
    unique, inverse = np.unique(pts, axis=0, return_inverse=True)
    cells = inverse.reshape(-1)[cells]
    ok = (cells[:, 0] != cells[:, 1]) & (cells[:, 1] != cells[:, 2]) & (cells[:, 0] != cells[:, 2])
    cells, ids = cells[ok], ids[ok]
    mesh = pv.PolyData(unique, faces=np.hstack([np.full((len(cells), 1), 3), cells]).ravel())
    mesh.cell_data[FACE_ARRAY] = ids
    return mesh


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tessellation_key(cad_file: Path, linear_deflection: float, angular_deflection_deg: float,
                     bodies: list[int] | None) -> str:
    """12 hex characters identifying a tessellation (file content, deflections, bodies)."""
    text = f"{file_digest(cad_file)}|{linear_deflection:.12g}|{angular_deflection_deg:.12g}|{bodies}"
    return hashlib.sha256(text.encode()).hexdigest()[:12]
