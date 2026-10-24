"""Line plots of the results (D-136, no Qt): fields sampled at evenly spaced points along a line through the fluid
volume, their chart (matplotlib, drawn into any Figure: the GUI's embedded canvas or the report's Agg PNG) and the
CSV export.

The samples are interpolated from the point fields of the latest results' internal mesh (the cell values averaged to
the points, as the other scene objects, D-132); a sample outside the fluid has no value (NaN, a gap in the chart and
an empty CSV cell).
"""

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv

from vortexcfd.foam.results import FIELDS_BY_KEY, field_values, latest_result_time

VALID_MASK = "vtkValidPointMask"
CSV_HEADER_START = ["distance_m", "x_m", "y_m", "z_m"]


@dataclass(frozen=True)
class LineSamples:
    """The samples of one line plot: the distance from the first point (m), the positions (n x 3) and the values of
    each requested field the results have (key -> n values, NaN outside the fluid)."""

    distance: np.ndarray
    positions: np.ndarray
    values: dict[str, np.ndarray]
    missing: tuple[str, ...] = ()  # requested fields the results do not have

    @property
    def inside(self) -> int:
        """The number of samples inside the fluid."""
        if not self.values:
            return 0
        return int(np.sum(np.isfinite(next(iter(self.values.values())))))


def sample_line(points: pv.UnstructuredGrid, obj, u_ref: float, direction=(1.0, 0.0, 0.0)) -> LineSamples:
    """Sample ``obj`` (core.model.LinePlotObject) on ``points`` (workflow/results_objects.point_fields).

    Raises:
        ValueError: none of the fields is in the results, or the whole line is outside the fluid.
    """
    p1, p2 = np.asarray(obj.point1, dtype=float), np.asarray(obj.point2, dtype=float)
    line = pv.Line(tuple(p1), tuple(p2), resolution=obj.n_samples - 1)
    sampled = line.sample(points)
    valid = np.asarray(sampled.point_data[VALID_MASK]).astype(bool)
    positions = np.asarray(line.points, dtype=float)
    distance = np.linalg.norm(positions - p1, axis=1)
    values, missing = {}, []
    for key in obj.fields:
        spec = FIELDS_BY_KEY.get(key)
        if spec is None or spec.source not in sampled.point_data:
            missing.append(key)
            continue
        v = np.asarray(field_values(spec, {spec.source: sampled.point_data[spec.source]}, u_ref, direction), dtype=float)
        values[key] = np.where(valid, v, np.nan)
    if not values:
        raise ValueError("none of the line's fields is in the results")
    if not valid.any():
        raise ValueError("the line is outside the fluid")
    return LineSamples(distance, positions, values, tuple(missing))


def case_points(case_dir: Path) -> pv.UnstructuredGrid | None:
    """The internal mesh of the latest results of ``case_dir`` with point fields (None without results)."""
    from vortexcfd.workflow.results_objects import point_fields

    case_dir = Path(case_dir)
    time = latest_result_time(case_dir)
    if time is None:
        return None
    foam = case_dir / "case.foam"
    foam.touch(exist_ok=True)
    reader = pv.OpenFOAMReader(str(foam))
    reader.set_active_time_value(float(time))
    blocks = reader.read()
    if "internalMesh" not in blocks.keys():
        return None
    return point_fields(blocks["internalMesh"])


def draw(figure, samples: LineSamples, title: str = "") -> None:
    """The chart of ``samples`` in a matplotlib ``figure`` (cleared first): one axes per field, against the distance
    along the line."""
    from vortexcfd.workflow import plot_axes

    figure.clear()
    keys = list(samples.values)
    axes = figure.subplots(len(keys), 1, sharex=True, squeeze=False)[:, 0]
    for ax, key in zip(axes, keys):
        spec = FIELDS_BY_KEY[key]
        ax.plot(samples.distance, samples.values[key], lw=1.4, color="#2f6fdb")
        ax.set_ylabel(spec.title, fontsize=8)
        plot_axes.apply(ax, target=5)  # the distance and the field's ticks, a light grid (D-169)
        ax.tick_params(labelsize=8)
    axes[-1].set_xlabel("Distance along the line [m]", fontsize=8)
    if title:
        axes[0].set_title(title, fontsize=9)
    figure.tight_layout()


def png_bytes(samples: LineSamples, title: str = "", size_in=(8.0, 3.2), dpi: int = 100) -> bytes:
    """The chart as PNG bytes (rendered with matplotlib's Agg canvas, no display)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    height = size_in[1] * max(1, len(samples.values)) ** 0.8
    figure = Figure(figsize=(size_in[0], height), dpi=dpi)
    FigureCanvasAgg(figure)
    draw(figure, samples, title)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue()


def write_png(samples: LineSamples, path: Path, title: str = "") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(samples, title, dpi=150))


def write_csv(samples: LineSamples, path: Path) -> None:
    """One row per sample: the distance, the position and every field (empty outside the fluid)."""
    def num(v: float) -> str:
        return "" if not math.isfinite(v) else repr(float(v))

    keys = list(samples.values)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER_START + [FIELDS_BY_KEY[k].key for k in keys])
        for i in range(len(samples.distance)):
            writer.writerow([num(samples.distance[i]), *(num(c) for c in samples.positions[i]),
                             *(num(samples.values[k][i]) for k in keys)])
