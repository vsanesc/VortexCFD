"""The Reynolds and Mach numbers of a project (D-168, Qt-free): what velocity and length they use, and the
compressibility warning.

External flow: Re = U∞ l_ref / ν and Ma = U∞ / a, with l_ref the Reference Values' (set, or the parts' x extent).
Internal flow: Re = U_bulk D_h / ν on each inlet's hydraulic diameter, with the bulk velocity from the velocity inlet,
or ṁ / (ρ A) for a mass-flow inlet; a total-pressure inlet's flow rate follows from the losses, so its numbers are
known after the run, from the inlet's mass-flow report. The speed of sound a is Physics.speed_of_sound.
"""

from dataclasses import dataclass

from vortexcfd.core.project import Project
from vortexcfd.core.reports import flow_id
from vortexcfd.foam.physics_case import reference_values
from vortexcfd.workflow import internal

# Above this Mach number the incompressible solver's results lose accuracy (density changes of a few per cent).
MACH_LIMIT = 0.3
SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


@dataclass(frozen=True)
class FlowNumbers:
    """Re and Ma of one flow (None: not known), the velocity and length they are taken on, and why one is missing."""

    reynolds: float | None
    mach: float | None
    speed: float | None
    speed_name: str  # "U∞", "U_bulk"
    length: float | None
    length_name: str  # "l_ref", "D_h (inlet)"
    note: str = ""  # e.g. "known after the run"
    source: str = ""  # where the velocity comes from ("free stream", "velocity inlet", "mass flow", "mass-flow report")

    def reynolds_text(self) -> str:
        """'Re = 1.2·10⁶ on U∞ = 20 m/s, l_ref = 0.3 m', or why it is not known."""
        if self.reynolds is None:
            return self.note or "—"
        return (f"Re = {format_number(self.reynolds)} on {self.speed_name} = {self.speed:.3g} m/s, "
                f"{self.length_name} = {self.length:.3g} m" + (f" ({self.source})" if self.source else ""))

    def mach_text(self, speed_of_sound: float) -> str:
        """'Ma = 0.058 on U∞ = 20 m/s, a = 343 m/s', or why it is not known."""
        if self.mach is None:
            return self.note or "—"
        return f"Ma = {self.mach:.3g} on {self.speed_name} = {self.speed:.3g} m/s, a = {speed_of_sound:.4g} m/s"

    @property
    def warning(self) -> str | None:
        return mach_warning(self.mach)


def format_number(value: float) -> str:
    """A positive number to two significant digits in the a·10ⁿ form ("1.2·10⁶"); 1 to 9999 as they are ("250")."""
    if value <= 0:
        return f"{value:.2g}"
    if 1 <= value < 1e4:
        return f"{value:.3g}"
    mantissa, exponent = f"{value:.1e}".split("e")
    return f"{mantissa}·10{str(int(exponent)).translate(SUPERSCRIPT)}"


def mach_warning(mach: float | None) -> str | None:
    """The soft warning above MACH_LIMIT: the app is incompressible."""
    if mach is None or mach <= MACH_LIMIT:
        return None
    return (f"Mach number {mach:.2f} is above {MACH_LIMIT:g}: the app solves incompressible flow (simpleFoam), so the "
            "density changes of this flow are ignored and the results lose accuracy.")


def _numbers(speed: float | None, length: float | None, project: Project, speed_name: str, length_name: str,
             note: str = "", source: str = "") -> FlowNumbers:
    physics = project.sim.physics
    re = speed * length / physics.nu if speed and length else None
    ma = speed / physics.speed_of_sound if speed else None
    return FlowNumbers(re, ma, speed, speed_name, length, length_name, note, source)


def external_numbers(project: Project) -> FlowNumbers:
    """Re on the free-stream speed and l_ref; l_ref unknown (a part cannot be loaded and none is set): Re unknown."""
    from vortexcfd.workflow.meshing import MeshingNotReady, body_bounds

    sim = project.sim
    length = sim.reports.reference_length
    if length is None:
        try:
            bounds = body_bounds(project)
        except (MeshingNotReady, ValueError, OSError, TypeError):  # TypeError: an unsaved project
            bounds = None
        length = reference_values(bounds, sim.reports).l_ref if bounds is not None else None
    note = "" if length else "l_ref unknown: import a part or set Reference Values > l_ref"
    return _numbers(sim.inflow.speed, length, project, "U∞", "l_ref", note)


