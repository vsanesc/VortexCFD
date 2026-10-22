"""Live reading of the function objects' output files in postProcessing/ (no Qt).

File names and columns are those written by ESI v2606 (checked against a real simpleFoam run of the
app's own controlDict, fixtures in tests/data/sphere_run/):

- forceCoeffs (src/functionObjects/forces/forceCoeffs): ``postProcessing/forceCoeffs1/<start
  time>/coefficient.dat``; comment header lines start with ``#``, the last one is ``# Time`` followed
  by the tab-separated coefficient names in sorted order (Cd, Cd(f), Cd(r), Cl, Cl(f), Cl(r),
  CmPitch, CmRoll, CmYaw, Cs, Cs(f), Cs(r)); one row per time step.
- forces (src/functionObjects/forces/forces): ``postProcessing/forces1/<start time>/force.dat``;
  header ``# Time  total_x total_y total_z  pressure_x ... viscous_z``; forces in N (rho = rhoInf)
  in the global axes (D-050).
- yPlus (src/functionObjects/field/yPlus): ``postProcessing/yPlus1/<start time>/yPlus.dat``;
  header ``# Time  patch  min  max  average``; one row per wall patch at every write time
  (executeControl/writeControl writeTime). ``average`` is the mean over the patch's faces; across
  several walls the average is weighted by each patch's face count (constant/polyMesh/boundary).

- forces per part, surfaceFieldValue sum(phi) and probes (D-060): foam/forces.py and
  ``ReportMonitor`` below.

The files are tailed: each poll reads only the bytes appended since the last one and keeps an
incomplete last line for the next poll.
"""

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

from vortexcfd.core.reports import BREAKDOWN, MASS, split_part, split_probe
from vortexcfd.foam.dictfile import read_foam_file
from vortexcfd.foam.mesh_case import GROUND_PATCH
from vortexcfd.foam.forces import (
    CoeffAxes,
    ForceRow,
    ForceSample,
    breakdown,
    mass_imbalance,
    parse_vector_row,
    read_coeff_axes,
)

FORCE_COEFFS = "forceCoeffs1"
FORCE_COEFFS_FILE = "coefficient.dat"
FORCES = "forces1"
FORCES_FILE = "force.dat"
MOMENT_FILE = "moment.dat"
MASS_FILE = "surfaceFieldValue.dat"
YPLUS = "yPlus1"
YPLUS_FILE = "yPlus.dat"

FORCE_REPORTS = ("Cd", "Cl", "CmPitch")
YPLUS_REPORTS = {"yplus_min": "min", "yplus_avg": "average", "yplus_max": "max"}


def _time_key(name: str) -> float:
    try:
        return float(name)
    except ValueError:
        return float("-inf")


def output_file(case_dir: Path, function: str, file_name: str) -> Path | None:
    """The function object's file in the latest start-time directory, or None."""
    folder = Path(case_dir) / "postProcessing" / function
    if not folder.is_dir():
        return None
    for start in sorted((d for d in folder.iterdir() if d.is_dir()), key=lambda d: _time_key(d.name),
                        reverse=True):
        if (start / file_name).is_file():
            return start / file_name
    return None


