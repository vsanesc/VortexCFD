"""Thin wrapper around foamlib for reading and writing OpenFOAM dictionary files.

foamlib conventions relied upon:
- A tuple is serialized as space-separated tokens without parentheses,
  e.g. ("Gauss", "linear") -> "Gauss linear".
- A list is serialized as parenthesized tokens,
  e.g. [1.0, 0.0, 0.0] -> "(1.0 0.0 0.0)".
- read_foam_file returns a dict whose values may be tuples, numpy arrays,
  DimensionSet objects, etc. (not only primitive types).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from foamlib import FoamFile


def read_foam_file(path: Path | str) -> dict[str, Any]:
    """Read an OpenFOAM dictionary file into a Python dictionary.

    Note that the returned dictionary values are not limited to plain primitive
    types: they may contain tuples (for multi-token keywords), DimensionSet
    objects, or NumPy ndarrays (for field data).

    Args:
        path: Path to the OpenFOAM file.

    Returns:
        Dictionary representing the file content (excluding FoamFile header).
    """
    file_path = Path(path)
    return FoamFile(file_path).as_dict()


def write_foam_file(
    path: Path | str,
    content: Mapping[str, Any],
    *,
    object_name: str,
    class_name: str = "dictionary",
) -> None:
    """Write an OpenFOAM dictionary file with a valid FoamFile header and content.

    Args:
        path: Target filesystem path where the file will be written.
        content: Dictionary containing the body of the OpenFOAM file.
        object_name: Value for the FoamFile header's 'object' entry.
        class_name: Value for the FoamFile header's 'class' entry (default: "dictionary").
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if file_path.exists():
        file_path.unlink()

    with FoamFile(file_path) as ff:
        ff.class_ = class_name
        ff.object_ = object_name
        for k, v in content.items():
            ff[k] = v


def set_foam_entry(
    path: Path | str,
    key: str,
    value: Any,
) -> None:
    """Edit a single entry in an existing OpenFOAM dictionary file in place.

    Uses foamlib's native in-place editing (FoamFile.__setitem__) to modify
    just the specified key without rewriting the whole file.

    Args:
        path: Path to the existing OpenFOAM file.
        key: Top-level keyword to set.
        value: New value for the keyword.
    """
    file_path = Path(path)
    ff = FoamFile(file_path)
    ff[key] = value
