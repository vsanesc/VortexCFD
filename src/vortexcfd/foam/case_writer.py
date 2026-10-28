"""OpenFOAM case directory writer."""

from __future__ import annotations

import re
import signal
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vortexcfd.foam.dictfile import write_foam_file


def enable_clean_stop(files: dict[str, FoamFileSpec]) -> dict[str, FoamFileSpec]:
    """Return a copy of files with OptimisationSwitches { stopAtWriteNowSignal } added to system/controlDict.

    Placed in case_writer.py alongside FoamFileSpec to keep case file dict transformations cohesive.

    Args:
        files: Mapping of relative case file paths to FoamFileSpec objects.

    Returns:
        A copy of files with stopAtWriteNowSignal configured for clean signal-based stopping.

    Raises:
        KeyError: If 'system/controlDict' is not present in files.
    """
    if "system/controlDict" not in files:
        raise KeyError("'system/controlDict' not found in case files")

    result = dict(files)
    cd_spec = files["system/controlDict"]
    new_content = dict(cd_spec.content)
    opt_switches = dict(new_content.get("OptimisationSwitches", {}))
    opt_switches["stopAtWriteNowSignal"] = int(signal.SIGUSR1)
    new_content["OptimisationSwitches"] = opt_switches
    result["system/controlDict"] = replace(cd_spec, content=new_content)
    return result


# The signal of "Write fields now" (D-172): OpenFOAM writes the fields at the end of the next iteration and goes on.
# SIGUSR2: the clean stop's SIGUSR1 must differ (v2606 refuses the same number for both, sigStopAtWriteNow::set).
WRITE_NOW_SIGNAL = int(signal.SIGUSR2)


def enable_write_now(files: dict[str, FoamFileSpec]) -> dict[str, FoamFileSpec]:
    """A copy of ``files`` with OptimisationSwitches { writeNowSignal 12 } in system/controlDict (runs started from the
    app only, D-172: the benchmark's and the validation drivers' dictionaries do not change)."""
    result = dict(files)
    spec = files["system/controlDict"]
    content = dict(spec.content)
    switches = dict(content.get("OptimisationSwitches", {}))
    switches["writeNowSignal"] = WRITE_NOW_SIGNAL
    content["OptimisationSwitches"] = switches
    result["system/controlDict"] = replace(spec, content=content)
    return result


class CaseDirectoryNotEmptyError(FileExistsError):
    """Raised when attempting to write a case into a non-empty directory."""


@dataclass
class FoamFileSpec:
    """Specification of an OpenFOAM file including its body content and header class."""

    content: dict[str, Any]
    class_name: str = "dictionary"
    # A comment block written under the FoamFile header, each line prefixed "// " (a declared start-up perturbation,
    # D-198); None: none.
    comment: str | None = None
    # The body written verbatim instead of ``content``: OpenFOAM syntax foamlib does not write (setExprFields'
    # #{ ... #} expressions, D-198); None: ``content``.
    text: str | None = None


def comment_block(comment: str) -> str:
    """``comment`` as C++ line comments, one "// " per line."""
    return "\n".join(("// " + line).rstrip() for line in comment.splitlines()) + "\n"


_HEADER = re.compile(r"FoamFile\s*\{[^}]*\}\s*")


def insert_comment(path: Path | str, comment: str) -> None:
    """Put ``comment`` (comment_block) right under the FoamFile header of the file at ``path``."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    found = _HEADER.search(text)
    at = found.end() if found else 0
    path.write_text(text[:at] + comment_block(comment) + "\n" + text[at:], encoding="utf-8")


def write_spec(path: Path | str, spec: FoamFileSpec, object_name: str | None = None) -> None:
    """Write one case file from its spec: ``content`` through foamlib (dictfile.write_foam_file), or ``text``
    verbatim under a FoamFile header; then the spec's comment block under the header."""
    path = Path(path)
    name = object_name or path.name
    if spec.text is None:
        write_foam_file(path, spec.content, object_name=name, class_name=spec.class_name)
        if spec.comment:
            insert_comment(path, spec.comment)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {spec.class_name};\n"
              f"    object {name};\n}}\n\n")
    path.write_text(header + (comment_block(spec.comment) + "\n" if spec.comment else "") + spec.text,
                    encoding="utf-8")


def write_case(case_dir: Path | str, files: dict[str, FoamFileSpec]) -> None:
    """Write an OpenFOAM case directory from a mapping of relative paths and FoamFileSpecs.

    Args:
        case_dir: Target directory for the case.
        files: Mapping of relative file paths (e.g. 'system/controlDict') to FoamFileSpec objects.

    Raises:
        CaseDirectoryNotEmptyError: If case_dir already exists and contains files.
    """
    case_path = Path(case_dir)

    if case_path.exists():
        if any(case_path.iterdir()):
            raise CaseDirectoryNotEmptyError(
                f"Target case directory is not empty: '{case_path}'"
            )
    else:
        case_path.mkdir(parents=True, exist_ok=True)

    for rel_path_str, spec in files.items():
        rel_path = Path(rel_path_str)
        target_file = case_path / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        write_spec(target_file, spec, rel_path.name)
