"""OpenFOAM case directory writer."""

from __future__ import annotations

import signal
from dataclasses import dataclass
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
    result["system/controlDict"] = FoamFileSpec(
        content=new_content,
        class_name=cd_spec.class_name,
    )
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
    result["system/controlDict"] = FoamFileSpec(content=content, class_name=spec.class_name)
    return result


class CaseDirectoryNotEmptyError(FileExistsError):
    """Raised when attempting to write a case into a non-empty directory."""


@dataclass
class FoamFileSpec:
    """Specification of an OpenFOAM file including its body content and header class."""

    content: dict[str, Any]
    class_name: str = "dictionary"


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

        write_foam_file(
            target_file,
            spec.content,
            object_name=rel_path.name,
            class_name=spec.class_name,
        )
