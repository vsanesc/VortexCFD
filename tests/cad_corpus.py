"""Small CAD files written by the tests with OCP (no binary files in the repository)."""

from pathlib import Path


def _doc():
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    return doc, XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()), XCAFDoc_DocumentTool.ColorTool_s(doc.Main())


def _set_name(label, name: str) -> None:
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name

    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))


def _faces(shape) -> list:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape

    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, m)
    return [m.FindKey(i) for i in range(1, m.Extent() + 1)]


def _write(doc, path: Path, unit: str = "MM") -> Path:
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs

    STEPCAFControl_Controller.Init_s()
    Interface_Static.SetIVal_s("write.stepcaf.subshapes.name", 1)
    Interface_Static.SetCVal_s("write.step.unit", unit)
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    writer.SetColorMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    assert writer.Write(str(path)) == 1  # IFSelect_RetDone
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    return Path(path)


def box(dx: float = 10.0, dy: float = 20.0, dz: float = 30.0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def cylinder(radius: float = 5.0, height: float = 20.0):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    return BRepPrimAPI_MakeCylinder(radius, height).Shape()


BOX_FACE_NAMES = ["inlet", "outlet", "wall", "wall", "top", "bottom"]


def named_box_step(path: Path, unit: str = "MM", red_inlet: bool = True) -> Path:
    """A 10 x 20 x 30 box named "Body" whose six faces are named BOX_FACE_NAMES (two "wall")."""
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.XCAFDoc import XCAFDoc_ColorType

    doc, shapes, colors = _doc()
    shape = box()
    label = shapes.AddShape(shape, False)
    _set_name(label, "Body")
    for name, face in zip(BOX_FACE_NAMES, _faces(shape)):
        sub = shapes.AddSubShape(label, face)
        _set_name(sub, name)
        if red_inlet and name == "inlet":
            colors.SetColor(sub, Quantity_Color(1, 0, 0, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    return _write(doc, path, unit)


def cylinder_step(path: Path) -> Path:
    doc, shapes, _ = _doc()
    _set_name(shapes.AddShape(cylinder(), False), "Rod")
    return _write(doc, path)


def assembly_step(path: Path) -> Path:
    """An assembly "Pair" of a box "Block" and a cylinder "Pin" moved 50 mm along x."""
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    doc, shapes, _ = _doc()
    assembly = shapes.NewShape()
    _set_name(assembly, "Pair")
    block = shapes.AddShape(box(), False)
    _set_name(block, "Block")
    pin = shapes.AddShape(cylinder(), False)
    _set_name(pin, "Pin")
    shapes.AddComponent(assembly, block, TopLoc_Location())
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(50, 0, 0))
    shapes.AddComponent(assembly, pin, TopLoc_Location(move))
    shapes.UpdateAssemblies()
    return _write(doc, path)


def box_brep(path: Path) -> Path:
    from OCP.BRepTools import BRepTools

    assert BRepTools.Write_s(box(), str(path))
    return Path(path)


def box_iges(path: Path) -> Path:
    from OCP.IGESControl import IGESControl_Writer

    writer = IGESControl_Writer("MM", 1)  # BRep mode
    writer.AddShape(box())
    writer.ComputeModel()
    assert writer.Write(str(path))
    return Path(path)
