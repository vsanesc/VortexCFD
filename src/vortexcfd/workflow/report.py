"""The HTML report of a project (D-134, Qt-free): one self-contained file (styles inline, images embedded as base64
PNG, no external link needed) written to <project>/reports/<timestamp>.html.

Sections: the project and its set-up; the geometry; the mesh report (cells, quality, layers, the first cell and y+);
the convergence (a residual plot and the stop reason); the force or internal-flow reports as windowed means; the mesh
study's GCI table and the polar sweep's table and plot (D-136); the line plots (D-136); the saved views as images
(rendered by the caller, which has the viewer: ``ReportImage``). A section with no data is left out with a one-line
note; a section the user left out (``Simulation.results.report_omit``, D-136) is not in the file at all. Every number
comes from the project, its records or its case files: nothing is estimated.
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
    REPORT_SECTIONS,
    MeanStableCriterion,
)
from vortexcfd.core.labels import value_label
from vortexcfd.core.project import Project
from vortexcfd.core.reports import FLOW_QUANTITIES, FLOW_QUANTITY_LABELS, report_label
from vortexcfd.workflow import flow_numbers
from vortexcfd.foam.convergence import window_stats
from vortexcfd.foam.logparse import parse_log_text
from vortexcfd.foam import mesh_study, polar_sweep
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
    key: str = ""  # its id in core.model.REPORT_SECTIONS


def case_dir(project: Project) -> Path | None:
    return project.folder / "case" if project.path is not None else None


# -- the sections ------------------------------------------------------------------------------------


def project_section(project: Project) -> Section:
    sim = project.sim
    rows = [("Project", sim.name), ("File", str(project.path) if project.path else "not saved"),
            ("Analysis", f"{ANALYSIS_TYPE_LABELS[sim.analysis_type]}, {DIMENSION_LABELS[sim.dimension]}"),
            ("Preset", sim.preset_name or "none"),
            ("Flow", f"{value_label('flow', sim.physics.flow)} RANS, "
                     f"{value_label('turbulence_model', sim.physics.turbulence_model)}"),
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
                  else f"auto ({value_label('reference_area_basis', sim.reports.reference_area_basis).lower()})")]
    numbers = flow_numbers.project_numbers(project, flow_numbers.run_report_values(project))  # D-168
    if numbers is not None:
        rows += [("Reynolds number", numbers.reynolds_text()),
                 ("Mach number", numbers.mach_text(sim.physics.speed_of_sound)
                  + (f". {numbers.warning}" if numbers.warning else ""))]
    stop = sim.solvers.stopping
    rows += [("Iteration limit", str(sim.solvers.iterations)), ("Solver cores", str(sim.solvers.cores)),
             ("Stopping criteria", "; ".join(_criterion_text(c) for c in stop.criteria) or "none"),
             ("Criteria combined", value_label("combine", stop.combine))]
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
        body += _pairs([("Mass imbalance at the last iteration", f"{balance[2]:.3g} % of the inlet flux")])
    return Section(title, body)


def study_section(project: Project) -> Section:
    """The mesh study's table (D-066): each quantity's value per level, the convergence, the order, the extrapolated
    value and the GCI, or why there is no GCI (D-136)."""
    record = mesh_study.read_record(project.folder / mesh_study.STUDY_DIR_NAME) if project.path is not None else None
    if record is None:
        return Section("Mesh independence study", None, "No mesh independence study has been run.")
    levels = [lv.name for lv in record.levels]
    rows = [("Status", record.status), ("Refinement ratio", f"{record.ratio:.4g}"),
            ("Current settings as", record.current_as)]
    rows += [(f"Level {lv.name}", f"{_num(lv.cells, '{:,}')} cells, h {_num(lv.h, '{:.4g} m')}, "
              f"{lv.state_label or 'not run'}") for lv in record.levels]
    body = _pairs(rows)
    table = []
    for row in mesh_study.quantity_rows(record):
        r = row.result
        gci_text = (f"{100 * r.gci_fine:.3g} %" if r is not None and r.applicable else
                    (r.text if r is not None else "not applicable"))
        table.append([report_label(row.quantity), *(_num(v, "{:.6g}") for v in row.values),
                      r.convergence if r else "—", _num(r.order if r else None, "{:.3g}"),
                      _num(r.extrapolated if r else None, "{:.6g}"), gci_text, row.note or "—"])
    if table:
        body += "<h3>Grid convergence (Celik et al. 2008)</h3>" + _table(
            ["Quantity", *levels, "Convergence", "Order p", "Extrapolated", "GCI fine", "Note"], table)
    if record.dimensions == 3:
        body += _note("A 3D study's levels do not refine the near field by the level ratio (D-127, Proposed): its "
                      "GCI covers the wall cells and the background and is indicative.")
    return Section("Mesh independence study", body)


def polar_png(points) -> bytes | None:
    """CL, CD and CM against the angle of attack (flagged points hollow) as PNG; None without a value."""
    done = [p for p in points if p.cl is not None or p.cd is not None or p.cm is not None]
    if not done:
        return None
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(9, 3.2), dpi=100)
    FigureCanvasAgg(fig)
    for i, (attr, label) in enumerate((("cl", "CL"), ("cd", "CD"), ("cm", "CM pitch"))):
        ax = fig.add_subplot(1, 3, i + 1)
        pts = [(p.alpha, getattr(p, attr), p.flagged) for p in done if getattr(p, attr) is not None]
        ax.plot([a for a, _v, _f in pts], [v for _a, v, _f in pts], color="#2f6fdb", lw=1.2)
        for a, v, flagged in pts:
            ax.plot([a], [v], "o", color="#2f6fdb", mfc="white" if flagged else "#2f6fdb", ms=5)
        ax.set_xlabel("Angle of attack [deg]", fontsize=8)
        ax.set_ylabel(label, fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def sweep_section(project: Project) -> Section:
    """The polar sweep (D-067, D-120): CL, CD, CM and L/D per angle, and their plot (D-136)."""
    record = polar_sweep.read_record(project.folder / polar_sweep.SWEEP_DIR_NAME) if project.path is not None else None
    if record is None:
        return Section("Polar sweep", None, "No polar sweep has been run.")
    rows = [[f"{p.alpha:g}", _num(p.cl, "{:.5g}"), _num(p.cd, "{:.5g}"), _num(p.cm, "{:.5g}"),
             _num(p.lift_to_drag, "{:.4g}"), _num(p.iterations, "{}"), p.state_label or "not run",
             _num(p.cells, "{:,}")] for p in record.points]
    body = _pairs([("Status", record.status), ("Angles", ", ".join(f"{a:g}" for a in record.alphas) + " deg")])
    body += _table(["Angle (deg)", "CL", "CD", "CM pitch", "L/D", "Iterations", "Stop", "Cells"], rows)
    if any(p.flagged for p in record.points):
        body += _note("Points that did not meet their stopping criteria are drawn hollow.")
    png = polar_png(record.points)
    if png is not None:
        body += f"<figure>{_img(png, 'polar')}<figcaption>CL, CD and CM pitch against the angle of attack (last iteration of each point)</figcaption></figure>"
    return Section("Polar sweep", body)


def line_plots_section(project: Project, points=None) -> Section:
    """Each line plot's chart (D-136) from the latest results; ``points``: the internal mesh with point fields
    (read from the case when None)."""
    from vortexcfd.foam.physics_case import flow_direction
    from vortexcfd.workflow import line_plot
    from vortexcfd.workflow.meshing import flow_speed

    plots = [o for o in project.sim.results.objects if o.kind == "line_plot"]
    if not plots:
        return Section("Line plots", None, "No line plots (Results > Line plot).")
    case = case_dir(project)
    if points is None and case is not None and case.is_dir():
        try:
            points = line_plot.case_points(case)
        except (OSError, RuntimeError, ValueError):
            points = None
    if points is None:
        return Section("Line plots", None, "No solver results.")
    parts = []
    for obj in plots:
        head = (f"{obj.name}: from ({', '.join(f'{v:.4g}' for v in obj.point1)}) to "
                f"({', '.join(f'{v:.4g}' for v in obj.point2)}) m, {obj.n_samples} samples")
        try:
            samples = line_plot.sample_line(points, obj, flow_speed(project), flow_direction())
        except ValueError as exc:
            parts.append(_note(f"{head}: {exc}."))
            continue
        figure = _img(line_plot.png_bytes(samples, obj.name), obj.name)
        extra = f" ({samples.inside} of {obj.n_samples} samples inside the fluid)" if samples.inside < obj.n_samples else ""
        parts.append(f"<figure>{figure}<figcaption>{_e(head + extra)}</figcaption></figure>")
    return Section("Line plots", "\n".join(parts))


def views_section(images: list[ReportImage]) -> Section:
    if not images:
        return Section("Saved views", None, "No saved views (Results > Save view).")
    body = "\n".join(f"<figure>{_img(i.png, i.title)}<figcaption>{_e(i.title)}</figcaption></figure>" for i in images)
    return Section("Saved views", body)


# -- the document ------------------------------------------------------------------------------------

SECTION_BUILDERS = {
    "setup": project_section, "geometry": geometry_section, "mesh": mesh_section, "convergence": convergence_section,
    "reports": reports_section, "study": study_section, "sweep": sweep_section, "line_plots": line_plots_section,
}
assert tuple(SECTION_BUILDERS) + ("comparison", "views") == tuple(REPORT_SECTIONS)


def comparison_section(snaps) -> Section:
    """The runs compared in the Compare tab (D-149): the values with their differences to the first snapshot, the
    set-up differences and the residual and first report overlays."""
    from vortexcfd.workflow import snapshots as snapshot_module

    if not snaps or len(snaps) < 2:
        return Section("Comparison", None, "Choose two or more runs in the Compare tab to compare them here.")
    labels = [s.label for s in snaps]
    rows = []
    for r in snapshot_module.value_rows(snaps):
        cells = [r.label, r.kind, *(_num(v) for v in r.values)]
        for i in range(1, len(snaps)):
            rel = r.relative(i)
            cells += [_num(r.absolute(i)), "—" if rel is None else f"{100 * rel:+.3g} %"]
        rows.append(cells)
    header = ["Quantity", "Value", *labels]
    for label in labels[1:]:
        header += [f"{label} − {labels[0]}", "relative"]
    body = _table(header, rows, numeric_from=2) if rows else _note("No report values to compare.")
    setup = snapshot_module.setup_rows(snaps)
    body += "<h3>Set-up differences</h3>" + (_table(["Input", *labels], [[k, *v] for k, v in setup], numeric_from=99)
                                            if setup else _note("The runs have the same set-up."))
    for choice, title in snapshot_module.plot_choices(snaps)[:2]:
        body += f"<figure>{_img(snapshot_module.png_bytes(snaps, choice), title)}<figcaption>{_e(title)}</figcaption></figure>"
    return Section("Comparison", body)


def build_report(project: Project, images: list[ReportImage] | None = None, now: datetime | None = None,
                 omit: list[str] | None = None, comparison=None) -> str:
    """The HTML text of the report; ``omit``: the section ids left out (default the project's choice, D-136);
    ``comparison``: the snapshots chosen in the Compare tab (D-149; the section only with two or more)."""
    now = now or datetime.now()
    omit = set(project.sim.results.report_omit if omit is None else omit)
    sections = []
    for key in REPORT_SECTIONS:
        if key in omit:
            continue
        if key == "comparison":
            if not comparison or len(comparison) < 2:  # only when runs are chosen in the Compare tab
                continue
            section = comparison_section(comparison)
        else:
            section = views_section(images or []) if key == "views" else SECTION_BUILDERS[key](project)
        section.key = key
        sections.append(section)
    parts = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
             f"<title>{_e(project.sim.name)}: report</title><style>{STYLE}</style></head><body>",
             f"<h1>{_e(project.sim.name)}</h1>", _note(f"VortexCFD report, {now:%Y-%m-%d %H:%M}")]
    for section in sections:
        parts.append(f"<h2>{_e(section.title)}</h2>")
        parts.append(section.body if section.body is not None else _note(section.note))
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def write_report(project: Project, images: list[ReportImage] | None = None, now: datetime | None = None,
                 omit: list[str] | None = None, comparison=None) -> Path:
    """Write the report to <project>/reports/<timestamp>.html and return the path.

    Raises:
        ValueError: the project is not saved.
    """
    if project.path is None:
        raise ValueError("Save the project first: the report is written next to it.")
    now = now or datetime.now()
    path = project.folder / REPORTS_DIR / f"{now:%Y%m%d_%H%M%S}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, build_report(project, images, now, omit, comparison))
    return path
