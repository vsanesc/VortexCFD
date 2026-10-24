#!/usr/bin/env bash
# VortexCFD installer for a fresh WSL2 Ubuntu 24.04 (D-137).
#
#   scripts/install.sh [--prefix DIR] [--check-only] [--no-launcher] [--ignore-os]
#
# What it does, in order (safe to run again: every step is idempotent):
#   1. checks the system: Ubuntu 24.04 (WSL2 expected), Python 3.12 with venv, OpenFOAM ESI v2606;
#   2. when OpenFOAM v2606 is missing, PRINTS the official ESI install commands (it never runs them);
#      reports ParaView, which is optional ("Open in ParaView"; D-138);
#   3. creates (or reuses) a virtual environment in DIR/venv (default ~/.local/share/vortexcfd/venv);
#   4. installs the pinned dependencies (scripts/requirements-v1.txt) and VortexCFD from this checkout;
#   5. checks the import and `vortexcfd --version`, copies the user manual next to the venv;
#   6. creates the launcher ~/.local/bin/vortexcfd and a desktop entry for WSLg;
#   7. runs `vortexcfd --check-openfoam`.
#
# It never uses sudo and never changes anything outside DIR, ~/.local/bin and ~/.local/share/applications.
# When a step needs a system package it stops and prints the command for you to run (with sudo).
#
# Environment: VORTEXCFD_PREFIX (default prefix), PYTHON (default python3), VORTEXCFD_OPENFOAM_BASHRC (an
# OpenFOAM v2606 etc/bashrc outside the standard places), VORTEXCFD_OPENFOAM_SEARCH (a colon-separated list replacing
# the standard places; tests), VORTEXCFD_OS_RELEASE (default /etc/os-release; tests), VORTEXCFD_PARAVIEW_COMMAND
# (default paraview; tests), VORTEXCFD_WINDOWS_PROGRAMS (default /mnt/c/Program Files; tests),
# PIP_* (pip's own settings, e.g. PIP_INDEX_URL or PIP_FIND_LINKS for an offline wheelhouse).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${VORTEXCFD_PREFIX:-$HOME/.local/share/vortexcfd}"
PYTHON="${PYTHON:-python3}"
OS_RELEASE="${VORTEXCFD_OS_RELEASE:-/etc/os-release}"
CHECK_ONLY=0
LAUNCHER=1
IGNORE_OS=0

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --prefix=*) PREFIX="${1#--prefix=}"; shift ;;
        --check-only) CHECK_ONLY=1; shift ;;
        --no-launcher) LAUNCHER=0; shift ;;
        --ignore-os) IGNORE_OS=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 64 ;;
    esac
done

VENV="$PREFIX/venv"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
STANDARD_BASHRCS=(
    "/usr/lib/openfoam/openfoam2606/etc/bashrc"
    "/opt/openfoam2606/etc/bashrc"
    "/opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc"
    "$HOME/OpenFOAM/OpenFOAM-v2606/etc/bashrc"
)
if [ -n "${VORTEXCFD_OPENFOAM_SEARCH:-}" ]; then  # a colon-separated list replacing the standard places (tests)
    IFS=: read -r -a STANDARD_BASHRCS <<< "$VORTEXCFD_OPENFOAM_SEARCH"
fi

step() { printf '\n== %s\n' "$*"; }
ok() { printf '   ok: %s\n' "$*"; }
warn() { printf '   WARNING: %s\n' "$*"; }
fail() { printf '   ERROR: %s\n' "$*" >&2; exit "${2:-1}"; }
needs_root() {  # a command the USER runs; this script only prints it
    printf '   Run this yourself (it needs sudo), then run this script again:\n'
    printf '       %s\n' "$@"
}

# -- 1. the system ---------------------------------------------------------------------------------------------------

step "System"
if [ -r "$OS_RELEASE" ]; then
    # shellcheck disable=SC1090
    OS_ID="$(. "$OS_RELEASE" && echo "${ID:-}")"
    OS_VERSION="$(. "$OS_RELEASE" && echo "${VERSION_ID:-}")"
else
    OS_ID="unknown"; OS_VERSION="unknown"
