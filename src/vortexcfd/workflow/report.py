"""The HTML report of a project (D-134, Qt-free): one self-contained file (styles inline, images embedded as base64
PNG, no external link needed) written to <project>/reports/<timestamp>.html.

Sections: the project and its set-up; the geometry; the mesh report (cells, quality, layers, the first cell and y+);
the convergence (a residual plot and the stop reason); the force or internal-flow reports as windowed means; the
saved views as images (rendered by the caller, which has the viewer: ``ReportImage``). A section with no data is left
out with a one-line note; every number comes from the project, its records or its case files: nothing is estimated.
"""

import base64
import html
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vortexcfd.core.atomic_io import write_text_atomic
from vortexcfd.core.model import (
    ANALYSIS_TYPE_LABELS,
    DIMENSION_LABELS,
    INLET_KIND_LABELS,
    PATCH_ROLE_LABELS,
    MeanStableCriterion,
)
from vortexcfd.core.project import Project
from vortexcfd.core.reports import FLOW_QUANTITIES, FLOW_QUANTITY_LABELS, report_label
from vortexcfd.foam.convergence import window_stats
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam.mesh_record import read_mesh_record
from vortexcfd.foam.postprocessing import ReportMonitor
from vortexcfd.foam.residuals import ResidualHistory
from vortexcfd.foam.run_record import read_run_record

REPORTS_DIR = "reports"
SOLVER_LOG = "log.simpleFoam"
STYLE = """
body { font-family: Helvetica, Arial, sans-serif; margin: 2em auto; max-width: 960px; color: #1d2330; line-height: 1.45; }
h1 { font-size: 1.6em; margin-bottom: 0.2em; } h2 { font-size: 1.2em; border-bottom: 1px solid #ccd; padding-bottom: 0.2em; margin-top: 1.8em; }
table { border-collapse: collapse; margin: 0.6em 0; font-size: 0.92em; }
th, td { border: 1px solid #d5d9e2; padding: 0.25em 0.6em; text-align: left; } th { background: #f0f2f6; }
td.num { text-align: right; font-family: Menlo, Consolas, monospace; }
p.note { color: #6a7286; font-style: italic; } figure { margin: 1em 0; } img { max-width: 100%; border: 1px solid #d5d9e2; }
figcaption { color: #6a7286; font-size: 0.9em; }
"""


@dataclass(frozen=True)
class ReportImage:
    """An image of a saved view (PNG bytes) and its caption."""

    title: str
    png: bytes


def _e(value) -> str:
    return html.escape(str(value))


def _num(value, fmt: str = "{:.5g}") -> str:
    return "—" if value is None else fmt.format(value)


