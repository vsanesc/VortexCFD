"""OpenFOAM case directory writer."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cfdgui.foam.dictfile import write_foam_file


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
