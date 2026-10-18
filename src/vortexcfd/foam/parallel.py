"""Parallel solver runs: physical cores, decomposeParDict, the decomposePar summary (no Qt). (D-063)

A run with ``Solvers.cores`` N > 1 is decomposed with ``decomposePar -force`` (method scotch,
system/decomposeParDict), solved with ``mpirun -np N simpleFoam -parallel`` and reconstructed
with ``reconstructPar -latestTime`` (foam/solver_run.py), so the viewer, the reports and ParaView
read an ordinary reconstructed case. The function objects' postProcessing files and the solver
log are written by the master rank in the case directory in the serial format.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from vortexcfd.foam.case_writer import FoamFileSpec

METHOD = "scotch"  # src/parallel/decompose/scotchDecomp: TypeName("scotch"); needs no coefficients
DECOMPOSE_DICT = "system/decomposeParDict"


def physical_cores(cpuinfo: Path = Path("/proc/cpuinfo")) -> int:
    """Physical cores of this machine: distinct (physical id, core id) pairs of /proc/cpuinfo
    (hyper-threads share a core), else os.cpu_count()."""
    pairs, phys = set(), "0"
    try:
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key == "physical id":
                phys = value.strip()
            elif key == "core id":
                pairs.add((phys, value.strip()))
    except OSError:
        pass
    return len(pairs) or os.cpu_count() or 1


def decompose_par_dict(cores: int) -> FoamFileSpec:
    """system/decomposeParDict for ``cores`` subdomains (keywords of decompositionMethod.C)."""
    if cores < 2:
        raise ValueError("a decomposition needs at least 2 subdomains")
    return FoamFileSpec(content={"numberOfSubdomains": cores, "method": METHOD})


def solver_command(solver: str, cores: int) -> list[str]:
    """The solver command line: serial, or through mpirun on ``cores`` ranks."""
    if cores <= 1:
        return [solver]
    return ["mpirun", "-np", str(cores), solver, "-parallel"]


DECOMPOSE_COMMAND = ["decomposePar", "-force"]
RECONSTRUCT_COMMAND = ["reconstructPar", "-latestTime"]


def processor_dirs(case_dir: Path) -> list[Path]:
    return sorted(p for p in Path(case_dir).glob("processor*") if p.is_dir())


@dataclass(frozen=True)
class Decomposition:
    """decomposePar's summary."""

    cells: tuple[int, ...]  # per processor
    processor_faces: int | None = None
    max_above_average: float | None = None  # percent

    def summary(self) -> str:
        n = len(self.cells)
        text = (f"Decomposed into {n} subdomains ({METHOD}): {min(self.cells)}-{max(self.cells)} cells per "
                f"processor")
        if self.max_above_average is not None:
            text += f" (max {self.max_above_average:.2g}% above average)"
        if self.processor_faces is not None:
            text += f", {self.processor_faces} faces between processors"
        return text


_PROC_RE = re.compile(r"^Processor (\d+)$")
_CELLS_RE = re.compile(r"^Number of cells = (\d+)$")
_FACES_RE = re.compile(r"^Number of processor faces = (\d+)$")
_MAX_RE = re.compile(r"^Max number of cells = \d+ \(([-+0-9.eE]+)% above average")


def parse_decomposition(text: str) -> Decomposition | None:
    """The decomposition summary of a decomposePar log (None when it has none)."""
    cells: dict[int, int] = {}
    current, faces, above = None, None, None
    for raw in text.splitlines():
        line = raw.strip()
        if raw.startswith("Processor ") and (m := _PROC_RE.match(line)):
            current = int(m.group(1))
        elif current is not None and current not in cells and (m := _CELLS_RE.match(line)):
            cells[current] = int(m.group(1))
        elif not raw.startswith(" ") and (m := _FACES_RE.match(line)):
            faces = int(m.group(1))  # the total (indented lines are per processor)
        elif m := _MAX_RE.match(line):
            above = float(m.group(1))
    if not cells:
        return None
    return Decomposition(tuple(cells[k] for k in sorted(cells)), faces, above)