def _table(header: list[str], rows: list[list], numeric_from: int = 1) -> str:
    out = ["<table><tr>" + "".join(f"<th>{_e(h)}</th>" for h in header) + "</tr>"]
    for row in rows:
        cells = "".join(f'<td class="num">{_e(c)}</td>' if i >= numeric_from else f"<td>{_e(c)}</td>"
                        for i, c in enumerate(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "\n".join(out)


def _pairs(rows: list[tuple[str, str]]) -> str:
    return _table(["Item", "Value"], [list(r) for r in rows], numeric_from=2)


def _img(png: bytes, alt: str) -> str:
    return f'<img alt="{_e(alt)}" src="data:image/png;base64,{base64.b64encode(png).decode("ascii")}">'


def _note(text: str) -> str:
    return f'<p class="note">{_e(text)}</p>'


@dataclass
class Section:
    title: str
    body: str | None  # None: no data
    note: str = ""  # the one line shown when there is no data


def case_dir(project: Project) -> Path | None:
    return project.folder / "case" if project.path is not None else None


# -- the sections ------------------------------------------------------------------------------------


def project_section(project: Project) -> Section:
    sim = project.sim
    rows = [("Project", sim.name), ("File", str(project.path) if project.path else "not saved"),
            ("Analysis", f"{ANALYSIS_TYPE_LABELS[sim.analysis_type]}, {DIMENSION_LABELS[sim.dimension]}"),
            ("Preset", sim.preset_name or "none"),
            ("Flow", f"steady incompressible RANS, {sim.physics.turbulence_model}"),
            ("Kinematic viscosity", f"{sim.physics.nu:.6g} m²/s"),
            ("Reference density", f"{sim.physics.rho_ref:.6g} kg/m³")]
    if sim.internal:
        rows.append(("Reference length", f"{sim.reports.reference_length:.6g} m" if sim.reports.reference_length
                     else "auto (the first inlet's hydraulic diameter)"))
    else:
        rows += [("Free-stream speed", f"{sim.inflow.speed:.6g} m/s"), ("Angle of attack", f"{sim.inflow.alpha_deg:g} deg"),
                 ("Turbulence intensity", f"{100 * sim.inflow.turbulence_intensity:.4g} %"),
                 ("Reference length", f"{sim.reports.reference_length:.6g} m" if sim.reports.reference_length else "auto"),
                 ("Reference area", f"{sim.reports.reference_area:.6g} m²" if sim.reports.reference_area
                  else f"auto ({sim.reports.reference_area_basis})")]
    stop = sim.solvers.stopping
    rows += [("Iteration limit", str(sim.solvers.iterations)), ("Solver cores", str(sim.solvers.cores)),
             ("Stopping criteria", "; ".join(_criterion_text(c) for c in stop.criteria) or "none"),
             ("Criteria combined", stop.combine)]
    body = _pairs(rows)
    if sim.internal and sim.boundaries:
        brows = []
        for b in sim.boundaries:
            if b.role == "inlet":
                value = {"velocity": f"{b.inlet.speed:.6g} m/s", "mass_flow": f"{b.inlet.mass_flow:.6g} kg/s",
                         "total_pressure": f"{b.inlet.total_pressure:.6g} Pa"}[b.inlet.kind]
                kind = INLET_KIND_LABELS[b.inlet.kind]
                extra = f"intensity {100 * b.inlet.turbulence_intensity:.4g} %, length scale " + (
                    f"{b.inlet.length_scale:.4g} m" if b.inlet.length_scale else "auto (0.07 D_h)")
            elif b.role == "outlet":
                value, kind, extra = f"{b.outlet.pressure:.6g} Pa", "Static-pressure outlet", ""
            else:
                value, kind, extra = "", "Wall", ""
            brows.append([b.patch, PATCH_ROLE_LABELS[b.role], kind, value, extra])
        body += "<h3>Boundaries</h3>" + _table(["Patch", "Role", "Type", "Value", "Turbulence"], brows, numeric_from=5)
    return Section("Project and set-up", body)


def _criterion_text(c) -> str:
    if c.kind == "residual":
        return f"{c.field} residual below {c.threshold:g}"
    what = "mean stable" if isinstance(c, MeanStableCriterion) else "asymptotic"
    return f"{report_label(c.quantity)} {what} over {c.window} iterations within {100 * c.tolerance:.3g} %"


def geometry_section(project: Project) -> Section:
    sim = project.sim
    if not sim.geometry.parts:
        return Section("Geometry", None, "No part has been imported.")
    rows = []
    for part in sim.geometry.parts:
        source = part.cad.file if part.cad else (part.section.file if part.section else part.source_file)
        rows.append([part.name, source, part.units, str(len(part.regions) or 1), ", ".join(part.patch_names())])
    body = _table(["Part", "File", "Units", "Regions", "Patches"], rows, numeric_from=5)
    prep = sim.surface_prep
    lines = [("Surface preparation", prep.strategy.replace("_", " ") if prep else "not run")]
    if prep is not None:
        lines += [(label, value) for label, value in prep.report]
    if sim.refinement_volumes:
        lines.append(("Refinement volumes", ", ".join(f"{v.name} ({v.shape.kind}, {v.target_size:.4g} m)"
                                                      for v in sim.refinement_volumes)))
    body += "<h3>Preparation</h3>" + _pairs(lines)
    return Section("Geometry", body)


def mesh_section(project: Project) -> Section:
    case = case_dir(project)
    record = read_mesh_record(case) if case is not None else None
    if record is None or record.report is None:
        return Section("Mesh report", None, "No mesh has been generated.")
    from vortexcfd.workflow.meshing import inputs_hash

    r = record.report
    rows = [("Cells", _num(r.cells, "{:,}")), ("Faces", _num(r.faces, "{:,}")), ("Points", _num(r.points, "{:,}")),
            ("checkMesh", "Mesh OK" if r.mesh_ok else f"{r.failed_checks} failed checks"),
            ("Max non-orthogonality", _num(r.max_non_orthogonality, "{:.4g} deg")),
            ("Average non-orthogonality", _num(r.avg_non_orthogonality, "{:.4g} deg")),
            ("Max skewness", _num(r.max_skewness, "{:.4g}")),
            ("Faces with layers", _num(r.extruded_percent, "{:.4g} %")),
            ("Meshing cores", str(record.cores)),
            ("Up to date", "yes" if record.inputs_hash == inputs_hash(project) else "no: the settings changed since")]
    if r.first_cell is not None and r.first_cell.mean_m is not None:
        fc = r.first_cell
        rows += [("First cell (mean, area-weighted)", f"{fc.mean_m:.4g} m"), ("First cell (95th percentile)", _num(fc.p95_m, "{:.4g} m")),
                 ("First cell planned", _num(fc.planned_m, "{:.4g} m")),
                 ("Wall above twice the plan", _num(None if fc.share_over_2x is None else 100 * fc.share_over_2x, "{:.3g} %"))]
    body = _pairs(rows)
    for line in r.failed_check_lines:
        body += _note(f"checkMesh: {line}")
    if r.layers:
        body += "<h3>Layer coverage</h3>" + _table(
            ["Patch", "Faces", "Target layers", "Mesh layers", "Thickness (% of target)"],
            [[c.patch, f"{c.faces:,}", c.target_layers, f"{c.mesh_layers:.3g}", f"{c.thickness_percent:.3g}"] for c in r.layers])
    yplus = _yplus_rows(project)
    if yplus:
        body += "<h3>y+ on the walls</h3>" + _pairs(yplus)
    return Section("Mesh report", body)


def _yplus_rows(project: Project) -> list[tuple[str, str]]:
    case = case_dir(project)
    if case is None or not (case / "postProcessing").is_dir():
        return []
    monitor = ReportMonitor(case)
    monitor.poll()
    rows = []
    for rid, label in (("yplus_min", "min"), ("yplus_avg", "average (face-weighted)"), ("yplus_max", "max")):
        series = monitor.series(rid)
        if series:
            rows.append((f"y+ {label} at iteration {series[-1][0]:g}", f"{series[-1][1]:.4g}"))
    return rows


def residual_png(text: str) -> bytes | None:
    """The initial residual of every field per iteration (log scale) from a solver log, as PNG; None without data."""
    history = ResidualHistory()
    history.extend(parse_log_text(text).time_steps)
    if not history.series:
        return None
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8, 3.6), dpi=100)
    ax = fig.add_subplot(111)
    for name, points in history.decimated().items():
        ax.semilogy([p[0] for p in points], [p[1] for p in points], lw=1.0, label=name)
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Initial residual")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def convergence_section(project: Project) -> Section:
    case = case_dir(project)
    record = read_run_record(case) if case is not None else None
    if record is None:
        return Section("Convergence", None, "The solver has not been run.")
    from vortexcfd.workflow.solving import results_hash

    rows = [("Stop reason", record.label), ("Iterations", str(record.iterations)),
            ("Criteria met at iteration", _num(record.met_iteration, "{}")),
            ("Stopped by", "; ".join(record.stopped_by) or "—"),
            ("Final residuals", ", ".join(f"{k} {v:.3g}" for k, v in record.final_residuals.items()) or "—"),
            ("Solver time", _num(record.duration_s, "{:.0f} s") + f" on {record.cores} cores"),
            ("Up to date", "yes" if record.inputs_hash == results_hash(project) else "no: the set-up changed since")]
    if record.switch_iteration is not None:
        rows.append(("Turbulence stage 2 from iteration", str(record.switch_iteration)))
    body = _pairs(rows)
    log = case / SOLVER_LOG
    png = residual_png(log.read_text(errors="replace")) if log.is_file() else None
    body += (f"<figure>{_img(png, 'residuals')}<figcaption>Initial residuals per iteration ({SOLVER_LOG})</figcaption></figure>"
             if png is not None else _note("No solver log: no residual plot."))
    return Section("Convergence", body)