def inlet_numbers(project: Project, mass_flow_of=None) -> dict[str, FlowNumbers]:
    """Per inlet (mesh patch name): Re on its D_h with its bulk velocity. ``mass_flow_of(report_id)`` gives the last
    value of a mass-flow report of the shown run (kg/s, any sign) or None; a total-pressure inlet uses it, else its
    numbers are known after the run."""
    from vortexcfd.workflow.meshing import MeshingNotReady, _body_parts

    sim = project.sim
    try:
        _names, meshes = _body_parts(project)
        measures = internal.inlet_measures(project, meshes) if meshes else {}
    except (MeshingNotReady, ValueError, OSError, TypeError):  # TypeError: an unsaved project
        measures = {}
    rho = sim.physics.rho_ref
    out: dict[str, FlowNumbers] = {}
    for patch in internal.patches(project):
        if patch.role != "inlet":
            continue
        m = measures.get(patch.safe)
        spec = sim.boundary(patch.name).inlet
        length_name = f"D_h ({patch.name})"
        if m is None:
            out[patch.safe] = _numbers(None, None, project, "U_bulk", length_name,
                                       "the inlet's geometry cannot be read")
            continue
        if spec.kind == "velocity":
            out[patch.safe] = _numbers(spec.speed, m.hydraulic_diameter, project, "U_bulk", length_name,
                                       source="velocity inlet")
        elif spec.kind == "mass_flow":
            speed = spec.mass_flow / (rho * m.area) if m.area > 0 else None
            out[patch.safe] = _numbers(speed, m.hydraulic_diameter, project, "U_bulk", length_name,
                                       source="ṁ / (ρ A)")
        else:  # total pressure: the flow rate follows from the losses
            mdot = mass_flow_of(flow_id("mdot", f"patch:{patch.safe}")) if mass_flow_of is not None else None
            if mdot is None or m.area <= 0:
                out[patch.safe] = _numbers(None, m.hydraulic_diameter, project, "U_bulk", length_name,
                                           "known after the run (a total-pressure inlet: the flow rate follows from "
                                           "the losses)")
            else:
                out[patch.safe] = _numbers(abs(mdot) / (rho * m.area), m.hydraulic_diameter, project, "U_bulk",
                                           length_name, source="from the run's mass-flow report")
    return out


def project_numbers(project: Project, mass_flow_of=None) -> FlowNumbers | None:
    """The project's numbers: external flow's, or the reference inlet's (the first inlet) in internal flow; None for
    an internal project without an inlet."""
    if not project.sim.internal:
        return external_numbers(project)
    numbers = inlet_numbers(project, mass_flow_of)
    return next(iter(numbers.values()), None)


def run_report_values(project: Project):
    """A ``mass_flow_of`` over the project's last run (case/postProcessing, read once): the last value of a report,
    or None when the case has no such report."""
    from vortexcfd.foam.postprocessing import ReportMonitor

    case = project.folder / "case" if project.folder is not None else None
    if case is None or not (case / "postProcessing").is_dir():
        return lambda _report_id: None
    monitor = ReportMonitor(case)
    monitor.poll()

    def last(report_id: str) -> float | None:
        try:
            series = monitor.series(report_id)
        except (OSError, KeyError, ValueError):
            return None
        return float(series[-1][1]) if series else None

    return last


def summary(numbers: FlowNumbers | None) -> dict[str, str]:
    """The set-up summary's entries (workflow/snapshots.setup_summary): "flow: Reynolds number", "flow: Mach number"."""
    if numbers is None:
        return {}
    out = {}
    if numbers.reynolds is not None:
        out["flow: Reynolds number"] = (f"{format_number(numbers.reynolds)} ({numbers.speed_name} "
                                        f"{numbers.speed:.3g} m/s, {numbers.length_name} {numbers.length:.3g} m)")
    if numbers.mach is not None:
        out["flow: Mach number"] = f"{numbers.mach:.3g}"
    return out

