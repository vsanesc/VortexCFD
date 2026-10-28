"""Diagnostics of the square cylinder's measurement C (task 1.1-transient, Part 2 closing brief, owner's addendum;
docs/validation/square_re22000/SETUP.md, "Diagnostics of measurement C"). The rules were committed before the runs.

    nice -n 15 .venv/bin/python scripts/validation/square_diagnostics.py restart  # a: Co 2 at 95.8 t_c -> Co 1
    .venv/bin/python scripts/validation/square_diagnostics.py sample              # b: nut/nu, k, I at fixed points
    nice -n 15 .venv/bin/python scripts/validation/square_diagnostics.py rerun    # c: turbOnFinalIterOnly false
    .venv/bin/python scripts/validation/square_diagnostics.py plot                # the lift histories (PNG)

The runs go to run/validation/square_re22000/ (git-ignored), the numbers to docs/validation/square_re22000/, the
figures to ~/vortexcfd-research/1.1-urans-diagnostics/ (outside the repository). At most 6 MPI processes.
"""

import argparse
import dataclasses
import importlib.util
import json
import math
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vortexcfd.core.display_guard import apply_display_guard  # noqa: E402
from vortexcfd.core.user_dirs import isolate_settings  # noqa: E402

apply_display_guard()
isolate_settings()
_spec = importlib.util.spec_from_file_location("cylinder_study", Path(__file__).with_name("cylinder_study.py"))
cylinder_study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cylinder_study)

from tests.validation import square_case as sc  # noqa: E402
from vortexcfd.foam import transient  # noqa: E402
from vortexcfd.foam.case_writer import write_spec  # noqa: E402
from vortexcfd.foam.dictfile import set_foam_entry  # noqa: E402
from vortexcfd.foam.logparse import parse_log_text  # noqa: E402
from vortexcfd.foam.parallel import DECOMPOSE_DICT, decompose_par_dict  # noqa: E402
from vortexcfd.foam.postprocessing import ReportMonitor  # noqa: E402
from vortexcfd.foam.runner import run_foam  # noqa: E402
from vortexcfd.foam.solver_run import ContinueFrom, SolverRun, solver_log  # noqa: E402

WORK = ROOT / "run" / "validation" / "square_re22000"
OUT = ROOT / "docs" / "validation" / "square_re22000"
FIGURES = Path.home() / "vortexcfd-research" / "1.1-urans-diagnostics"
SWITCH = "95.81674986"  # the PIMPLE Co 2 run's sampling-switch time (t_c = 1 s)
CORES = 6
say = cylinder_study.say


def _summary(case: Path, result, seconds: float) -> dict:
    steps = parse_log_text(solver_log(case).read_text(errors="replace")).time_steps
    courant = [s.courant_max for s in steps if s.courant_max is not None]
    tr = result.transient or {}
    stats = tr.get("statistics") or {}
    c = stats.get("coefficients") or {}
    say(f"{case.parent.name}: {result.state} to t = {tr.get('end_time')} in {seconds:.0f} s, {len(steps)} steps; "
        f"St {stats.get('strouhal')}, Cd {c.get('Cd', {}).get('mean')}, Cl RMS {c.get('Cl', {}).get('rms')}")
    return {"state": result.state, "steps": len(steps), "solve_s": round(seconds, 1),
            "max_courant": max(courant) if courant else None, "transient": tr}


def cmd_restart(_args) -> None:
    """a: the PIMPLE Co 2 run's fields at its sampling switch, continued to 150 t_c at Co 1 on 6 processes."""
    src, dst = WORK / "coarse", WORK / "coarse_restart_co1"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in ("square.json", "square.dat", "geometry"):
        (shutil.copytree if (src / name).is_dir() else shutil.copy2)(src / name, dst / name)
    case, origin = dst / "case", src / "case"
    for name in ("constant", "system", "0"):
        shutil.copytree(origin / name, case / name)
    for name in (".vortexcfd-case", "vortexcfd_mesh.json", "vortexcfd_domain.json", "case.foam"):
        if (origin / name).exists():
            shutil.copy2(origin / name, case / name)
    for proc in sorted(origin.glob("processor*")):
        for name in ("constant", SWITCH):
            shutil.copytree(proc / name, case / proc.name / name)
    code = run_foam(["reconstructPar", "-time", SWITCH], case, case / "log.reconstructPar")
    if code != 0 or not (case / SWITCH / "U").is_file():
        raise SystemExit(f"reconstructPar -time {SWITCH} failed ({code}): see {case / 'log.reconstructPar'}")
    for proc in case.glob("processor*"):
        shutil.rmtree(proc)
    control_dict = case / "system" / "controlDict"
    for key, value in (("startFrom", "latestTime"), ("endTime", 150.0), ("maxCo", 1.0),
                       ("writeInterval", transient.even_interval(150.0 - float(SWITCH), 150.0))):
        set_foam_entry(control_dict, key, value)
    write_spec(case / DECOMPOSE_DICT, decompose_par_dict(CORES))
    control = transient.read_control(case)
    transient.write_control(case, dataclasses.replace(control, end_time=150.0, max_courant=1.0))
    before = parse_log_text((origin / "log.pimpleFoam").read_text(errors="replace")).time_steps
    done = sum(1 for s in before if s.time <= float(SWITCH) + 1e-9)
    t0 = time.monotonic()
    run = SolverRun(case, cores=CORES, timeout_s=8 * 3600,
                    resume=ContinueFrom(done, (), reuse_decomposition=False, reconstruct_first=False))
    run.start()
    result = run.wait()
    out = {"source": str(src), "restart_time": float(SWITCH), "steps_before": done,
           "solve": _summary(case, result, time.monotonic() - t0)}
    (WORK / f"{dst.name}.json").write_text(json.dumps(out, indent=2) + "\n")