def _window(project: Project, report_id: str) -> int:
    stop = project.sim.solvers.stopping
    return next((c.window for c in stop.criteria if isinstance(c, MeanStableCriterion) and c.quantity == report_id),
                stop.oscillation_window)


def _mean_text(series, window: int) -> tuple[str, str]:
    stats = window_stats(series, window)
    if stats is None:
        return "—", "—"
    spread = "" if stats.amplitude is None else f"{50 * stats.amplitude:.2g} %"
    return f"{stats.mean:.6g}", f"±{spread} over {stats.n}" if spread else f"over {stats.n}"


def reports_section(project: Project) -> Section:
    case = case_dir(project)
    title = "Internal-flow reports" if project.sim.internal else "Forces"
    if case is None or not (case / "postProcessing").is_dir():
        return Section(title, None, "No solver results.")
    monitor = ReportMonitor(case)
    monitor.poll()
    rows = []
    if project.sim.internal:
        for kind, name in monitor.internal_locations():
            for q in FLOW_QUANTITIES:
                rid = f"flow:{q}:{kind}:{name}"
                series = monitor.series(rid)
                if series:
                    rows.append([f"{kind} {name}", FLOW_QUANTITY_LABELS[q], *_mean_text(series, _window(project, rid))])
        for drop in project.sim.reports.pressure_drops:
            for k in ("static", "total"):
                rid = f"dp:{drop.name}:{k}"
                series = monitor.series(rid)
                if series:
                    rows.append([f"drop {drop.name}", f"dp {k} (Pa)", *_mean_text(series, _window(project, rid))])
        balance = monitor.mass_balance()
    else:
        keys = [None, *monitor.part_keys()]
        for key in keys:
            for base in ("Cd", "Cl", "CmPitch", "Cd_pressure", "Cd_viscous"):
                rid = base if key is None else f"{base}@{key}"
                series = monitor.series(rid)
                if series:
                    rows.append(["All walls" if key is None else key, report_label(base),
                                 *_mean_text(series, _window(project, rid))])
        balance = monitor.mass_balance()
    if not rows:
        return Section(title, None, "The run wrote no report data.")
    body = _table(["Where", "Quantity", "Windowed mean", "Half range (share of the mean) over iterations"], rows,
                  numeric_from=2)
    body += _note("Means over the last iterations: the window of a mean-stable criterion on the quantity, else the "
                  "oscillation window of the stopping criteria (D-118, D-119).")
    if balance is not None and balance[2] is not None:
        body += _pairs([("Mass imbalance at the last iteration", f"{balance[2]:.3g} % of the inflow")])
    return Section(title, body)


