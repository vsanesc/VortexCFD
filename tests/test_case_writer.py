"""Tests for OpenFOAM dictionary I/O, case writer, and cavity reference case."""

from pathlib import Path
import shutil
from typing import Any
from foamlib import FoamFile
import numpy as np
import pytest

import signal
from cfdgui.foam.case_writer import (
    CaseDirectoryNotEmptyError,
    FoamFileSpec,
    enable_clean_stop,
    write_case,
)
from cfdgui.foam.dictfile import read_foam_file, write_foam_file
from cfdgui.foam.reference_cases.cavity import CavityParams, build_cavity_files
from cfdgui.foam.runner import run_foam

TUTORIAL_CAVITY = Path(
    "/usr/lib/openfoam/openfoam2606/tutorials/incompressible/icoFoam/cavity/cavity"
)


def resolve_macros(data: Any, parent: dict[str, Any] | None = None) -> Any:
    """Resolve $name; macro inclusions in dictionary structures.

    A key '$x' with value None means merge the sibling dict 'x', then apply
    other keys of this dict on top.
    Raises ValueError on any other macro construct.
    """
    if isinstance(data, dict):
        resolved: dict[str, Any] = {}
        macro_keys = [k for k in data if isinstance(k, str) and k.startswith("$")]
        other_keys = [k for k in data if not (isinstance(k, str) and k.startswith("$"))]

        for k in macro_keys:
            v = data[k]
            if v is not None:
                raise ValueError(
                    f"Unknown macro construct '{k}': expected None value, got {v!r}"
                )
            if parent is None:
                raise ValueError(f"Macro '{k}' cannot be resolved without a parent context")
            ref_name = k[1:]
            if ref_name not in parent or not isinstance(parent[ref_name], dict):
                raise ValueError(
                    f"Macro reference '{k}' cannot be resolved: sibling '{ref_name}' not found"
                )
            base_dict = resolve_macros(dict(parent[ref_name]), parent)
            resolved.update(base_dict)

        for k in other_keys:
            resolved[k] = resolve_macros(data[k], data)
        return resolved
    elif isinstance(data, list):
        return [resolve_macros(item, parent) for item in data]
    return data


def values_equal(v1: Any, v2: Any) -> bool:
    """Compare two parsed OpenFOAM values handling numpy arrays and nested structures."""
    if isinstance(v1, dict) and isinstance(v2, dict):
        if v1.keys() != v2.keys():
            return False
        return all(values_equal(v1[k], v2[k]) for k in v1)
    if isinstance(v1, (list, tuple)) and isinstance(v2, (list, tuple)):
        if len(v1) != len(v2):
            return False
        return all(values_equal(x, y) for x, y in zip(v1, v2))
    if isinstance(v1, np.ndarray) or isinstance(v2, np.ndarray):
        return bool(np.allclose(v1, v2))
    return bool(v1 == v2)


def test_write_case_creates_files_and_refuses_non_empty_dir(tmp_path: Path) -> None:
    """Verify write_case creates expected files and refuses non-empty directory."""
    case_dir = tmp_path / "test_cavity"
    files = build_cavity_files(CavityParams())

    write_case(case_dir, files)

    for rel_path in files:
        assert (case_dir / rel_path).is_file(), f"Expected file {rel_path} was not created"

    # Attempting to write into non-empty directory must raise error
    with pytest.raises(CaseDirectoryNotEmptyError):
        write_case(case_dir, files)


def test_dictfile_round_trip(tmp_path: Path) -> None:
    """Verify write_foam_file followed by read_foam_file returns equal content."""
    content = {
        "nu": 0.015,
        "simpleList": [1, 2, 3],
        "subDict": {
            "keyA": "valueA",
            "keyB": 42,
        },
    }
    file_path = tmp_path / "testDict"
    write_foam_file(file_path, content, object_name="testDict")

    read_back = read_foam_file(file_path)
    assert read_back == content