fi
if [ "$OS_ID" = "ubuntu" ] && [ "$OS_VERSION" = "24.04" ]; then
    ok "Ubuntu $OS_VERSION"
elif [ "$IGNORE_OS" = 1 ]; then
    warn "$OS_ID $OS_VERSION is not Ubuntu 24.04 (continuing: --ignore-os)"
else
    fail "VortexCFD 1.0 supports Ubuntu 24.04 (found: $OS_ID $OS_VERSION). Use --ignore-os to try anyway."
fi
if grep -qi microsoft /proc/version 2>/dev/null; then
    ok "WSL2"
else
    warn "not running under WSL: the launcher is written for WSLg, a Linux desktop works the same way"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    needs_root "sudo apt-get install python3.12 python3.12-venv"
    fail "$PYTHON not found"
fi
PY_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$PY_VERSION" != "3.12" ]; then
    needs_root "sudo apt-get install python3.12 python3.12-venv"
    fail "Python 3.12 is required (found $PYTHON $PY_VERSION; set PYTHON=python3.12)"
fi
ok "Python $PY_VERSION ($(command -v "$PYTHON"))"
if ! "$PYTHON" -c 'import venv, ensurepip' >/dev/null 2>&1; then
    needs_root "sudo apt-get install python3.12-venv"
    fail "the Python venv module is missing"
fi
ok "Python venv module"

# -- 2. OpenFOAM -----------------------------------------------------------------------------------------------------

step "OpenFOAM ESI v2606"
OPENFOAM_BASHRC=""
for candidate in ${VORTEXCFD_OPENFOAM_BASHRC:+"$VORTEXCFD_OPENFOAM_BASHRC"} "${STANDARD_BASHRCS[@]}"; do
    if [ -f "$candidate" ] && grep -Eq '^[[:space:]]*(export[[:space:]]+)?WM_PROJECT_VERSION=v2606([[:space:];#]|$)' "$candidate"; then
        OPENFOAM_BASHRC="$candidate"
        break
    fi
    printf '   looked at %s: %s\n' "$candidate" "$([ -f "$candidate" ] && echo "not v2606" || echo "no such file")"
done
if [ -n "$OPENFOAM_BASHRC" ]; then
    ok "found $OPENFOAM_BASHRC"
else
    warn "OpenFOAM v2606 was not found. VortexCFD installs and opens projects without it, but cannot mesh or solve."
    printf '   Install it with the official ESI packages (run these yourself, they need sudo):\n'
    printf '       curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash\n'
    printf '       sudo apt-get update\n'
    printf '       sudo apt-get install openfoam2606-default\n'
    printf '   Installed elsewhere? Set VORTEXCFD_OPENFOAM_BASHRC to its etc/bashrc, or set it in the app (Help > OpenFOAM Installation).\n'
fi

step "ParaView (optional)"
PARAVIEW_COMMAND="${VORTEXCFD_PARAVIEW_COMMAND:-paraview}"
WINDOWS_PROGRAMS="${VORTEXCFD_WINDOWS_PROGRAMS:-/mnt/c/Program Files}"
WINDOWS_PARAVIEW=""
for exe in "$WINDOWS_PROGRAMS"/ParaView*/bin/paraview.exe; do
    if [ -f "$exe" ]; then WINDOWS_PARAVIEW="$exe"; fi
done
if command -v "$PARAVIEW_COMMAND" >/dev/null 2>&1; then
    ok "found $(command -v "$PARAVIEW_COMMAND") (Open in ParaView uses it)"
elif [ -n "$WINDOWS_PARAVIEW" ]; then
    ok "found the Windows ParaView $WINDOWS_PARAVIEW (Open in ParaView uses it)"
else
    printf '   not found: ParaView is optional, VortexCFD shows its results without it ("Open in ParaView" stays off).\n'
    printf '   To use it, either install it in Ubuntu (run this yourself, it needs sudo):\n'
    printf '       sudo apt install paraview\n'
    printf '   or install ParaView for Windows and open the case.foam of a case through \\\\wsl$\\%s\\...\n' "${WSL_DISTRO_NAME:-<distribution>}"
fi

