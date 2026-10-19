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


def _worker(name: str, out_file: Path, root: Path, solve: bool) -> int:
    from vortexcfd.bench.runner import run_case

    case = CASES[name]
    try:
        result = run_case(case, root / "run" / "bench", root / "benchmarks" / "geometries", solve=solve)
    except Exception as exc:  # a crash is a benchmark result, not a reason to lose the others
        result = {"case": name, "description": case.description, "failed": True,
                  "failure": f"{type(exc).__name__}: {exc}"}
    cores = (result.get("yplus") or {}).get("cores")
    result["deviations"] = deviations(case, cores)
    out_file.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


def run_cases(names: list[str], root: Path, solve: bool) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            out = Path(tmp) / f"{name}.json"
            code = subprocess.run([sys.executable, "-m", "vortexcfd.bench", "--worker", name, "--worker-out", str(out)]
                                  + ([] if solve else ["--no-solve"]), cwd=root).returncode
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
    parser = argparse.ArgumentParser(prog="python -m vortexcfd.bench", description="Meshing benchmark (D-082).")
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), help="cases to run (default: all)")
    parser.add_argument("--compare", type=Path, help="an earlier result file to compare with")
    parser.add_argument("--result", type=Path, help="compare this existing result instead of running")
    parser.add_argument("--no-solve", action="store_true", help="mesh only (no indicative y+ run)")
    parser.add_argument("--out", type=Path, help="result folder (default benchmarks/results)")
    parser.add_argument("--generate", action="store_true", help="only (re)generate the geometries")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = repo_root()
    if args.worker:
        return _worker(args.worker, args.worker_out, root, not args.no_solve)
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
        now = datetime.now(timezone.utc)
        start = time.monotonic()
        cases = run_cases(names, root, not args.no_solve)
        new = {"meta": {"stamp": now.strftime("%Y%m%dT%H%M%SZ"), "utc": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "git_sha": git_sha(root), "cases": names, "solve": not args.no_solve,
                        "physical_cores": physical_cores(), "wall_s": time.monotonic() - start},
               "cases": cases}
        json_path, md_path = report.write_result(new, args.out or root / "benchmarks" / "results")
        print(f"\nWrote {json_path} and {md_path.name}")
        print(f"Wall-clock {new['meta']['wall_s']:.0f} s\n")
    print(report.markdown_table(new))
    if args.compare is not None:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        return print_compare(old, new, str(args.compare))
    return 0
