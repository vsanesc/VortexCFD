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


# mpirun process placement (D-064): "default" leaves Open MPI 4.1's own policy (bind to core for
# up to 2 ranks, to the package above), "core" maps and binds each rank to one physical core.
BINDINGS = {
    "default": [],
    "core": ["--bind-to", "core", "--map-by", "core"],
}
DEFAULT_BINDING = "default"


def parallel_command(command: list[str], cores: int, binding: str = DEFAULT_BINDING) -> list[str]:
    """``command`` (an OpenFOAM application and its arguments) as it is: serial, or through mpirun on
    ``cores`` ranks with ``binding`` (a key of BINDINGS) and ``-parallel``."""
    if cores <= 1:
        return list(command)
    return ["mpirun", "-np", str(cores), *BINDINGS[binding], *command, "-parallel"]


def solver_command(solver: str, cores: int, binding: str = DEFAULT_BINDING) -> list[str]:
    """The solver command line: serial, or through mpirun on ``cores`` ranks with ``binding``
    (a key of BINDINGS)."""
    return parallel_command([solver], cores, binding)


# Recommended core count (D-064, docs/validation/parallel/README.md): at least CELLS_PER_CORE cells
# per rank, and no more than EFFICIENT_CORES ranks: on the development machine (Ryzen 9 5900X, two
# memory channels) the parallel efficiency is at least 0.5 up to 4 ranks and drops to 0.28-0.37 at 8
# for every mesh measured (192k to 990k cells): the solver is memory-bandwidth bound.
CELLS_PER_CORE = 50_000
EFFICIENT_CORES = 4


def recommended_cores(cells: int, physical: int, cells_per_core: int = CELLS_PER_CORE,
                      efficient: int = EFFICIENT_CORES) -> int:
    """min(physical cores, cells / cells_per_core rounded down, ``efficient``), at least 1 (D-064)."""
    return max(1, min(physical, int(cells) // cells_per_core, efficient))


# Recommended meshing cores (D-111, benchmarks/RESULT_parallel_mesh.md): from the estimated background
# cells (the only cell count known before meshing, foam/mesh_estimate), at least MESH_CELLS_PER_CORE
# background cells per rank and no more than MESH_EFFICIENT_CORES ranks. Measured on the development
# machine with 100,000 background cells: 8 ranks mesh 1.85-2.13 times faster than serial on the public
# cases and 4.13 times on the aircraft, still faster than 4 ranks everywhere; above 8 was not measured.
MESH_CELLS_PER_CORE = 12_500
MESH_EFFICIENT_CORES = 8


def recommended_mesh_cores(background_cells: int, physical: int) -> int:
    """The meshing recommendation: recommended_cores with the meshing constants (D-111)."""
    return recommended_cores(background_cells, physical, MESH_CELLS_PER_CORE, MESH_EFFICIENT_CORES)


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
