"""Locating OpenFOAM ESI v2606 at start-up (D-137, no Qt).

Order: the ``VORTEXCFD_OPENFOAM_BASHRC`` environment variable, the bashrc path the user configured (a small JSON file
in the user's configuration folder, so the command line check needs no Qt), then the standard ESI locations. A
bashrc is accepted when it declares ``WM_PROJECT_VERSION=v2606`` and its installation has the solver and mesher
binaries (simpleFoam, snappyHexMesh, blockMesh under platforms/*/bin). Nothing is run and nothing is installed: the
install commands are text for the user (the official ESI Debian/Ubuntu repository).
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from vortexcfd.core.atomic_io import write_text_atomic
from vortexcfd.core.user_dirs import settings_dir

VERSION = "v2606"
BASHRC_ENV = "VORTEXCFD_OPENFOAM_BASHRC"
CONFIG_NAME = "openfoam.json"
REQUIRED_BINARIES = ("simpleFoam", "snappyHexMesh", "blockMesh")
# The standard ESI locations: the Debian/Ubuntu packages, then the usual source / tarball installs.
STANDARD_BASHRCS = (
    Path("/usr/lib/openfoam/openfoam2606/etc/bashrc"),
    Path("/opt/openfoam2606/etc/bashrc"),
    Path("/opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc"),
    Path("~/OpenFOAM/OpenFOAM-v2606/etc/bashrc"),
)
# Where other OpenFOAM versions are looked for (reported, never used).
OTHER_PATTERNS = (
    ("/usr/lib/openfoam", "openfoam*/etc/bashrc"),
    ("/opt", "openfoam*/etc/bashrc"),
    ("/opt/OpenFOAM", "OpenFOAM-*/etc/bashrc"),
    ("~/OpenFOAM", "OpenFOAM-*/etc/bashrc"),
)
# The official ESI install commands for Ubuntu (https://develop.openfoam.com/Development/openfoam/-/wikis/precompiled/debian):
# shown to the user, never run by the app.
INSTALL_COMMANDS = (
    "curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash\n"
    "sudo apt-get update\n"
    "sudo apt-get install openfoam2606-default"
)
_VERSION_RE = re.compile(r"^\s*(?:export\s+)?WM_PROJECT_VERSION=([^\s;#]+)", re.MULTILINE)


@dataclass(frozen=True)
class Looked:
    """One place looked at and what was found there."""

    path: Path
    source: str  # "environment", "configured" or "standard"
    outcome: str  # "found", or why it is not usable


@dataclass
class OpenFOAMCheck:
    bashrc: Path | None  # the usable v2606 bashrc, None: not found
    looked: list[Looked] = field(default_factory=list)
    others: list[tuple[Path, str]] = field(default_factory=list)  # other versions found (bashrc, version)

    @property
    def ok(self) -> bool:
        return self.bashrc is not None

    def problem(self) -> str | None:
        """None when found, else one line for tooltips."""
        if self.ok:
            return None
        other = f" (found {', '.join(v for _p, v in self.others)} instead)" if self.others else ""
        return f"OpenFOAM {VERSION} was not found{other}: Help > OpenFOAM Installation."

    def text(self) -> str:
        """What was looked for and found, several lines (the dialog and ``vortexcfd --check-openfoam``)."""
        lines = [f"OpenFOAM {VERSION}: " + (f"found at {self.bashrc}" if self.ok else "NOT FOUND")]
        lines += [f"  {item.source}: {item.path}: {item.outcome}" for item in self.looked]
        lines += [f"  other version: {version} at {path}" for path, version in self.others]
        return "\n".join(lines)


def config_path(env=None) -> Path:
    env = os.environ if env is None else env
    isolated = settings_dir(env)  # tests and scripts (core/user_dirs.py)
    if isolated is not None:
        return isolated / "VortexCFD" / CONFIG_NAME
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".config")
    return Path(base) / "VortexCFD" / CONFIG_NAME


def configured_bashrc(env=None) -> Path | None:
    """The bashrc path the user set (None: none, or the file is unreadable)."""
    try:
        value = json.loads(config_path(env).read_text(encoding="utf-8")).get("bashrc")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(value) if isinstance(value, str) and value else None


def set_configured_bashrc(path: Path | None, env=None) -> None:
    """Remember the user's bashrc path (None forgets it)."""
    target = config_path(env)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, json.dumps({"bashrc": str(path) if path else None}, indent=2) + "\n")


def bashrc_version(path: Path) -> str | None:
    """The WM_PROJECT_VERSION a bashrc declares (None: unreadable or not declared)."""
    try:
        match = _VERSION_RE.search(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return match.group(1).strip("'\"") if match else None


def installation_problem(path: Path) -> str | None:
    """Why ``path`` is not a usable OpenFOAM v2606 bashrc (None: it is)."""
    path = Path(path)
    if not path.is_file():
        return "no such file"
    version = bashrc_version(path)
    if version is None:
        return "not an OpenFOAM bashrc (no WM_PROJECT_VERSION)"
    if version != VERSION:
        return f"OpenFOAM {version}, not {VERSION}"
    root = path.parent.parent
    bins = [d for d in (root / "platforms").glob("*/bin") if d.is_dir()]
    missing = [b for b in REQUIRED_BINARIES if not any((d / b).is_file() for d in bins)]
    if missing:
        return f"incomplete installation: {', '.join(missing)} not under {root / 'platforms'}/*/bin"
    return None


def _expand(path: Path, home: str | None) -> Path:
    text = str(path)
    if text.startswith("~") and home:
        return Path(home + text[1:])
    return path.expanduser()


def check_openfoam(configured: Path | None = None, env=None, standard=None, other_patterns=None) -> OpenFOAMCheck:
    """Look for OpenFOAM v2606: the environment variable, ``configured`` (default: the saved path), then
    ``standard`` (default STANDARD_BASHRCS); the first usable bashrc wins. Other versions found are listed
    (default OTHER_PATTERNS)."""
    env = os.environ if env is None else env
    standard = STANDARD_BASHRCS if standard is None else standard
    other_patterns = OTHER_PATTERNS if other_patterns is None else other_patterns
    home = env.get("HOME")
    if configured is None:
        configured = configured_bashrc(env)
    places: list[tuple[Path, str]] = []
    if env.get(BASHRC_ENV):
        places.append((Path(env[BASHRC_ENV]), "environment"))
    if configured is not None:
        places.append((Path(configured), "configured"))
    places += [(_expand(p, home), "standard") for p in standard]
    check = OpenFOAMCheck(None)
    seen = set()
    for path, source in places:
        if path in seen:
            continue
        seen.add(path)
        problem = installation_problem(path)
        check.looked.append(Looked(path, source, problem or "found"))
        if problem is None and check.bashrc is None:
            check.bashrc = path
            break
    for base, pattern in other_patterns:
        root = _expand(Path(base), home)
        if not root.is_dir():
            continue
        for bashrc in sorted(root.glob(pattern)):
            version = bashrc_version(bashrc)
            if version and version != VERSION and (bashrc, version) not in check.others:
                check.others.append((bashrc, version))
    return check


def activate(check: OpenFOAMCheck) -> None:
    """Make the runner source the bashrc found (no-op when none was found)."""
    if check.bashrc is not None:
        from vortexcfd.foam import runner

        runner.set_bashrc(check.bashrc)