def cmd_rerun(_args) -> None:
    """c: C exactly, with PIMPLE { turbOnFinalIterOnly false; } written into the case (diagnostic only)."""
    folder = WORK / "coarse_pimple_co1_turball"
    project = sc.build_project(folder, "coarse", end_time=150.0, cores=CORES, algorithm="pimple", max_courant=1.0,
                               perturb=True, sampling_start=96.0)
    project.update_mesh(cores=CORES)
    project.save()
    mesh = cylinder_study.mesh(project)

    def turbulence_every_outer(case: Path) -> None:
        set_foam_entry(case / "system" / "fvSolution", ("PIMPLE", "turbOnFinalIterOnly"), False)

    solve = cylinder_study.solve(project, timeout_s=8 * 3600, before_run=turbulence_every_outer)
    out = {"level": "coarse", "settings": {"algorithm": "pimple", "max_courant": 1.0, "perturb": True,
                                           "sampling_start": 96.0, "turbOnFinalIterOnly": False},
           "mesh": mesh, "solve": solve}
    (WORK / f"{folder.name}.json").write_text(json.dumps(out, indent=2) + "\n")


# b: the points (x, z) in D on the centre line, and the runs' written times sampled.
POINTS = {"upstream x=-10": (-10.0, 0.0), "upstream x=-3": (-3.0, 0.0), "upstream x=-1": (-1.0, 0.0),
          "front face x=-0.05": (-0.05, 0.0), "near wake x=1.5": (1.5, 0.0), "near wake x=2": (2.0, 0.0),
          "near wake x=3": (3.0, 0.0)}
# PIMPLE Co 2 at the switch: its fields as reconstructed into diagnostic a's case (an unchanged copy; this VTK's
# OpenFOAM reader cannot read a decomposed case).
SAMPLES = (("PIMPLE Co 1 (C)", "coarse_pimple_co1", "150"), ("PISO Co 1", "coarse_piso_window", "150"),
           ("PIMPLE Co 2", "coarse_restart_co1", SWITCH), ("PIMPLE Co 2", "coarse", "200"))
BETA_STAR, BETA = 0.09, 0.0828  # k-omega SST: beta* and the far-field beta2 (v2606 kOmegaSSTBase)


