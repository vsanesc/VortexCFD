"""Optional local-only benchmark cases (D-094). No Qt.

The cases are read from benchmarks/local_cases.json, which is git-ignored: they use geometry the
owner keeps outside the repository (never copied, committed or embedded). The committed
benchmarks/local_cases.example.json documents the format. A missing config file or geometry file
skips the cases with a message; results of local cases go to benchmarks/results/local/ (git-ignored)
and never into the committed baseline, which stays the three public cases.

Format (JSON):
    {
      "format_version": 1,
      "reference": {                       # the clean model the fidelity is measured against
        "file": "<path>",                  # "~" is expanded; relative paths are relative to the config
        "components": {"<name>": <body index>, ...},
        "l_ref": {"mean_chord": "<component>"},
        "zones": {"band": 0.05, "junctions": {"<zone>": "<component>", ...},
                  "trailing_edge": "<component>", "tips": "<component>"}
      },
      "defaults": {"import_mode": "parts", "inflow": {...}, "mesh": {...}, "domain": {...}},
      "cases": [
        {"name": "<name>", "file": "<path>", "description": "...", "solve": false,
         "surface_prep": null | "intersection_features" | "cad_union", ...}
      ]
    }
Every case field overrides the defaults; "mesh", "inflow" and "domain" are merged key by key.
"""

import json
import os
import re
from pathlib import Path

from vortexcfd.bench.cases import CASES, BenchCase

CONFIG = Path("benchmarks") / "local_cases.json"
EXAMPLE = Path("benchmarks") / "local_cases.example.json"
FORMAT_VERSION = 1
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
STRATEGIES = (None, "intersection_features", "cad_union")
IMPORT_MODES = ("regions", "parts")


def work_root() -> Path:
    """Where local cases put their projects and the reference cache: <XDG cache>/vortexcfd/bench_local
    (~/.cache by default), outside the repository, because the projects hold copies of the owner's
    geometry and its tessellations (never inside the repository, not even git-ignored)."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "vortexcfd" / "bench_local"


class LocalConfigError(ValueError):
    """The local config is invalid; the message says why."""


def _path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path)


def load_local_cases(root: Path, config: Path | None = None) -> tuple[dict[str, BenchCase], list[str]]:
    """(cases by name, messages about what was skipped). A missing config gives no cases and one
    message; a case whose geometry or reference file is missing is skipped with a message.

    Raises:
        LocalConfigError: the file exists but is not a valid config.
    """
    path = Path(config) if config is not None else Path(root) / CONFIG
    if not path.is_file():
        return {}, [f"no local cases: {path} not found (format: {EXAMPLE})"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        raise LocalConfigError(f"{path}: format_version must be {FORMAT_VERSION}")
    base = path.parent
    ref = data.get("reference") or {}
    defaults = data.get("defaults") or {}
    cases, messages = {}, []
    ref_file = _path(ref["file"], base) if ref.get("file") else None
    for raw in data.get("cases") or []:
        entry = {**defaults, **raw}
        for key in ("mesh", "inflow", "domain"):
            entry[key] = {**(defaults.get(key) or {}), **(raw.get(key) or {})}
        name = entry.get("name", "")
        if not NAME_RE.match(str(name)) or name in CASES:
            raise LocalConfigError(f"{path}: invalid or reserved case name {name!r}")
        if entry.get("surface_prep") not in STRATEGIES:
            raise LocalConfigError(f"{path}: case {name}: unknown surface_prep {entry.get('surface_prep')!r}")
        if entry.get("import_mode", "parts") not in IMPORT_MODES:
            raise LocalConfigError(f"{path}: case {name}: unknown import_mode {entry.get('import_mode')!r}")
        source = _path(entry["file"], base) if entry.get("file") else None
        if source is None or not source.is_file():
            messages.append(f"local case {name} skipped: geometry file {source} not found")
            continue
        if ref_file is None or not ref_file.is_file():
            messages.append(f"local case {name} skipped: reference file {ref_file} not found")
            continue
        cases[name] = BenchCase(
            name=name, geometry=name, units=entry.get("units", "m"), reference_length=0.0,
            description=entry.get("description", f"local case {name}"),
            mesh=dict(entry["mesh"]), inflow=dict(entry["inflow"]), domain=dict(entry["domain"]),
            reports=dict(entry.get("reports") or {}),
            local=True, source=str(source), import_mode=entry.get("import_mode", "parts"), reference=str(ref_file),
            reference_spec={k: ref.get(k) for k in ("components", "l_ref", "zones")},
            surface_prep=entry.get("surface_prep"), solve=bool(entry.get("solve", False)),
        )
    return cases, messages