class TailReader:
    """Reads the complete lines appended to a file since the last call."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._offset = 0
        self._partial = b""

    def read_lines(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:  # the file was replaced or truncated: start again
            self._offset, self._partial = 0, b""
        if size == self._offset:
            return []
        with open(self.path, "rb") as fh:
            fh.seek(self._offset)
            data = fh.read(size - self._offset)
        self._offset += len(data)
        data = self._partial + data
        *complete, self._partial = data.split(b"\n")
        return [line.decode("utf-8", errors="replace").rstrip("\r") for line in complete]


def _floats(parts: list[str]) -> list[float] | None:
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


@dataclass
class ForceCoeffsTail:
    """Coefficient series from coefficient.dat: column name -> [(time, value)]."""

    path: Path
    columns: list[str] = field(default_factory=list)
    series: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        """Read new rows; returns how many were added."""
        added = 0
        for line in self._reader.read_lines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("#"):
                body = text[1:].strip()
                if body.startswith("Time"):
                    self.columns = [c.strip() for c in body.split("\t")[1:] if c.strip()]
                    for name in self.columns:
                        self.series.setdefault(name, [])
                continue
            values = _floats(text.split())
            if values is None or not self.columns or len(values) != len(self.columns) + 1:
                continue  # a malformed row is skipped
            for name, value in zip(self.columns, values[1:]):
                self.series[name].append((values[0], value))
            added += 1
        return added


@dataclass
class ForcesTail:
    """Total force vectors from force.dat: [(time, (Fx, Fy, Fz))] in the global axes."""

    path: Path
    total: list[tuple[float, tuple[float, float, float]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        added = 0
        for line in self._reader.read_lines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            values = _floats(text.replace("(", " ").replace(")", " ").split())
            if values is None or len(values) < 10:
                continue
            self.total.append((values[0], (values[1], values[2], values[3])))
            added += 1
        return added


def project_coefficients(force: tuple[float, float, float], alpha_deg: float, rho: float, speed: float,
                         area: float) -> tuple[float, float]:
    """(Cd, Cl) of a global force vector: its components along dragDir = (cos a, 0, sin a) and
    liftDir = (-sin a, 0, cos a) divided by 0.5 rho U^2 A_ref (the app's forceCoeffs axes)."""
    a = math.radians(alpha_deg)
    q = 0.5 * rho * speed**2 * area
    fx, _fy, fz = force
    return (fx * math.cos(a) + fz * math.sin(a)) / q, (-fx * math.sin(a) + fz * math.cos(a)) / q


@dataclass
class YPlusTail:
    """y+ statistics from yPlus.dat. ``rows``: time -> {patch: (min, max, average)}."""

    path: Path
    rows: dict[float, dict[str, tuple[float, float, float]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        added = 0
        for line in self._reader.read_lines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split()
            if len(parts) != 5:
                continue
            values = _floats([parts[0], *parts[2:]])
            if values is None:
                continue
            t, lo, hi, avg = values
            self.rows.setdefault(t, {})[parts[1]] = (lo, hi, avg)
            added += 1
        return added

    def series(self, stat: str, face_counts: dict[str, int] | None = None) -> list[tuple[float, float]]:
        """Over all part wall patches per write time (the ground plane is left out, D-116): the minimum
        of the minima ("min"), the maximum of
        the maxima ("max"), or the face-count-weighted average of the patch averages ("average",
        i.e. the mean over all wall faces). Without a face count for every patch the average falls
        back to the plain mean of the patch averages."""
        out = []
        for t in sorted(self.rows):
            patches = {name: row for name, row in self.rows[t].items() if name != GROUND_PATCH}
            if not patches:
                continue
            if stat == "min":
                value = min(p[0] for p in patches.values())
            elif stat == "max":
                value = max(p[1] for p in patches.values())
            elif face_counts and all(face_counts.get(name, 0) > 0 for name in patches):
                total = sum(face_counts[name] for name in patches)
                value = sum(face_counts[name] * p[2] for name, p in patches.items()) / total
            else:
                value = sum(p[2] for p in patches.values()) / len(patches)
            out.append((t, value))
        return out


def patch_face_counts(case_dir: Path) -> dict[str, int]:
    """nFaces of every patch in constant/polyMesh/boundary ({} when it cannot be read)."""
    try:
        data = read_foam_file(Path(case_dir) / "constant" / "polyMesh" / "boundary")
    except Exception:  # missing file or foamlib parser errors
        return {}
    entries = data.get(None, []) if isinstance(data, dict) else []
    counts = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], dict):
            n = entry[1].get("nFaces")
            if isinstance(n, int):
                counts[str(entry[0])] = n
    return counts


class ScalarTail:
    """(time, value) rows of a two-column file: surfaceFieldValue.dat or a one-probe scalar file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.values: list[tuple[float, float]] = []
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        added = 0
        for line in self._reader.read_lines():
            parts = line.split()
            if len(parts) != 2 or line.lstrip().startswith("#"):
                continue
            values = _floats(parts)
            if values is not None:
                self.values.append((values[0], values[1]))
                added += 1
        return added


class VectorTail:
    """(time, (x, y, z)) rows of a one-probe vector file (``1  (18.8 -9.6e-05 -0.0003)``)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.values: list[tuple[float, tuple[float, float, float]]] = []
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        added = 0
        for line in self._reader.read_lines():
            if line.lstrip().startswith("#"):
                continue
            values = _floats(line.replace("(", " ").replace(")", " ").split())
            if values is not None and len(values) == 4:
                self.values.append((values[0], (values[1], values[2], values[3])))
                added += 1
        return added


class ForceVectorTail:
    """force.dat / moment.dat rows: (time, (total, pressure, viscous))."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.rows: list = []
        self._reader = TailReader(self.path)

    def poll(self) -> int:
        added = 0
        for line in self._reader.read_lines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            row = parse_vector_row(line)
            if row is not None:
                self.rows.append(row)
                added += 1
        return added


def _last_per_time(rows):
    """{time: value}, the last value written for each time (writeAndEnd repeats the final row)."""
    return {t: v for t, v in rows}


class _Breakdown:
    """The force rows of one wall set, kept up to date incrementally: the row of a time is
    ``breakdown`` of the last force and moment rows written for that time (writeAndEnd repeats the
    final row, a truncated file is re-read), computed again only when one of them changes, with the
    axes and rho the rows were read with. ``rows`` keeps the times in order of first appearance."""

    def __init__(self, axes: CoeffAxes, rho: float) -> None:
        self.axes, self.rho = axes, rho
        self.force: dict[float, tuple] = {}
        self.moment: dict[float, tuple] = {}
        self.rows: dict[float, ForceRow] = {}
        self.done_force = self.done_moment = 0

    def update(self, forces: ForceVectorTail, moments: ForceVectorTail | None) -> list[tuple[float, ForceRow]]:
        changed: set[float] = set()
        for t, f in forces.rows[self.done_force:]:
            self.force[t] = f
            changed.add(t)
        self.done_force = len(forces.rows)
        if moments is not None:
            for t, m in moments.rows[self.done_moment:]:
                self.moment[t] = m
                changed.add(t)
            self.done_moment = len(moments.rows)
        for t in changed:
            if t in self.force:
                self.rows[t] = breakdown("", ForceSample(t, self.force[t], self.moment.get(t)), self.axes, self.rho)
        return [(t, self.rows[t]) for t in self.force]


class ReportMonitor:
    """All report series of a run, polled from the case's postProcessing files (D-048, D-060).

    Function objects are found by their names (foam/physics_case.py): forceCoeffs1 / forces1 for all
    walls, forceCoeffs_<patch> / forces_<patch> per part, massFlow_<patch>, probe_<name>, yPlus1.
    Report ids are those of core/reports.py.
    """

    def __init__(self, case_dir: Path) -> None:
        self.case_dir = Path(case_dir)
        self._coeffs: dict[str | None, ForceCoeffsTail] = {}
        self._force: dict[str | None, ForceVectorTail] = {}
        self._moment: dict[str | None, ForceVectorTail] = {}
        self._axes: dict[str | None, CoeffAxes] = {}
        self._mass: dict[str, ScalarTail] = {}
        self._probe_p: dict[str, ScalarTail] = {}
        self._probe_u: dict[str, VectorTail] = {}
        self._yplus: YPlusTail | None = None
        self._face_counts: dict[str, int] = {}
        self._rho: float | None = None
        self._breakdowns: dict[str | None, _Breakdown] = {}

    # -- discovery --------------------------------------------------------------------------

    def _discover(self) -> None:
        folder = self.case_dir / "postProcessing"
        if not folder.is_dir():
            return
        for child in folder.iterdir():
            name = child.name
            if name == FORCE_COEFFS or name.startswith("forceCoeffs_"):
                key = None if name == FORCE_COEFFS else name[len("forceCoeffs_"):]
                if key not in self._coeffs:
                    path = output_file(self.case_dir, name, FORCE_COEFFS_FILE)
                    if path is not None:
                        self._coeffs[key] = ForceCoeffsTail(path)
            elif name == FORCES or name.startswith("forces_"):
                key = None if name == FORCES else name[len("forces_"):]
                for store, file_name in ((self._force, FORCES_FILE), (self._moment, MOMENT_FILE)):
                    if key not in store:
                        path = output_file(self.case_dir, name, file_name)
                        if path is not None:
                            store[key] = ForceVectorTail(path)
            elif name.startswith("massFlow_") and name[len("massFlow_"):] not in self._mass:
                path = output_file(self.case_dir, name, MASS_FILE)
                if path is not None:
                    self._mass[name[len("massFlow_"):]] = ScalarTail(path)
            elif name.startswith("probe_"):
                probe = name[len("probe_"):]
                if probe not in self._probe_p and (path := output_file(self.case_dir, name, "p")) is not None:
                    self._probe_p[probe] = ScalarTail(path)
                if probe not in self._probe_u and (path := output_file(self.case_dir, name, "U")) is not None:
                    self._probe_u[probe] = VectorTail(path)
            elif name == YPLUS and self._yplus is None:
                path = output_file(self.case_dir, YPLUS, YPLUS_FILE)
                if path is not None:
                    self._yplus = YPlusTail(path)
                    self._face_counts = patch_face_counts(self.case_dir)

    def _tails(self):
        yield from self._coeffs.values()
        yield from self._force.values()
        yield from self._moment.values()
        yield from self._mass.values()
        yield from self._probe_p.values()
        yield from self._probe_u.values()
        if self._yplus is not None:
            yield self._yplus

    def poll(self) -> bool:
        """Read whatever was appended; True if anything new arrived."""
        self._discover()
        return sum(tail.poll() for tail in self._tails()) > 0

    # -- reference values ----------------------------------------------------------------------

    def rho(self) -> float | None:
        """rhoInf of the forces function object (system/controlDict)."""
        if self._rho is None:
            try:
                functions = read_foam_file(self.case_dir / "system" / "controlDict").get("functions", {})
                self._rho = float(functions[FORCES]["rhoInf"])
            except Exception:  # missing file, entry or parser errors: no breakdown
                return None
        return self._rho

    def axes(self, key: str | None) -> CoeffAxes | None:
        if key not in self._axes and key in self._coeffs:
            axes = read_coeff_axes(self._coeffs[key].path)
            if axes is not None:
                self._axes[key] = axes
        return self._axes.get(key)

    # -- series ----------------------------------------------------------------------------------

    def part_keys(self) -> list[str]:
        """Part patches with their own force objects, sorted."""
        return sorted(k for k in self._force if k is not None)

    def _breakdown(self, key: str | None) -> list[tuple[float, ForceRow]]:
        """(time, force row) of every time written for the wall set ``key`` (the last rows of each
        time), in order of first appearance; empty without the files, the axes or rho."""
        forces = self._force.get(key)
        axes, rho = self.axes(key), self.rho()
        if forces is None or axes is None or rho is None:
            return []
        cache = self._breakdowns.get(key)
        if cache is None or cache.axes != axes or cache.rho != rho:
            cache = self._breakdowns[key] = _Breakdown(axes, rho)
        return cache.update(forces, self._moment.get(key))

    def _breakdown_series(self, base: str, key: str | None) -> list[tuple[float, float]]:
        attr = {"Cd_pressure": "cd_pressure", "Cd_viscous": "cd_viscous", "Cl_pressure": "cl_pressure",
                "Cl_viscous": "cl_viscous", "x_cp": "x_cp"}[base]
        out = []
        for t, row in self._breakdown(key):
            value = getattr(row, attr)
            if value is not None:
                out.append((t, value))
        return out

    def mass_series(self) -> list[tuple[float, float]]:
        """Mass imbalance (% of the inlet flux) per iteration, from massFlow_inlet / _outlet."""
        if "inlet" not in self._mass or "outlet" not in self._mass:
            return []
        inlet = _last_per_time(self._mass["inlet"].values)
        outlet = _last_per_time(self._mass["outlet"].values)
        out = []
        for t in inlet:
            if t in outlet:
                value = mass_imbalance(inlet[t], outlet[t])
                if value is not None:
                    out.append((t, value))
        return out

    def series(self, report_id: str) -> list:
        """(iteration, value) pairs of a report (core/reports.py ids), empty when not written yet.
        ``probe:<name>:U`` gives (iteration, (Ux, Uy, Uz))."""
        probe = split_probe(report_id)
        if probe is not None:
            name, comp = probe
            if comp == "p":
                return list(self._probe_p[name].values) if name in self._probe_p else []
            if name not in self._probe_u:
                return []
            vectors = self._probe_u[name].values
            if comp == "U":
                return list(vectors)
            if comp == "Umag":
                return [(t, math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)) for t, v in vectors]
            return [(t, v["xyz".index(comp[1])]) for t, v in vectors]
        if report_id in YPLUS_REPORTS:
            if self._yplus is None:
                return []
            return self._yplus.series(YPLUS_REPORTS[report_id], self._face_counts)
        if report_id == MASS:
            return self.mass_series()
        base, patch = split_part(report_id)
        if base in FORCE_REPORTS:
            tail = self._coeffs.get(patch)
            return list(tail.series.get(base, [])) if tail is not None else []
        if base in BREAKDOWN or base == "x_cp":
            return self._breakdown_series(base, patch)
        raise KeyError(report_id)

    # -- tables ----------------------------------------------------------------------------------

    def breakdown_rows(self) -> list[ForceRow]:
        """The latest force breakdown of all walls ("All walls") and of each part."""
        rows = []
        for key in (None, *self.part_keys()):
            computed = self._breakdown(key)
            if computed:
                rows.append(replace(computed[-1][1], name="All walls" if key is None else key))
        return rows

    def mass_balance(self) -> tuple[float, float, float | None] | None:
        """(inlet flux, outlet flux, imbalance %) at the latest iteration (None: not written)."""
        if "inlet" not in self._mass or "outlet" not in self._mass:
            return None
        inlet = _last_per_time(self._mass["inlet"].values)
        outlet = _last_per_time(self._mass["outlet"].values)
        common = sorted(set(inlet) & set(outlet))
        if not common:
            return None
        t = common[-1]
        return inlet[t], outlet[t], mass_imbalance(inlet[t], outlet[t])
