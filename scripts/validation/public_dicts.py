"""The meshing and solver dictionaries of the public benchmark cases (sphere, wing, ahmed), written to a folder, so
two versions of the app can be compared file by file (diff -r): the proof that a change leaves the external-flow
defaults unchanged. No OpenFOAM run: the meshing case as prepare_job writes it, the solver files as
build_solver_files makes them from the same project (the 2D span and the mesh-dependent inputs do not apply).

    .venv/bin/python scripts/validation/public_dicts.py OUT_DIR
    PYTHONPATH=<other checkout>/src .venv/bin/python scripts/validation/public_dicts.py OUT_DIR_2
    diff -r OUT_DIR OUT_DIR_2
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402
from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

apply_display_guard()
isolate_settings()  # never the user's settings or Recent list (D-141)

from vortexcfd.bench.cases import CASES  # noqa: E402
from vortexcfd.bench.geometries import ensure_geometry  # noqa: E402
from vortexcfd.bench.runner import import_geometry, new_project  # noqa: E402
from vortexcfd.foam.dictfile import write_foam_file  # noqa: E402
from vortexcfd.foam.physics_case import build_solver_files  # noqa: E402
from vortexcfd.workflow import meshing, solving  # noqa: E402

GEOMETRY = ROOT / "benchmarks" / "geometries"
DICTS = ("system", "constant/triSurface")


def main() -> None:
    out = Path(sys.argv[1]).resolve()
    if out.exists():
        shutil.rmtree(out)
    work = out.parent / (out.name + "_work")
    if work.exists():
        shutil.rmtree(work)
    for name in ("sphere", "wing", "ahmed"):
        case = CASES[name]
        project = new_project(case, work / name)
        import_geometry(project, ensure_geometry(case.geometry, GEOMETRY), case.units, case.import_mode)
        job = meshing.prepare_job(project)
        target = out / name / "mesh"
        for rel in DICTS:
            if (job.case_dir / rel).is_dir():
                shutil.copytree(job.case_dir / rel, target / rel)
        for rel, spec in build_solver_files(solving.solver_input(project)).items():
            write_foam_file(out / name / "solver" / rel, spec.content, object_name=Path(rel).name,
                            class_name=spec.class_name)
    shutil.rmtree(work)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    print(f"{len(files)} files in {out}")


if __name__ == "__main__":
    main()
