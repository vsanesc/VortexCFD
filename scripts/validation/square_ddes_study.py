"""Square cylinder at Re 22,000 with k-omega SST DDES in 3D (task 1.1-transient Part 2, Step 3;
docs/validation/square_ddes/SETUP.md): the validated 2D medium mesh of docs/validation/square_re22000/ extruded over
a span of 4 D in 20 cells with periodic sides, the app's DDES solver files written onto it, a scaling test and the
run.

    nice -n 15 .venv/bin/python scripts/validation/square_ddes_study.py build
    nice -n 15 .venv/bin/python scripts/validation/square_ddes_study.py scale --procs 4 6 8 10 12 --steps 200
    nice -n 15 .venv/bin/python scripts/validation/square_ddes_study.py run --procs 8

The extrusion and the periodic sides are OpenFOAM utilities (topoSet, createPatch, extrudeMesh), not the app's
mesher: the app meshes a 2D section one cell thick, and has no periodic boundary. Everything else (the physics,
schemes, fields, function objects, the run and its statistics) is the app's: physics_case.build_solver_files and
SolverRun. Work goes to run/validation/square_ddes/ (git-ignored).
"""

import argparse
import dataclasses
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("cylinder_study", Path(__file__).with_name("cylinder_study.py"))
cylinder_study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cylinder_study)  # the display guard and the isolated settings come with it

from tests.validation import square_case as sc  # noqa: E402
from vortexcfd.foam.dictfile import read_foam_file, write_foam_file  # noqa: E402

WORK = ROOT / "run" / "validation" / "square_ddes"
SOURCE_2D = ROOT / "run" / "validation" / "square_re22000" / "medium"  # the validated medium level (its project)
OUT = ROOT / "docs" / "validation" / "square_ddes"
say = cylinder_study.say

SPAN = 4.0  # D: the LES workshop's spanwise extent (ERCOFTAC UFR 2-02, "Test Case": "4 D in the spanwise direction")
NZ = 20  # spanwise cells: the most frequent Nz of the LES grids of the UFR 2-02 Evaluation, Table 1
END_TIME = 100.0  # t_c (SETUP.md)
SAMPLING_START = 40.0  # t_c, set by hand (SETUP.md): 30 t_c after the start-up perturbation
CYCLIC = ("periodic0", "periodic1")
FOAM = ["openfoam2606", "-c"]


def foam(case: Path, command: str, log: str) -> None:
    """An OpenFOAM utility in ``case`` (its output in ``log``); raises on failure."""
    with open(case / log, "w") as out:
        code = subprocess.run([*FOAM, command], cwd=case, stdout=out, stderr=subprocess.STDOUT).returncode
    if code != 0:
        raise SystemExit(f"{command} failed in {case} (see {log})")


def write(case: Path, rel: str, content: dict) -> None:
    write_foam_file(case / rel, content, object_name=Path(rel).name)


def _system(case: Path) -> None:
    """The fvSchemes and fvSolution the mesh utilities read (the 2D case's)."""
    for name in ("fvSchemes", "fvSolution"):
        shutil.copyfile(SOURCE_2D / "case" / "system" / name, case / "system" / name)


