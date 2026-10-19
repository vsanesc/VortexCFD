"""cfMesh evaluation case (phase 5.3, benchmark only): availability, dictionaries, combined surface."""

from pathlib import Path

import pytest

from vortexcfd.foam.cfmesh_case import CFMESH_EXECUTABLES, cfmesh_executables
from vortexcfd.foam.runner import OPENFOAM_BASHRC

needs_openfoam = pytest.mark.skipif(not Path(OPENFOAM_BASHRC).is_file(), reason="OpenFOAM v2606 not installed")


@needs_openfoam
def test_cfmesh_executables_are_in_the_v2606_installation():
    found = cfmesh_executables()
    assert set(found) == set(CFMESH_EXECUTABLES)
    missing = [name for name, path in found.items() if path is None]
    assert not missing
    assert "/openfoam2606/" in found["cartesianMesh"]


def test_a_missing_executable_is_none():
    assert cfmesh_executables(("cartesianMesh_does_not_exist",)) == {"cartesianMesh_does_not_exist": None}