def views_section(images: list[ReportImage]) -> Section:
    if not images:
        return Section("Saved views", None, "No saved views (Results > Save view).")
    body = "\n".join(f"<figure>{_img(i.png, i.title)}<figcaption>{_e(i.title)}</figcaption></figure>" for i in images)
    return Section("Saved views", body)


# -- the document ------------------------------------------------------------------------------------


def build_report(project: Project, images: list[ReportImage] | None = None, now: datetime | None = None) -> str:
    """The HTML text of the report."""
    now = now or datetime.now()
    sections = [project_section(project), geometry_section(project), mesh_section(project),
                convergence_section(project), reports_section(project), views_section(images or [])]
    parts = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
             f"<title>{_e(project.sim.name)}: report</title><style>{STYLE}</style></head><body>",
             f"<h1>{_e(project.sim.name)}</h1>", _note(f"VortexCFD report, {now:%Y-%m-%d %H:%M}")]
    for section in sections:
        parts.append(f"<h2>{_e(section.title)}</h2>")
        parts.append(section.body if section.body is not None else _note(section.note))
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def write_report(project: Project, images: list[ReportImage] | None = None, now: datetime | None = None) -> Path:
    """Write the report to <project>/reports/<timestamp>.html and return the path.

    Raises:
        ValueError: the project is not saved.
    """
    if project.path is None:
        raise ValueError("Save the project first: the report is written next to it.")
    now = now or datetime.now()
    path = project.folder / REPORTS_DIR / f"{now:%Y%m%d_%H%M%S}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, build_report(project, images, now))
    return path