def test_written_header_classes(tmp_path: Path) -> None:
    """Verify FoamFile header class of 0/U, 0/p, and system/controlDict."""
    case_dir = tmp_path / "header_case"
    files = build_cavity_files(CavityParams())
    write_case(case_dir, files)

    assert FoamFile(case_dir / "0" / "U").class_ == "volVectorField"
    assert FoamFile(case_dir / "0" / "p").class_ == "volScalarField"
    assert FoamFile(case_dir / "system" / "controlDict").class_ == "dictionary"


def test_written_files_are_multiline_and_end_with_newline(tmp_path: Path) -> None:
    """Verify system/fvSchemes and 0/U contain multiple lines and end with a newline."""
    case_dir = tmp_path / "multiline_case"
    files = build_cavity_files(CavityParams())
    write_case(case_dir, files)

    for rel_path in ("system/fvSchemes", "0/U"):
        file_path = case_dir / rel_path
        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        assert len(lines) > 1, f"{rel_path} was written as a single line"
        assert text.endswith("\n"), f"{rel_path} does not end with a newline"


@pytest.mark.openfoam
def test_reference_cavity_against_tutorial(tmp_path: Path) -> None:
    """Compare generated cavity files dictionary-by-dictionary against the official tutorial."""
    assert TUTORIAL_CAVITY.is_dir(), f"Tutorial not found at {TUTORIAL_CAVITY}"

    params = CavityParams()
    gen_files = build_cavity_files(params)
    case_dir = tmp_path / "gen_case"
    write_case(case_dir, gen_files)

    # Check file set matches tutorial minus excluded files
    tut_files = {
        str(f.relative_to(TUTORIAL_CAVITY))
        for f in TUTORIAL_CAVITY.rglob("*")
        if f.is_file()
    }
    excluded = {"system/PDRblockMeshDict", "system/decomposeParDict"}
    expected_files = tut_files - excluded
    gen_file_set = set(gen_files.keys())

    missing = expected_files - gen_file_set
    extra = gen_file_set - expected_files
    assert gen_file_set == expected_files, (
        f"Generated file set does not match tutorial files (minus {excluded}).\n"
        f"Missing files: {sorted(missing)}\n"
        f"Unexpected extra files: {sorted(extra)}"
    )

    mismatches: list[str] = []

    for rel_path in sorted(gen_files.keys()):
        tut_file = TUTORIAL_CAVITY / rel_path
        gen_file = case_dir / rel_path

        assert tut_file.is_file(), f"Tutorial file {tut_file} does not exist"
        assert gen_file.is_file(), f"Generated file {gen_file} does not exist"

        raw_tut_dict = read_foam_file(tut_file)
        tut_dict = resolve_macros(raw_tut_dict)
        gen_dict = read_foam_file(gen_file)

        # Check for top-level key mismatches
        tut_keys = set(tut_dict.keys())
        gen_keys = set(gen_dict.keys())
        if tut_keys != gen_keys:
            mismatches.append(
                f"{rel_path}: key set mismatch (tutorial keys: {tut_keys}, generated keys: {gen_keys})"
            )

        # Compare values key-by-key
        for key in tut_keys.intersection(gen_keys):
            if not values_equal(tut_dict[key], gen_dict[key]):
                mismatches.append(
                    f"{rel_path} [{key}]: mismatch\n"
                    f"  tutorial:  {tut_dict[key]!r}\n"
                    f"  generated: {gen_dict[key]!r}"
                )

    assert not mismatches, "Mismatches found between reference tutorial and generated cavity:\n" + "\n".join(mismatches)