def build_mesh(case: Path) -> int:
    """The 3D mesh: the 2D mesh's frontAndBack split into front and back, the back face mesh extruded along +y over
    SPAN in NZ layers, and the two ends made a translational cyclic pair. Returns the cells."""
    src = WORK / "mesh2d"
    shutil.rmtree(src, ignore_errors=True)
    (src / "system").mkdir(parents=True)
    shutil.copytree(SOURCE_2D / "case" / "constant" / "polyMesh", src / "constant" / "polyMesh")
    y0 = float(_points(src)[:, 1].min())
    write(src, "system/controlDict", {"application": "none", "startFrom": "latestTime", "startTime": 0,
                                       "stopAt": "endTime", "endTime": 1, "deltaT": 1, "writeControl": "timeStep",
                                       "writeInterval": 1})
    write(src, "system/topoSetDict", {"actions": [
        {"name": "back", "type": "faceSet", "action": "new", "source": "patchToFace", "patch": "frontAndBack"},
        {"name": "back", "type": "faceSet", "action": "subset", "source": "boxToFace",
         "min": [-1e6, y0 - 1e-6, -1e6], "max": [1e6, y0 + 1e-6, 1e6]},
    ]})
    write(src, "system/createPatchDict", {"pointSync": False, "patches": [
        {"name": "back", "patchInfo": {"type": "patch"}, "constructFrom": "set", "set": "back"}]})
    _system(src)
    foam(src, "topoSet", "log.topoSet")
    foam(src, "createPatch -overwrite", "log.createPatch")
    shutil.rmtree(case, ignore_errors=True)
    (case / "system").mkdir(parents=True)
    write(case, "system/controlDict", {"application": "none", "startFrom": "latestTime", "startTime": 0,
                                        "stopAt": "endTime", "endTime": 1, "deltaT": 1, "writeControl": "timeStep",
                                        "writeInterval": 1})
    write(case, "system/extrudeMeshDict", {
        "constructFrom": "patch", "sourceCase": f'"{src}"', "sourcePatches": ["back"], "exposedPatchName": "frontAndBack",  # (the name must exist in the source mesh)
        "flipNormals": True, "extrudeModel": "linearDirection", "nLayers": NZ, "expansionRatio": 1.0,
        "linearDirectionCoeffs": {"direction": [0, 1, 0], "thickness": SPAN * sc.SIDE},
        "mergeFaces": False, "mergeTol": 0})
    _system(case)
    foam(case, "extrudeMesh", "log.extrudeMesh")
    write(case, "system/createPatchDict", {"matchTolerance": 1e-4, "pointSync": False, "patches": [
        {"name": CYCLIC[0], "patchInfo": {"type": "cyclic", "neighbourPatch": CYCLIC[1], "transform": "translational",
                                          "separationVector": [0, -SPAN * sc.SIDE, 0]},
         "constructFrom": "patches", "patches": ["back"]},
        {"name": CYCLIC[1], "patchInfo": {"type": "cyclic", "neighbourPatch": CYCLIC[0], "transform": "translational",
                                          "separationVector": [0, SPAN * sc.SIDE, 0]},
         "constructFrom": "patches", "patches": ["frontAndBack"]},
    ]})
    foam(case, "createPatch -overwrite", "log.createPatch")
    foam(case, "checkMesh -constant", "log.checkMesh")
    text = (case / "log.checkMesh").read_text()
    cells = int(next(line.split()[1] for line in text.splitlines() if line.strip().startswith("cells:")))
    say(f"3D mesh: {cells:,} cells, {NZ} spanwise layers over {SPAN:g} D; checkMesh "
        f"{'OK' if 'Mesh OK' in text else 'FAILED'}")
    return cells


def _points(case: Path):
    from vortexcfd.foam.polymesh import read_points

    return read_points(case / "constant" / "polyMesh" / "points")


def ddes_project():
    """The validated medium project (not saved back) as a DDES project of the 3D extrusion: k-omega SST DDES with
    the app's DDES defaults (D-191), A_ref = D x span, the transient settings of SETUP.md."""
    from vortexcfd.core.project import Project

    project = Project.open(SOURCE_2D / "square.json")
    project.update_physics(turbulence_model="kOmegaSSTDDES")
    project.update_reports(reference_area_basis="custom", reference_area=SPAN * sc.SIDE * sc.SIDE)
    project.update_transient(end_time=END_TIME, write_interval=10.0, sampling_start=SAMPLING_START)
    return project


def build_files(case: Path, cores: int) -> dict:
    """The app's solver files of the DDES project written onto the 3D mesh, the periodic pair added to every field.
    Returns what was written (the files' names)."""
    from vortexcfd.foam.case_writer import enable_clean_stop
    from vortexcfd.foam.physics_case import build_solver_files
    from vortexcfd.workflow import solving

    project = ddes_project()
    project.update_solver(cores=cores)
    inp = dataclasses.replace(solving.solver_input(project), span=None)  # 3D: no empty front and back
    files = enable_clean_stop(build_solver_files(inp))
    for rel in ("0", "postProcessing"):
        shutil.rmtree(case / rel, ignore_errors=True)
    for path in case.glob("processor*"):
        shutil.rmtree(path)
    for rel, spec in files.items():
        content = spec.content
        if rel.startswith("0/"):
            content = {**content, "boundaryField": {**content["boundaryField"],
                                                   **{name: {"type": "cyclic"} for name in CYCLIC}}}
        write_foam_file(case / rel, content, object_name=Path(rel).name, class_name=spec.class_name)
    return {"files": sorted(files)}


