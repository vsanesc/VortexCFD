"""Parallel speedup study (D-064, marker ``long``; run with nothing else on the machine):

    .venv/bin/pytest -m long -s tests/test_parallel_speedup.py

A sphere mesh of about one million cells (the default domain and sizing with a background cell
budget of 900,000), 100 iterations of the app's simpleFoam set-up (20 m/s, alpha 4 deg, no stopping
criteria) at 1, 2, 4 and 8 cores, each with Open MPI's default placement and with ``--bind-to core
--map-by core`` (foam/parallel.BINDINGS). The solver's wall time (FoamRun's duration, without
decomposePar and reconstructPar) is written to docs/validation/parallel/speedup.json and printed as
the table of docs/validation/parallel/README.md.
"""

import json
from pathlib import Path

import pytest

from tests.real_cases import mesh_body, run_solver, sphere, write_solver_case
from vortexcfd.core.model import Inflow, Mesh, Solvers, StoppingCriteria
from vortexcfd.core.project_io import V9_MESH_BEHAVIOUR
from vortexcfd.foam.parallel import BINDINGS
from vortexcfd.foam.solver_run import ITERATION_LIMIT

pytestmark = [pytest.mark.long, pytest.mark.slow]

OUT = Path(__file__).resolve().parents[1] / "docs" / "validation" / "parallel" / "speedup.json"
BACKGROUND_CELLS = 900_000
ITERATIONS = 100
CORES = (1, 2, 4, 8)


def test_speedup_study(tmp_path: Path) -> None:
    import shutil

    meshed = mesh_body(tmp_path / "mesh", sphere(), "Sphere", Mesh(**V9_MESH_BEHAVIOUR, background_cells_target=BACKGROUND_CELLS),
                       step_timeout_s=1800, total_timeout_s=3600)
    assert meshed.ok, "".join(meshed.lines[-30:])
    rows = []
    for binding in BINDINGS:
        for cores in CORES:
            if cores == 1 and binding != "default":
                continue  # a serial run has no mpirun
            case = tmp_path / f"{binding}_{cores}"
            shutil.copytree(meshed.case_dir, case)
            meshed_copy = type(meshed)(case, meshed.inputs)
            write_solver_case(meshed_copy, inflow=Inflow(alpha_deg=4.0),
                              solvers=Solvers(iterations=ITERATIONS, write_interval=ITERATIONS, cores=cores,
                                              stopping=StoppingCriteria(criteria=[])))
            result = run_solver(case, timeout_s=3600, cores=cores, binding=binding)
            assert result is not None and result.state == ITERATION_LIMIT and result.iterations == ITERATIONS, result
            rows.append({"binding": binding, "cores": cores, "wall_s": round(result.duration_s, 1)})
            shutil.rmtree(case)
    serial = next(r["wall_s"] for r in rows if r["cores"] == 1)
    for r in rows:
        r["speedup"] = round(serial / r["wall_s"], 2)
        r["efficiency"] = round(serial / r["wall_s"] / r["cores"], 2)
        r["cells_per_core"] = meshed.cells // r["cores"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cells": meshed.cells, "background_cells_target": BACKGROUND_CELLS,
                               "iterations": ITERATIONS, "rows": rows}, indent=2) + "\n")
    print(f"\n{meshed.cells} cells, {ITERATIONS} iterations")
    print("| Binding | Cores | Wall time [s] | Speedup | Efficiency | Cells per core |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['binding']} | {r['cores']} | {r['wall_s']} | {r['speedup']} | {r['efficiency']} | "
              f"{r['cells_per_core']:,} |")
