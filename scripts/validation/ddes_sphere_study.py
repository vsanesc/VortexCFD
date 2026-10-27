"""DDES functional run (task 1.1-transient Part 2, Part B 3b; docs/validation/ddes_sphere/SETUP.md): a sphere at
Re 10,000 with k-omega SST DDES through the app's workflow layer, and its cost (per cell and time step, memory).

    nice -n 15 .venv/bin/python scripts/validation/ddes_sphere_study.py [--mesh-only] [--end 40] [--cores 8]

The project goes to run/validation/ddes_sphere/ (git-ignored); the record to docs/validation/ddes_sphere/run.json.
The meshing and solving steps are the cylinder driver's; the peak memory of the solver processes is sampled.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("cylinder_study", Path(__file__).with_name("cylinder_study.py"))
cylinder_study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cylinder_study)

from tests.validation import sphere_ddes_case as dc  # noqa: E402
from vortexcfd.workflow import solving  # noqa: E402

WORK = ROOT / "run" / "validation" / "ddes_sphere"
OUT = ROOT / "docs" / "validation" / "ddes_sphere"
say = cylinder_study.say


def rss_sampler(stop: threading.Event, peak: list[float]) -> None:
    """The largest summed resident memory (GB) of the pimpleFoam processes, every 5 s."""
    while not stop.wait(5.0):
        out = subprocess.run(["ps", "-C", "pimpleFoam", "-o", "rss="], capture_output=True, text=True).stdout
        total = sum(int(v) for v in out.split()) / 1024 ** 2
        peak[0] = max(peak[0], total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", type=float, default=dc.END_TIME)
    parser.add_argument("--cores", type=int, default=dc.CORES)
    parser.add_argument("--mesh-only", action="store_true")
    args = parser.parse_args()
    project = dc.build_project(WORK, end_time=args.end, cores=args.cores)
    say(f"sphere DDES: mesh warning: {solving.ddes_mesh_warning(project)}")
    out = {"mesh": cylinder_study.mesh(project)}
    if not args.mesh_only:
        stop, peak = threading.Event(), [0.0]
        sampler = threading.Thread(target=rss_sampler, args=(stop, peak), daemon=True)
        sampler.start()
        out["solve"] = cylinder_study.solve(project)
        stop.set()
        cells, steps, seconds = out["mesh"]["cells"], out["solve"]["steps"], out["solve"]["solve_s"]
        out["cost"] = {"peak_rss_gb": round(peak[0], 2), "cores": args.cores,
                       "s_per_step": seconds / steps if steps else None,
                       "us_per_cell_step_wall": 1e6 * seconds / (cells * steps) if steps else None,
                       "us_per_cell_step_core": 1e6 * seconds * args.cores / (cells * steps) if steps else None}
        say(f"cost: {out['cost']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run.json").write_text(json.dumps(out, indent=2) + "\n")
    say(f"wrote {OUT / 'run.json'}")


if __name__ == "__main__":
    main()
