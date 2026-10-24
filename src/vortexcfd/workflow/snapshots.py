"""Results snapshots and their comparison (D-149; Qt-free).

A snapshot keeps what is needed to compare runs after the case has been meshed or solved again: the residual
history, every report's history with its final value and windowed mean, the line plots' samples, the mesh summary
and the set-up summary (the key inputs, flattened to text). It is a JSON file in <project>/snapshots/ (the folder
carries a .gitignore: the snapshots are data, not sources). Snapshots of another project can be loaded read-only.

The comparison: the values table (each quantity's windowed mean, or final value, per snapshot with the absolute and
relative difference to the first one), the set-up differences (the inputs that differ), the overlaid plots and the
CSV / PNG exports.
"""

import csv
import io
import json
import math
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from vortexcfd.core.atomic_io import write_text_atomic
from vortexcfd.core.labels import setup_label, setup_value
from vortexcfd.core.model import DOMAIN_EXTENTS, MeanStableCriterion, Simulation
from vortexcfd.core.project import Project
from vortexcfd.core.project_io import load_simulation
from vortexcfd.core.reports import available_reports, report_label
from vortexcfd.foam.convergence import window_stats
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.mesh_record import read_mesh_record
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory, decimate
from vortexcfd.foam.run_record import read_run_record

SNAPSHOT_DIR = "snapshots"
FORMAT_VERSION = 1
SOLVER_LOG = "log.simpleFoam"
MAX_POINTS = 2000  # per series, decimated like the live chart (foam/residuals.decimate)
CURRENT_RUN = "Current run"


class SnapshotError(ValueError):
    """A snapshot cannot be made, saved or read; the message says why."""


@dataclass
class ReportData:
    """One report of a snapshot: its history, final value and windowed mean over ``window`` iterations."""

    label: str
    series: list[tuple[float, float]]
    final: float | None
    mean: float | None
    window: int


@dataclass
class LineData:
    """One line plot of a snapshot: the distance along the line (m) and each field's samples (None outside the
    fluid)."""

    title: str
    distance: list[float]
    fields: dict[str, list[float | None]]


@dataclass
class Snapshot:
    name: str
    created: str
    project: str
    source: str  # the project file it was taken from
    state: str = ""  # the run's end state (run record label)
    iterations: int = 0
    residuals: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    reports: dict[str, ReportData] = field(default_factory=dict)
    line_plots: dict[str, LineData] = field(default_factory=dict)
    mesh: dict[str, object] = field(default_factory=dict)
    setup: dict[str, str] = field(default_factory=dict)
    read_only: bool = False  # loaded from another project (never saved there)
    path: str | None = None  # where it is stored (None: the current run, not saved)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.project})" if self.read_only else self.name

    def to_json(self) -> str:
        data = asdict(self)
        data.pop("read_only")
        data.pop("path")
        data["format"] = FORMAT_VERSION
        return json.dumps(data, indent=1) + "\n"


# -- the set-up summary -------------------------------------------------------------------------------------


def _text(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_text(v) for v in value) + ")"
    if value is None:
        return "auto"
    return str(value)


def setup_summary(sim: Simulation) -> dict[str, str]:
    """The key inputs of a run, flattened to "group: field" -> text (the set-up differences compare these)."""
    out: dict[str, str] = {
        "analysis": f"{sim.analysis_type}, {sim.dimension}",
        "parts": ", ".join(f"{p.name} ({p.source_file}, {p.units})" for p in sim.geometry.parts) or "none",
    }
    for key, value in sim.physics.model_dump().items():
        out[f"physics: {key}"] = _text(value)
    if not sim.internal:
        for key, value in sim.inflow.model_dump().items():
            out[f"free stream: {key}"] = _text(value)
        domain = sim.domain.model_dump(exclude={"parts", "ground", "boundary_types", "units", "wall_layers"})
        for key, value in domain.items():
            unit = f" {sim.domain.extent_unit(key)}" if key in DOMAIN_EXTENTS else ""  # "5 L", "2 m" (D-157)
            out[f"domain: {key}"] = _text(value) + unit
        out["domain: ground"] = (f"on, {sim.domain.ground.motion}" if sim.domain.ground.enabled else "off")
        for face, kind in sorted(sim.domain.boundary_types.items()):
            out[f"domain: {face} type"] = kind
        from vortexcfd.workflow.meshing import wall_layer_faces

        for face in wall_layer_faces(sim.domain):  # only where written (D-161): older snapshots compare as before
            out[f"domain: {face} prism layers"] = "on"
    for key, value in sim.mesh.model_dump().items():
        out[f"mesh: {key}"] = _text(value)
    for v in sim.refinement_volumes:
        out[f"refinement volume: {v.name}"] = (f"{v.shape.kind}, {v.target_size:.4g} m"
                                               + ("" if v.enabled else " (disabled)"))
    out["solver: iterations"] = str(sim.solvers.iterations)
    out["solver: stopping"] = "; ".join(f"{c.kind} {getattr(c, 'quantity', getattr(c, 'field', ''))}"
                                        for c in sim.solvers.stopping.criteria) or "none"
    rep = sim.reports
    out["reference: area"] = _text(rep.reference_area) + f" ({rep.reference_area_basis})"
    out["reference: length"] = _text(rep.reference_length)
    out["reference: CofR"] = _text(rep.center_of_rotation)
    for b in sim.boundaries:
        out[f"boundary: {b.patch}"] = _text(b.model_dump(exclude={"patch"}))
    return out