@pytest.mark.openfoam
def test_end_to_end_cavity_simulation(tmp_path: Path) -> None:
    """Verify numerical equivalence between unmodified tutorial run and generated cavity."""
    assert TUTORIAL_CAVITY.is_dir(), f"Tutorial not found at {TUTORIAL_CAVITY}"

    # 1. Run unmodified tutorial reference copy
    ref_case = tmp_path / "ref_cavity"
    shutil.copytree(TUTORIAL_CAVITY, ref_case)

    ref_bm = run_foam(["blockMesh"], case_dir=ref_case, log_file=ref_case / "log.blockMesh")
    assert ref_bm == 0, f"Tutorial blockMesh failed with exit code {ref_bm}"

    ref_ico = run_foam(["icoFoam"], case_dir=ref_case, log_file=ref_case / "log.icoFoam")
    assert ref_ico == 0, f"Tutorial icoFoam failed with exit code {ref_ico}"

    # 2. Run generated cavity case
    gen_case = tmp_path / "gen_cavity"
    files = build_cavity_files(CavityParams())
    write_case(gen_case, files)

    gen_bm = run_foam(["blockMesh"], case_dir=gen_case, log_file=gen_case / "log.blockMesh")
    assert gen_bm == 0, f"Generated blockMesh failed with exit code {gen_bm}"

    gen_ico = run_foam(["icoFoam"], case_dir=gen_case, log_file=gen_case / "log.icoFoam")
    assert gen_ico == 0, f"Generated icoFoam failed with exit code {gen_ico}"

    # 3. Compare final-time results (time = 0.5)
    ref_p_data = read_foam_file(ref_case / "0.5" / "p")
    gen_p_data = read_foam_file(gen_case / "0.5" / "p")
    assert np.allclose(ref_p_data["internalField"], gen_p_data["internalField"])

    ref_u_data = read_foam_file(ref_case / "0.5" / "U")
    gen_u_data = read_foam_file(gen_case / "0.5" / "U")
    assert np.abs(gen_u_data["internalField"]).max() > 0.0
    assert np.allclose(ref_u_data["internalField"], gen_u_data["internalField"])


def test_param_change_updates_transport_properties(tmp_path: Path) -> None:
    """Verify that changing CavityParams updates the written transportProperties on disk."""
    case_dir = tmp_path / "case"
    files = build_cavity_files(CavityParams(nu=0.035))
    write_case(case_dir, files)

    read_back = read_foam_file(case_dir / "constant" / "transportProperties")
    assert read_back["nu"] == 0.035


def test_macro_resolver_raises_on_unknown_construct() -> None:
    """Verify resolve_macros raises ValueError on unsupported macro syntax."""
    with pytest.raises(ValueError, match="expected None value"):
        resolve_macros({"$foo": "bar"}, parent={"foo": {}})

    with pytest.raises(ValueError, match="without a parent context"):
        resolve_macros({"$foo": None}, parent=None)

    with pytest.raises(ValueError, match="sibling 'foo' not found"):
        resolve_macros({"$foo": None}, parent={"other": {}})


def test_enable_clean_stop_helper() -> None:
    """Verify enable_clean_stop adds stopAtWriteNowSignal to OptimisationSwitches."""
    files = {
        "system/controlDict": FoamFileSpec(
            content={"application": "icoFoam", "startFrom": "startTime"},
            class_name="dictionary",
        ),
        "0/U": FoamFileSpec(content={"dimensions": [0, 1, -1, 0, 0, 0, 0]}),
    }
    modified = enable_clean_stop(files)

    # Original dict must be unchanged
    assert "OptimisationSwitches" not in files["system/controlDict"].content

    # Modified dict must have OptimisationSwitches with stopAtWriteNowSignal
    cd_mod = modified["system/controlDict"].content
    assert "OptimisationSwitches" in cd_mod
    assert cd_mod["OptimisationSwitches"]["stopAtWriteNowSignal"] == int(signal.SIGUSR1)
    assert modified["0/U"] == files["0/U"]

    # If OptimisationSwitches already existed, existing keys are preserved
    files_with_opt = {
        "system/controlDict": FoamFileSpec(
            content={
                "application": "icoFoam",
                "OptimisationSwitches": {"fileModificationSkew": 0},
            },
            class_name="dictionary",
        )
    }
    modified2 = enable_clean_stop(files_with_opt)
    cd2_switches = modified2["system/controlDict"].content["OptimisationSwitches"]
    assert cd2_switches["fileModificationSkew"] == 0
    assert cd2_switches["stopAtWriteNowSignal"] == int(signal.SIGUSR1)

    # Missing system/controlDict raises KeyError
    with pytest.raises(KeyError, match="system/controlDict"):
        enable_clean_stop({"0/U": files["0/U"]})
