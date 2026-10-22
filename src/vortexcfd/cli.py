"""The ``vortexcfd`` command (D-137): ``--version`` and ``--check-openfoam`` answer without Qt (the install script
and a terminal without a display use them); anything else starts the GUI (``vortexcfd [project]``)."""

import sys

from vortexcfd import __version__

USAGE = """usage: vortexcfd [project.vcfd]
       vortexcfd --version          print the version
       vortexcfd --check-openfoam   look for OpenFOAM v2606 (exit code 0 when found)"""


def check_openfoam_main() -> int:
    from vortexcfd.foam.installation import INSTALL_COMMANDS, check_openfoam

    check = check_openfoam()
    print(check.text())
    if not check.ok:
        print("\nInstall it with the official ESI packages (needs sudo; the app never runs these):")
        print("\n".join(f"    {line}" for line in INSTALL_COMMANDS.splitlines()))
        print("or set VORTEXCFD_OPENFOAM_BASHRC to its etc/bashrc.")
    return 0 if check.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"vortexcfd {__version__}")
        return 0
    if "--check-openfoam" in args:
        return check_openfoam_main()
    if "-h" in args or "--help" in args:
        print(USAGE)
        return 0
    from vortexcfd.gui.main_window import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