def cmd_sample(_args) -> None:
    """b: nut/nu, k and I = sqrt(2k/3)/U at POINTS from the written fields (no solver run)."""
    import numpy as np
    import pyvista as pv
    from vortexcfd.foam.dictfile import read_foam_file

    nu, speed = sc.NU, sc.SPEED
    rows = []
    for label, run, time_name in SAMPLES:
        case = WORK / run / "case"
        foam = case / "case.foam"
        foam.touch()
        reader = pv.OpenFOAMReader(str(foam))
        reader.set_active_time_value(float(time_name))
        reader.enable_all_cell_arrays()
        mesh = reader.read()["internalMesh"]
        centres = mesh.cell_centers().points
        values = {}
        for name, (x, z) in POINTS.items():
            i = int(np.argmin((centres[:, 0] - x) ** 2 + (centres[:, 2] - z) ** 2))
            k = float(mesh.cell_data["k"][i])
            values[name] = {"cell": [round(float(c), 4) for c in centres[i]],
                            "nut_nu": float(mesh.cell_data["nut"][i]) / nu, "k": k,
                            "intensity": math.sqrt(2.0 * k / 3.0) / speed}
        rows.append({"run": label, "folder": run, "time": float(time_name), "points": values})
        say(f"{label} t = {time_name}: " + ", ".join(f"{n}: nut/nu {v['nut_nu']:.3g}, I {100 * v['intensity']:.2f} %"
                                                     for n, v in values.items()))
    k0 = float(read_foam_file(WORK / "coarse_pimple_co1" / "case" / "0" / "k")["internalField"])
    omega0 = float(read_foam_file(WORK / "coarse_pimple_co1" / "case" / "0" / "omega")["internalField"])
    inlet_x = min(float(c) for c in pv.OpenFOAMReader(str(WORK / "coarse_pimple_co1" / "case" / "case.foam"))
                  .read()["internalMesh"].points[:, 0])
    decay = {}
    for name, (x, _z) in POINTS.items():
        if x < 0:  # convected at U from the inlet: omega = omega0 / (1 + beta omega0 t), k = k0 (...)^(-beta*/beta)
            t = (x - inlet_x) / speed
            factor = 1.0 + BETA * omega0 * t
            k = k0 * factor ** (-BETA_STAR / BETA)
            decay[name] = {"t": t, "k": k, "omega": omega0 / factor, "intensity": math.sqrt(2.0 * k / 3.0) / speed,
                           "nut_nu": k / (omega0 / factor) / nu}
    out = {"nu": nu, "speed": speed, "inlet": {"x": inlet_x, "k": k0, "omega": omega0,
                                                 "intensity": math.sqrt(2.0 * k0 / 3.0) / speed,
                                                 "nut_nu": k0 / omega0 / nu},
           "analytic_free_stream_decay": decay, "samples": rows}
    (OUT / "diagnostic_b.json").write_text(json.dumps(out, indent=2) + "\n")
    say(f"wrote {OUT / 'diagnostic_b.json'}")


PLOTS = (("PIMPLE Co 2", "coarse"), ("PIMPLE Co 1 (C)", "coarse_pimple_co1"),
         ("a: Co 2 -> Co 1 at 95.8 t_c", "coarse_restart_co1"), ("c: Co 1, turbOnFinalIterOnly false",
                                                                   "coarse_pimple_co1_turball"),
         ("PISO Co 1", "coarse_piso_window"))


def lift(run: str):
    monitor = ReportMonitor(WORK / run / "case")
    monitor.poll()
    return monitor.series("Cl")


def ranges(series, step: float = 10.0) -> list[tuple[float, float]]:
    """(interval start, lift range) per ``step`` t_c (t_c = 1 s)."""
    import numpy as np

    data = np.array(series)
    out = []
    a = math.floor(data[0, 0] / step) * step
    while a < data[-1, 0] - 1e-9:
        sel = (data[:, 0] >= a) & (data[:, 0] < a + step)
        if sel.sum() > 1:
            out.append((a, float(data[sel, 1].max() - data[sel, 1].min())))
        a += step
    return out


def cmd_plot(_args) -> None:
    import matplotlib

    matplotlib.use("Agg")  # offscreen
    import matplotlib.pyplot as plt
    import numpy as np

    FIGURES.mkdir(parents=True, exist_ok=True)
    table = {}
    fig, axes = plt.subplots(len(PLOTS), 1, figsize=(11, 2.2 * len(PLOTS)), sharex=True)
    for ax, (label, run) in zip(axes, PLOTS):
        if not (WORK / run / "case").is_dir():
            ax.set_title(f"{label}: not run")
            continue
        data = np.array(lift(run))
        table[run] = ranges(data)
        ax.plot(data[:, 0], data[:, 1], lw=0.4, color="#2a6f97")
        ax.set_ylabel("Cl")
        ax.set_title(label, fontsize=9, loc="left")
        ax.set_xlim(0, 150)
        single, sx = plt.subplots(figsize=(11, 3))
        sx.plot(data[:, 0], data[:, 1], lw=0.4, color="#2a6f97")
        sx.set_xlabel("t / t_c")
        sx.set_ylabel("Cl")
        sx.set_title(f"Square cylinder Re 22,000, coarse, 2D URANS: {label}", fontsize=9)
        single.tight_layout()
        single.savefig(FIGURES / f"lift_{run}.png", dpi=130)
        plt.close(single)
    axes[-1].set_xlabel("t / t_c")
    fig.tight_layout()
    fig.savefig(FIGURES / "lift_all.png", dpi=130)
    (OUT / "lift_ranges.json").write_text(json.dumps(table, indent=2) + "\n")
    for run, rows in table.items():
        say(f"{run}: " + " ".join(f"{a:g}:{r:.2f}" for a, r in rows))
    say(f"figures in {FIGURES}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("restart", cmd_restart), ("rerun", cmd_rerun), ("sample", cmd_sample), ("plot", cmd_plot)):
        sub.add_parser(name).set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
