"""The live view of a running solver (D-172, Qt-free): a ``surfaces`` function object that samples the wall patches
and the Results Scene's planes every N iterations into postProcessing/liveView/<iteration>/ (VTK), and the reader
side: the latest complete sample, the older ones removed (only the latest is kept on disk).

[NUMERICS-REVIEW] The function object only samples (it never changes the solution): sampleScheme cell and no
interpolation, so each face carries its cell's value, as the Results Scene shows the walls and the sections.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

LIVE_VIEW = "liveView"  # the function object and its postProcessing folder
LIVE_FIELDS = ("p", "U", "k", "omega", "nut")
WALLS = "walls"  # the surface of the wall patches
SAMPLE_SUFFIXES = (".vtp", ".vtk")


@dataclass(frozen=True)
class LivePlane:
    """A plane sampled by the live view: its surface name (letters, digits, _), a point and its normal."""

    name: str
    point: tuple[float, float, float]
    normal: tuple[float, float, float]


@dataclass(frozen=True)
class LiveViewSpec:
    """What the live view samples: the wall patches, the planes, every ``interval`` iterations."""

    walls: tuple[str, ...]
    planes: tuple[LivePlane, ...] = ()
    interval: int = 50

    def surface_names(self) -> tuple[str, ...]:
        return ((WALLS,) if self.walls else ()) + tuple(p.name for p in self.planes)


def safe_name(text: str) -> str:
    """A surface name from any text (letters, digits and _, starting with a letter)."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", text)
    return name if name[:1].isalpha() else f"s_{name}"


def function_object(spec: LiveViewSpec) -> dict:
    """The controlDict entry of the live view [NUMERICS-REVIEW]."""
    surfaces: dict[str, dict] = {}
    if spec.walls:
        surfaces[WALLS] = {"type": "patch", "patches": list(spec.walls), "interpolate": False}
    for plane in spec.planes:
        surfaces[plane.name] = {"type": "cuttingPlane", "point": list(plane.point), "normal": list(plane.normal),
                                "interpolate": False}
    return {
        "type": "surfaces",
        "libs": ["sampling"],
        "writeControl": "timeStep",
        "writeInterval": int(spec.interval),
        "surfaceFormat": "vtk",
        "fields": list(LIVE_FIELDS),
        "sampleScheme": "cell",
        "surfaces": surfaces,
    }


@dataclass(frozen=True)
class LiveSample:
    """One sample of the live view: its iteration (a transient run's time, D-181) and the file of each surface."""

    iteration: int | float
    files: dict[str, Path]


def _iteration(name: str) -> int | float | None:
    """A sample folder's iteration, or a transient run's time (a float, D-181)."""
    try:
        value = float(name)
    except ValueError:
        return None
    return int(round(value)) if value == round(value) else value


def _files(folder: Path) -> dict[str, Path]:
    """The surface files of a sample folder by surface name (the file's stem)."""
    out = {}
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix in SAMPLE_SUFFIXES and path.stat().st_size > 0:
            out.setdefault(path.stem, path)
    return out


def samples(case_dir: Path) -> list[tuple[int, Path]]:
    """Every sample folder (iteration, path) in iteration order."""
    root = Path(case_dir) / "postProcessing" / LIVE_VIEW
    if not root.is_dir():
        return []
    found = [(_iteration(child.name), child) for child in root.iterdir() if child.is_dir()]
    return sorted((it, path) for it, path in found if it is not None)


def latest_sample(case_dir: Path, expected: tuple[str, ...] = (), settled: dict | None = None) -> LiveSample | None:
    """The newest complete sample: every ``expected`` surface written (any when none is given). A folder that may
    still be written (the newest one, whose files changed since the last call: ``settled`` keeps their sizes) is
    taken only once its files have stopped growing; an older complete one is taken meanwhile."""
    for rank, (iteration, folder) in enumerate(reversed(samples(case_dir))):
        files = _files(folder)
        if not files or any(name not in files for name in expected):
            continue
        if settled is not None and rank == 0:  # only the newest folder may still be written
            sizes = tuple(sorted((name, path.stat().st_size) for name, path in files.items()))
            if settled.get(iteration) != sizes:
                settled[iteration] = sizes  # seen for the first time or still growing: wait one poll
                continue
        return LiveSample(iteration, files)
    return None


def prune(case_dir: Path, keep: int) -> list[int]:
    """Remove every sample older than the iteration ``keep`` (only the latest stays on disk); returns the removed."""
    removed = []
    for iteration, folder in samples(case_dir):
        if iteration < keep:
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(iteration)
    return removed