if [ "$CHECK_ONLY" = 1 ]; then
    step "Check only: nothing installed"
    [ -n "$OPENFOAM_BASHRC" ] && exit 0 || exit 3
fi

# -- 3. the virtual environment --------------------------------------------------------------------------------------

step "Virtual environment ($VENV)"
if [ -x "$VENV/bin/python" ] && [ "$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "3.12" ]; then
    ok "reusing the existing environment"
else
    mkdir -p "$PREFIX"
    "$PYTHON" -m venv --clear "$VENV"
    ok "created"
fi

# -- 4. the packages -------------------------------------------------------------------------------------------------

step "Packages (pinned: scripts/requirements-v1.txt)"
"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet -r "$REPO/scripts/requirements-v1.txt"
ok "dependencies"
"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet --no-deps --force-reinstall "$REPO"
ok "vortexcfd from $REPO"
"$VENV/bin/python" -m pip check --disable-pip-version-check >/dev/null || fail "pip check found inconsistent packages"
ok "pip check"

# -- 5. verification and the manual ----------------------------------------------------------------------------------

step "Verification"
QT_QPA_PLATFORM=offscreen "$VENV/bin/python" -c \
    "import vortexcfd, vortexcfd.cli, PySide6.QtWidgets, vtk, pyvista, pyvistaqt, OCP, pymeshfix, pytetwild, foamlib, matplotlib, pydantic" \
    || fail "the packages do not import"
ok "imports"
VERSION_LINE="$("$VENV/bin/vortexcfd" --version)"
ok "$VERSION_LINE"
MANUAL_DIR="$VENV/share/vortexcfd/manual"
if [ -d "$REPO/docs/manual" ]; then
    rm -rf "$MANUAL_DIR"
    mkdir -p "$(dirname "$MANUAL_DIR")"
    cp -r "$REPO/docs/manual" "$MANUAL_DIR"
    ok "user manual in $MANUAL_DIR"
fi
ICON_DIR="$VENV/share/vortexcfd/icons"  # the logo (D-175): the desktop entry's icon
if [ -d "$REPO/assets/branding/png" ]; then
    mkdir -p "$ICON_DIR"
    cp "$REPO/assets/branding/png/"vortexcfd-*.png "$ICON_DIR/"
    ok "icons in $ICON_DIR"
fi

# -- 6. the launcher -------------------------------------------------------------------------------------------------

if [ "$LAUNCHER" = 1 ]; then
    step "Launcher"
    LAUNCH="$PREFIX/vortexcfd-launch"
    cat > "$LAUNCH" <<EOF
#!/bin/sh
# VortexCFD launcher (written by scripts/install.sh)
exec "$VENV/bin/vortexcfd" "\$@"
EOF
    chmod +x "$LAUNCH"
    mkdir -p "$BIN_DIR" "$APPS_DIR"
    ln -sfn "$LAUNCH" "$BIN_DIR/vortexcfd"
    ok "$BIN_DIR/vortexcfd"
    cat > "$APPS_DIR/vortexcfd.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VortexCFD
Comment=CFD workflow on OpenFOAM ESI v2606
Exec=$LAUNCH %f
Icon=$ICON_DIR/vortexcfd-256.png
StartupWMClass=vortexcfd
Terminal=false
Categories=Science;Engineering;
EOF
    ok "$APPS_DIR/vortexcfd.desktop (WSLg lists it in the Windows Start menu)"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) warn "$BIN_DIR is not on PATH: open a new terminal (Ubuntu's ~/.profile adds it) or run $LAUNCH" ;;
    esac
fi

# -- 7. OpenFOAM through the app -------------------------------------------------------------------------------------

step "OpenFOAM check (vortexcfd --check-openfoam)"
if VORTEXCFD_OPENFOAM_BASHRC="${OPENFOAM_BASHRC:-${VORTEXCFD_OPENFOAM_BASHRC:-}}" "$VENV/bin/vortexcfd" --check-openfoam; then
    step "Done: start VortexCFD with 'vortexcfd' or from the Start menu"
    exit 0
fi
step "Done, but OpenFOAM v2606 is missing: install it (above), then run 'vortexcfd --check-openfoam'"
exit 3