def cmd_build(_args) -> None:
    case = WORK / "case"
    cells = build_mesh(case)
    build_files(case, 8)
    (WORK / "mesh.json").write_text(json.dumps({"cells": cells, "span_D": SPAN, "nz": NZ}, indent=2) + "\n")
    say(f"wrote {case}")


def _set_end(case: Path, steps: int | None, end: float | None) -> None:
    from foamlib import FoamFile

    control = FoamFile(case / "system" / "controlDict")
    if steps is not None:  # a fixed number of steps: endTime far away, stopAt writeNow after the steps
        control["stopAt"] = "endTime"
        control["endTime"] = 1e9
    if end is not None:
        control["endTime"] = end


def cmd_scale(args) -> None:
    """~args.steps time steps at each process count, from the same start, nothing else running; the wall time per
    step over the steps after the first 20 (start-up and first-step costs left out)."""
    from vortexcfd.foam.logparse import parse_log_text

    case = WORK / "case"
    rows = []
    for procs in args.procs:
        build_files(case, procs)
        from foamlib import FoamFile

        control = FoamFile(case / "system" / "controlDict")
        control["stopAt"] = "endTime"
        control["endTime"] = 1e9
        control["writeInterval"] = 1e9
        foam(case, "decomposePar -force", "log.decomposePar")
        log = case / f"log.scale{procs}"
        t0 = time.monotonic()
        with open(log, "w") as out:
            proc = subprocess.Popen([*FOAM, f"mpirun -np {procs} pimpleFoam -parallel"], cwd=case, stdout=out,
                                    stderr=subprocess.STDOUT)
            while proc.poll() is None:
                time.sleep(2)
                text = log.read_text(errors="replace")
                if text.count("\nTime = ") >= args.steps + 1:
                    subprocess.run(["pkill", "-f", "pimpleFoam -parallel"])
                    break
            proc.wait()
        wall = time.monotonic() - t0
        steps = parse_log_text(log.read_text(errors="replace")).time_steps
        clocks = [s.execution_time for s in steps if s.execution_time is not None]
        n = len(clocks)
        per_step = (clocks[-1] - clocks[20]) / (n - 21) if n > 30 else None
        rows.append({"procs": procs, "steps": n, "wall_s": round(wall, 1), "s_per_step": per_step,
                     "dt_last": steps[-1].delta_t if steps else None})
        say(f"{procs} processes: {n} steps, {per_step} s per step (after the first 20)")
    cells = json.loads((WORK / "mesh.json").read_text())["cells"]
    base = rows[0]
    for r in rows:
        r["s_per_step_per_Mcell"] = r["s_per_step"] / (cells / 1e6) if r["s_per_step"] else None
        r["speedup_vs_first"] = base["s_per_step"] / r["s_per_step"] if r["s_per_step"] else None
        r["efficiency_vs_first"] = r["speedup_vs_first"] * base["procs"] / r["procs"] if r["s_per_step"] else None
    (WORK / "scaling.json").write_text(json.dumps({"cells": cells, "rows": rows}, indent=2) + "\n")
    say(f"wrote {WORK / 'scaling.json'}")


def cmd_run(args) -> None:
    """The run through SolverRun (the app's transient run: perturbation, detection, statistics)."""
    from vortexcfd.foam.solver_run import SolverRun

    case = WORK / "case"
    build_files(case, args.procs)
    t0 = time.monotonic()
    run = SolverRun(case, cores=args.procs, timeout_s=14 * 3600,
                    on_line=lambda line: line.startswith("Start-up transient") and say(line.strip()))
    run.start()
    result = run.wait()
    seconds = time.monotonic() - t0
    tr = result.transient or {}
    stats = tr.get("statistics") or {}
    out = {"state": result.state, "procs": args.procs, "solve_s": round(seconds, 1), "transient": tr}
    (WORK / "run.json").write_text(json.dumps(out, indent=2) + "\n")
    say(f"run: {result.state} after {tr.get('steps')} steps to t = {tr.get('end_time')} in {seconds:.0f} s; "
        f"sampling from {tr.get('sampling_start')}; St {stats.get('strouhal')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(func=cmd_build)
    scale = sub.add_parser("scale")
    scale.add_argument("--procs", type=int, nargs="+", default=[4, 6, 8, 10, 12])
    scale.add_argument("--steps", type=int, default=200)
    scale.set_defaults(func=cmd_scale)
    run = sub.add_parser("run")
    run.add_argument("--procs", type=int, required=True)
    run.set_defaults(func=cmd_run)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
