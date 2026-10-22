"""The geometry of the results scene objects (D-132, no Qt): a clip of the fluid volume, an isosurface of a field
and streamlines of U, computed from the internal mesh of a solved case (PyVista's OpenFOAM reader: cell data).

Each function returns a PyVista dataset with POINT data (the cell fields interpolated to the points), so the viewer
colours it by any field with foam/results.field_values on its point arrays.
"""

import math

import numpy as np
import pyvista as pv

from vortexcfd.foam.results import FIELDS_BY_KEY, field_values

ISO_ARRAY = "_iso"


def point_fields(internal: pv.UnstructuredGrid) -> pv.UnstructuredGrid:
    """The internal mesh with its cell fields also as point data (the clip keeps both, contour and streamlines need
    point data)."""
    return internal.cell_data_to_point_data(pass_cell_data=True)


def _unit(v) -> tuple[float, float, float]:
    n = math.sqrt(sum(float(c) ** 2 for c in v))
    return tuple(float(c) / n for c in v)  # type: ignore[return-value]


def clip_geometry(points: pv.UnstructuredGrid, obj) -> pv.UnstructuredGrid:
    """The volume on the kept side of the clip plane (``obj.keep`` "behind": the side the normal points away from)."""
    return points.clip(normal=_unit(obj.normal), origin=tuple(obj.origin), invert=obj.keep == "behind")


def iso_geometry(points: pv.UnstructuredGrid, obj, u_ref: float, direction=(1.0, 0.0, 0.0)) -> pv.PolyData:
    """The isosurface ``obj.field`` = ``obj.value`` (empty when the value is outside the field's range).

    Raises:
        ValueError: the field is not a volume scalar the case has.
    """
    spec = FIELDS_BY_KEY.get(obj.field)
    if spec is None or spec.source not in points.point_data:
        raise ValueError(f"no field {obj.field!r} in the results")
    work = points.copy(deep=False)
    work.point_data[ISO_ARRAY] = field_values(spec, {spec.source: points.point_data[spec.source]}, u_ref, direction)
    values = np.asarray(work.point_data[ISO_ARRAY])
    if not values.size or not (values.min() <= obj.value <= values.max()):
        return pv.PolyData()
    return work.contour(isosurfaces=[float(obj.value)], scalars=ISO_ARRAY)


def seed_points(obj) -> pv.PolyData:
    """The streamlines' seeds: ``n_seeds`` points evenly along the line, or a near-square grid of at least
    ``n_seeds`` points over the plane (k x k with k = ceil(sqrt(n))), cut to ``n_seeds``."""
    if obj.seed == "line":
        p1, p2 = np.asarray(obj.point1, dtype=float), np.asarray(obj.point2, dtype=float)
        t = np.linspace(0.0, 1.0, obj.n_seeds) if obj.n_seeds > 1 else np.array([0.5])
        return pv.PolyData(p1 + np.outer(t, p2 - p1))
    k = max(1, math.ceil(math.sqrt(obj.n_seeds)))
    plane = pv.Plane(center=tuple(obj.point1), direction=_unit(obj.normal), i_size=obj.size, j_size=obj.size,
                     i_resolution=max(1, k - 1), j_resolution=max(1, k - 1))
    pts = np.asarray(plane.points)[: obj.n_seeds] if k > 1 else np.asarray([obj.point1], dtype=float)
    return pv.PolyData(pts)


def streamline_geometry(points: pv.UnstructuredGrid, obj) -> pv.PolyData:
    """Streamlines of U from the seeds, ``obj.direction``, at most ``obj.max_length`` metres long each way (steps in
    cell lengths, the default Runge-Kutta 4-5).

    Raises:
        ValueError: the results have no U.
    """
    if "U" not in points.point_data:
        raise ValueError("no velocity field U in the results")
    lines = points.streamlines_from_source(seed_points(obj), vectors="U", integration_direction=obj.direction,
                                           max_length=float(obj.max_length), max_steps=20_000,
                                           initial_step_length=0.2, max_step_length=0.5)
    return lines


def object_geometry(points: pv.UnstructuredGrid, obj, u_ref: float, direction=(1.0, 0.0, 0.0)):
    """The dataset of any scene object."""
    if obj.kind == "clip":
        return clip_geometry(points, obj)
    if obj.kind == "isosurface":
        return iso_geometry(points, obj, u_ref, direction)
    return streamline_geometry(points, obj)