# -- capture ------------------------------------------------------------------------------------------------------


def _window(sim: Simulation, report_id: str) -> int:
    stop = sim.solvers.stopping
    return next((c.window for c in stop.criteria if isinstance(c, MeanStableCriterion) and c.quantity == report_id),
                stop.oscillation_window)


def _scalar_series(series) -> list[tuple[float, float]]:
    """(iteration, value) pairs with a finite scalar value (a probe's vector series is left out)."""
    return [(float(t), float(v)) for t, v in series if isinstance(v, (int, float)) and math.isfinite(v)]


def sample_line_plots(project: Project, points=None) -> dict:
    """Every line plot of the project (Results > Line plot) sampled on the latest results of its case, by line plot
    name (D-160); ``points``: the internal mesh with point fields, read from the case when None. A line plot that
    cannot be sampled (no field, or outside the fluid) is left out; no results: none."""
    from vortexcfd.core.model import LinePlotObject
    from vortexcfd.foam.physics_case import flow_direction
    from vortexcfd.workflow import line_plot
    from vortexcfd.workflow.meshing import flow_speed

    plots = [o for o in project.sim.results.objects if isinstance(o, LinePlotObject)]
    if not plots or project.folder is None:
        return {}
    if points is None:
        try:
            points = line_plot.case_points(project.folder / "case")
        except (OSError, RuntimeError, ValueError):
            return {}
    if points is None:
        return {}
    out = {}
    for obj in plots:
        try:
            out[obj.name] = line_plot.sample_line(points, obj, flow_speed(project), flow_direction())
        except ValueError:
            continue
    return out


def capture(project: Project, name: str, now: datetime | None = None, points=None) -> Snapshot:
    """The snapshot of the project's current run (its case folder): residuals, reports, every line plot sampled on
    the results (``sample_line_plots``; ``points`` passed on), the mesh and set-up summaries.

    Raises:
        SnapshotError: the project is not saved or its case has no solver run.
    """
    if project.path is None:
        raise SnapshotError("Save the project first.")
    case = project.folder / "case"
    record = read_run_record(case)
    log = case / SOLVER_LOG
    if record is None and not log.is_file():
        raise SnapshotError("The project has no solver run to keep: run the solver first.")
    sim = project.sim
    snap = Snapshot(name=name, created=(now or datetime.now()).isoformat(timespec="seconds"), project=sim.name,
                    source=str(project.path), state=record.label if record is not None else "",
                    iterations=record.iterations if record is not None else 0, setup=setup_summary(sim))
    if log.is_file():
        history = ResidualHistory()
        history.extend(parse_log_text(log.read_text(encoding="utf-8", errors="replace")).time_steps)
        snap.residuals = {k: [(float(t), float(v)) for t, v in decimate(points, MAX_POINTS)]
                          for k, points in history.series.items()}
    if (case / "postProcessing").is_dir():
        from vortexcfd.workflow.solving import report_scope

        monitor = ReportMonitor(case)
        monitor.poll()
        for report_id in available_reports(**report_scope(project)):
            try:
                series = _scalar_series(monitor.series(report_id))
            except KeyError:
                continue
            if not series:
                continue
            window = _window(sim, report_id)
            stats = window_stats(series, window, quantity=report_id)
            snap.reports[report_id] = ReportData(report_label(report_id), decimate(series, MAX_POINTS),
                                                 series[-1][1], stats.mean if stats is not None else None, window)
    mesh = read_mesh_record(case)
    if mesh is not None:
        r = mesh.report
        snap.mesh = {"cells": r.cells, "faces": r.faces, "points": r.points,
                     "max non-orthogonality": r.max_non_orthogonality, "max skewness": r.max_skewness,
                     "failed checks": r.failed_checks, "mesh OK": r.mesh_ok,
                     "surface faces with layers %": r.extruded_percent}
    for title, samples in sample_line_plots(project, points).items():
        snap.line_plots[title] = LineData(title, [float(d) for d in samples.distance],
                                          {k: [float(x) if math.isfinite(x) else None for x in v]
                                           for k, v in samples.values.items()})
    return snap


