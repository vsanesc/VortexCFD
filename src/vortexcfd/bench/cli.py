"""``python -m vortexcfd.bench [--cases ...] [--compare <file>]``: the meshing benchmark (D-082). No Qt.

Each case runs in its own Python process, so the peak memory of its OpenFOAM processes
(getrusage RUSAGE_CHILDREN) belongs to that case alone. Results go to
benchmarks/results/<UTC date and time>_<short git sha>.json and .md (git-ignored); ``--compare``
prints the deltas against another result file and lists the regressions (exit code 1 when there is
one; a slower total time is only flagged).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from vortexcfd.bench import report
from vortexcfd.bench.cases import CASES, deviations
from vortexcfd.bench.local import LocalConfigError, load_local_cases
from vortexcfd.bench.local import work_root as local_work_root
from vortexcfd.core.user_dirs import isolate_settings


def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd()


def git_sha(root: Path) -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _worker(name: str, out_file: Path, root: Path, solve: bool, mesher: str = "snappy", mesh_cores: int = 1) -> int:
    from vortexcfd.bench.runner import run_case

    case = CASES.get(name) or load_local_cases(root)[0][name]
    work = local_work_root() if case.local else root / "run" / "bench"
    try:
        result = run_case(case, work, root / "benchmarks" / "geometries", solve=solve, mesher=mesher,
                          mesh_cores=mesh_cores)
    except Exception as exc:  # a crash is a benchmark result, not a reason to lose the others
        result = {"case": name if mesher == "snappy" else f"{name}_{mesher}", "mesher": mesher,
                  "description": case.description, "failed": True,
                  "failure": f"{type(exc).__name__}: {exc}"}
    cores = (result.get("yplus") or {}).get("cores")
    result["deviations"] = deviations(case, cores)
    out_file.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


def run_cases(names: list[str], root: Path, solve: bool, mesher: str = "snappy", mesh_cores: int = 1) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            out = Path(tmp) / f"{name}.json"
            code = subprocess.run([sys.executable, "-m", "vortexcfd.bench", "--worker", name, "--worker-out", str(out)]
                                  + ([] if solve else ["--no-solve"]) + ["--mesher", mesher]
                                  + ["--mesh-cores", str(mesh_cores)], cwd=root).returncode
            if out.is_file():
                results.append(json.loads(out.read_text(encoding="utf-8")))
            else:
                results.append({"case": name, "failed": True, "failure": f"worker exit code {code}"})
    return results


def print_compare(old: dict, new: dict, old_name: str) -> int:
    deltas, regressions, flags = report.compare(old, new)
    print(f"\nCompared with {old_name}:")
    for line in deltas:
        print(f"  {line}")
    for line in flags:
        print(f"  FLAG {line}")
    for line in regressions:
        print(f"  REGRESSION {line}")
    if not regressions:
        print("  no regressions")
    return 1 if regressions else 0


def main(argv: list[str] | None = None) -> int:
    isolate_settings()  # never the user's settings; the per-case processes inherit it (D-141)
    parser = argparse.ArgumentParser(prog="python -m vortexcfd.bench", description="Meshing benchmark (D-082).")
    parser.add_argument("--cases", nargs="+", help=f"cases to run (default: all public ones: {', '.join(CASES)})")
    parser.add_argument("--local", action="store_true",
                        help="run the local-only cases of benchmarks/local_cases.json (git-ignored; D-094)")
    parser.add_argument("--compare", type=Path, help="an earlier result file to compare with")
    parser.add_argument("--result", type=Path, help="compare this existing result instead of running")
    parser.add_argument("--no-solve", action="store_true", help="mesh only (no indicative y+ run)")
    parser.add_argument("--out", type=Path, help="result folder (default benchmarks/results)")
    parser.add_argument("--generate", action="store_true", help="only (re)generate the geometries")
    parser.add_argument("--mesher", choices=("snappy", "cfmesh"), default="snappy",
                        help="evaluation only (phase 5.3, D-102): mesh with cfMesh's cartesianMesh instead of "
                             "snappyHexMesh; the app always uses snappyHexMesh")
    parser.add_argument("--mesh-cores", type=int, default=1,
                        help="snappyHexMesh ranks (D-111; default 1: serial, comparable with the baseline)")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = repo_root()
    if args.worker:
        return _worker(args.worker, args.worker_out, root, not args.no_solve, args.mesher, args.mesh_cores)
    if args.generate:
        from vortexcfd.bench.geometries import GEOMETRIES, ensure_geometry

        for name in GEOMETRIES:
            print(ensure_geometry(name, root / "benchmarks" / "geometries", force=True))
        return 0
    if args.result is not None:
        new = json.loads(args.result.read_text(encoding="utf-8"))
    else:
        from vortexcfd.foam.parallel import physical_cores

        names = args.cases or list(CASES)
        local = {}
        if args.local:
            try:
                local, messages = load_local_cases(root)
            except LocalConfigError as exc:
                print(f"Local cases: {exc}")
                return 2
            for line in messages:
                print(line)
            names = [n for n in args.cases if n in local] if args.cases else list(local)
            if not names:
                print("No local case to run.")
                return 0
        unknown = [n for n in names if n not in CASES and n not in local]
        if unknown:
            print(f"Unknown case(s): {', '.join(unknown)} (public: {', '.join(CASES)}; local cases need --local)")
            return 2
        now = datetime.now(timezone.utc)
        start = time.monotonic()
        if not 1 <= args.mesh_cores <= physical_cores():
            print(f"--mesh-cores must be between 1 and the {physical_cores()} physical cores")
            return 2
        cases = run_cases(names, root, not args.no_solve, args.mesher, args.mesh_cores)
        new = {"meta": {"stamp": now.strftime("%Y%m%dT%H%M%SZ"), "utc": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "git_sha": git_sha(root), "cases": names, "solve": not args.no_solve,
                        "physical_cores": physical_cores(), "wall_s": time.monotonic() - start,
                        "local": bool(args.local), "mesher": args.mesher, "mesh_cores": args.mesh_cores},
               "cases": cases}
        # Local results never go next to the public ones (D-094): benchmarks/results/local/, git-ignored.
        folder = args.out or root / "benchmarks" / "results" / ("local" if args.local else "")
        json_path, md_path = report.write_result(new, folder)
        print(f"\nWrote {json_path} and {md_path.name}")
        print(f"Wall-clock {new['meta']['wall_s']:.0f} s\n")
    print(report.local_table(new) if new.get("meta", {}).get("local") else report.markdown_table(new))
    if args.compare is not None:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        return print_compare(old, new, str(args.compare))
    return 0
