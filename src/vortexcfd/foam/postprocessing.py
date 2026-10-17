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

The files are tailed: each poll reads only the bytes appended since the last one and keeps an
incomplete last line for the next poll.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.foam.dictfile import read_foam_file

FORCE_COEFFS = "forceCoeffs1"
FORCE_COEFFS_FILE = "coefficient.dat"
FORCES = "forces1"
FORCES_FILE = "force.dat"
YPLUS = "yPlus1"
YPLUS_FILE = "yPlus.dat"

# Report ids (core.model.REPORT_IDS) -> label shown in the report slot.
REPORT_LABELS = {
    "Cd": "Cd",
    "Cl": "Cl",
    "CmPitch": "Cm (pitch)",
    "yplus_min": "y+ min (walls)",
    "yplus_avg": "y+ avg (walls)",
    "yplus_max": "y+ max (walls)",
}
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
        """Over all wall patches per write time: the minimum of the minima ("min"), the maximum of
        the maxima ("max"), or the face-count-weighted average of the patch averages ("average",
        i.e. the mean over all wall faces). Without a face count for every patch the average falls
        back to the plain mean of the patch averages."""
        out = []
        for t in sorted(self.rows):
            patches = self.rows[t]
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


class ReportMonitor:
    """All report series of a run, polled from the case's postProcessing files."""

    def __init__(self, case_dir: Path) -> None:
        self.case_dir = Path(case_dir)
        self._forces: ForceCoeffsTail | None = None
        self._yplus: YPlusTail | None = None
        self._face_counts: dict[str, int] = {}

    def poll(self) -> bool:
        """Read whatever was appended; True if anything new arrived."""
        if self._forces is None:
            path = output_file(self.case_dir, FORCE_COEFFS, FORCE_COEFFS_FILE)
            self._forces = ForceCoeffsTail(path) if path is not None else None
        if self._yplus is None:
            path = output_file(self.case_dir, YPLUS, YPLUS_FILE)
            self._yplus = YPlusTail(path) if path is not None else None
            if self._yplus is not None:
                self._face_counts = patch_face_counts(self.case_dir)
        added = 0
        for tail in (self._forces, self._yplus):
            if tail is not None:
                added += tail.poll()
        return added > 0

    def series(self, report_id: str) -> list[tuple[float, float]]:
        """(iteration, value) pairs of a report (REPORT_LABELS), empty when not written yet."""
        if report_id in FORCE_REPORTS:
            return list(self._forces.series.get(report_id, [])) if self._forces is not None else []
        if report_id in YPLUS_REPORTS:
            if self._yplus is None:
                return []
            return self._yplus.series(YPLUS_REPORTS[report_id], self._face_counts)
        raise KeyError(report_id)