# -- storage --------------------------------------------------------------------------------------------------------


def snapshot_dir(project_folder: Path) -> Path:
    return Path(project_folder) / SNAPSHOT_DIR


def _file_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name.strip()) or "snapshot"
    return f"{safe}.json"


def save(project: Project, snap: Snapshot, overwrite: bool = False) -> Path:
    """Write ``snap`` to <project>/snapshots/<name>.json (the folder git-ignored).

    Raises:
        SnapshotError: no project folder, an empty name, or a snapshot of that name exists (without ``overwrite``).
    """
    if project.path is None:
        raise SnapshotError("Save the project first.")
    if not snap.name.strip():
        raise SnapshotError("Enter a snapshot name.")
    folder = snapshot_dir(project.folder)
    folder.mkdir(exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.is_file():
        ignore.write_text("# VortexCFD results snapshots (D-149): data, not sources\n*\n", encoding="utf-8")
    path = folder / _file_name(snap.name)
    if path.exists() and not overwrite:
        raise SnapshotError(f"A snapshot named '{snap.name}' exists.")
    write_text_atomic(path, snap.to_json())
    snap.path = str(path)
    return path


def load(path: Path, read_only: bool = False) -> Snapshot:
    """A snapshot file. Raises SnapshotError when it cannot be read."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.pop("format", None) != FORMAT_VERSION:
            raise ValueError("unknown snapshot format")
        reports = {k: ReportData(v["label"], [tuple(p) for p in v["series"]], v["final"], v["mean"], v["window"])
                   for k, v in data.pop("reports", {}).items()}
        lines = {k: LineData(v["title"], v["distance"], v["fields"]) for k, v in data.pop("line_plots", {}).items()}
        residuals = {k: [tuple(p) for p in v] for k, v in data.pop("residuals", {}).items()}
        snap = Snapshot(**data, reports=reports, line_plots=lines, residuals=residuals)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SnapshotError(f"{Path(path).name}: {exc}") from exc
    snap.read_only = read_only
    snap.path = str(path)
    return snap


def saved(project_folder: Path | None, read_only: bool = False) -> list[Snapshot]:
    """The snapshots stored in a project folder, oldest first (unreadable files left out)."""
    if project_folder is None:
        return []
    out = []
    for path in sorted(snapshot_dir(project_folder).glob("*.json")):
        try:
            out.append(load(path, read_only))
        except SnapshotError:
            continue
    return sorted(out, key=lambda s: s.created)


def from_project(vcfd: Path) -> list[Snapshot]:
    """The snapshots of another project (its .vcfd file), read-only; their project name is that project's."""
    vcfd = Path(vcfd)
    try:
        name = load_simulation(vcfd).name
    except Exception:  # an unreadable project: its snapshots still carry their project name
        name = vcfd.stem
    snaps = saved(vcfd.parent, read_only=True)
    for s in snaps:
        s.project = s.project or name
    return snaps


def delete(snap: Snapshot) -> None:
    if snap.read_only or snap.path is None:
        raise SnapshotError("Only this project's saved snapshots can be deleted.")
    Path(snap.path).unlink(missing_ok=True)


# -- comparison -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueRow:
    """One quantity across the snapshots: ``values`` the windowed mean (else the final value) per snapshot, None where
    a snapshot has none; the differences are to the first snapshot (the reference)."""

    report_id: str
    label: str
    values: tuple[float | None, ...]
    kind: str  # "windowed mean" or "final"

    def absolute(self, i: int) -> float | None:
        ref, v = self.values[0], self.values[i]
        return None if ref is None or v is None else v - ref

    def relative(self, i: int) -> float | None:
        diff, ref = self.absolute(i), self.values[0]
        return None if diff is None or not ref else diff / abs(ref)


def value_rows(snaps: list[Snapshot]) -> list[ValueRow]:
    """Every report any snapshot has, in the first appearance order; the mesh's cell count first."""
    rows = []
    if any("cells" in s.mesh for s in snaps):
        rows.append(ValueRow("mesh:cells", "Mesh cells", tuple(_float(s.mesh.get("cells")) for s in snaps), "final"))
    ids: list[str] = []
    for s in snaps:
        ids += [k for k in s.reports if k not in ids]
    for rid in ids:
        data = [s.reports.get(rid) for s in snaps]
        use_mean = all(d is None or d.mean is not None for d in data)
        values = tuple(None if d is None else (d.mean if use_mean else d.final) for d in data)
        label = next(d.label for d in data if d is not None)
        rows.append(ValueRow(rid, label, values, "windowed mean" if use_mean else "final"))
    return rows


def _float(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def setup_rows(snaps: list[Snapshot]) -> list[tuple[str, tuple[str, ...]]]:
    """The inputs whose values differ between the snapshots: (the input's label, the value in each; "—" where
    missing). The snapshots keep the model's identifiers; the rows show their labels (D-166)."""
    keys: list[str] = []
    for s in snaps:
        keys += [k for k in s.setup if k not in keys]
    out = []
    for key in keys:
        values = tuple(s.setup.get(key, "—") for s in snaps)
        if len(set(values)) > 1:
            out.append((setup_label(key), tuple(v if v == "—" else setup_value(key, v) for v in values)))
    return out


def _cell(v: float | None) -> str:
    return "" if v is None else repr(float(v))


def write_values_csv(snaps: list[Snapshot], path: Path) -> None:
    """The values table: per quantity the value of each snapshot, then the absolute and relative differences of the
    others to the first."""
    rows = value_rows(snaps)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        header = ["quantity", "value"] + [s.label for s in snaps]
        for s in snaps[1:]:
            header += [f"{s.label} - {snaps[0].label}", f"{s.label} vs {snaps[0].label} (relative)"]
        w.writerow(header)
        for r in rows:
            line = [r.label, r.kind] + [_cell(v) for v in r.values]
            for i in range(1, len(snaps)):
                line += [_cell(r.absolute(i)), _cell(r.relative(i))]
            w.writerow(line)


def write_setup_csv(snaps: list[Snapshot], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["input"] + [s.label for s in snaps])
        for key, values in setup_rows(snaps):
            w.writerow([key, *values])


# -- plots ---------------------------------------------------------------------------------------------------------


def plot_choices(snaps: list[Snapshot]) -> list[tuple[str, str]]:
    """(key, label) of every plot the snapshots can overlay: the residuals, each report history, each line plot
    field."""
    out = [("residuals", "Residuals")] if any(s.residuals for s in snaps) else []
    seen: list[str] = []
    for s in snaps:
        for rid, data in s.reports.items():
            if rid not in seen:
                seen.append(rid)
                out.append((f"report:{rid}", f"History: {data.label}"))
    lines: list[tuple[str, str]] = []
    for s in snaps:
        for title, line in s.line_plots.items():
            for key in line.fields:
                choice = (f"line:{title}:{key}", f"Line plot {title}: {key}")
                if choice not in lines:
                    lines.append(choice)
    return out + lines


def draw(figure, snaps: list[Snapshot], choice: str, colors: list[str] | None = None) -> None:
    """Overlay ``choice`` (a ``plot_choices`` key) of every snapshot in a matplotlib figure, one legend entry per
    snapshot (residuals: one colour per snapshot, a line style per field)."""
    figure.clear()
    ax = figure.add_subplot(111)
    colors = colors or [f"C{i}" for i in range(10)]
    styles = ["-", "--", ":", "-."]
    if choice == "residuals":
        for i, s in enumerate(snaps):
            for j, (fieldname, points) in enumerate(s.residuals.items()):
                ax.semilogy([p[0] for p in points], [p[1] for p in points], lw=1.0, color=colors[i % len(colors)],
                            ls=styles[j % len(styles)], label=f"{s.label}: {fieldname}")
        ax.set_xlabel("Iteration")
        ax.set_ylabel("Initial residual")
    elif choice.startswith("report:"):
        rid = choice.split(":", 1)[1]
        for i, s in enumerate(snaps):
            data = s.reports.get(rid)
            if data is not None:
                ax.plot([p[0] for p in data.series], [p[1] for p in data.series], lw=1.2,
                        color=colors[i % len(colors)], label=s.label)
        ax.set_xlabel("Iteration")
        ax.set_ylabel(report_label(rid))
    elif choice.startswith("line:"):
        _prefix, title, key = choice.split(":", 2)
        for i, s in enumerate(snaps):
            line = s.line_plots.get(title)
            if line is not None and key in line.fields:
                ys = [math.nan if v is None else v for v in line.fields[key]]
                ax.plot(line.distance, ys, lw=1.2, color=colors[i % len(colors)], label=s.label)
        ax.set_xlabel("Distance along the line [m]")
        ax.set_ylabel(key)
    ax.grid(alpha=0.3, which="both")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, ncol=2)
    with warnings.catch_warnings():  # a canvas too small for the margins keeps matplotlib's default layout
        warnings.simplefilter("ignore", UserWarning)
        figure.tight_layout()


def png_bytes(snaps: list[Snapshot], choice: str, size_in=(8.0, 4.0), dpi: int = 100) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=size_in, dpi=dpi)
    FigureCanvasAgg(figure)
    draw(figure, snaps, choice)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue()
