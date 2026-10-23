# 1. Installation

VortexCFD runs inside WSL2 Ubuntu 24.04 on Windows 11; its window appears on the Windows desktop through WSLg.
It needs Python 3.12 (Ubuntu 24.04's own) and OpenFOAM ESI v2606.

## 1.1 OpenFOAM ESI v2606

Install OpenFOAM first, with the official ESI packages, in an Ubuntu terminal (these need sudo; VortexCFD never
runs them for you):

```bash
curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash
```

```bash
sudo apt-get update
```

```bash
sudo apt-get install openfoam2606-default
```

This puts OpenFOAM in `/usr/lib/openfoam/openfoam2606`, where VortexCFD looks first. OpenFOAM does not need to be on
your PATH: VortexCFD sources its `etc/bashrc` for every command it runs.

## 1.2 The install script

From a checkout of the VortexCFD repository:

```bash
scripts/install.sh
```

It:

1. checks Ubuntu 24.04, Python 3.12 with its venv module, and OpenFOAM v2606. When OpenFOAM is missing it prints
   the three commands above and carries on (the app installs and opens without it; the script then ends with exit
   code 3);
2. creates a virtual environment in `~/.local/share/vortexcfd/venv` (another place: `--prefix DIR`);
3. installs the pinned dependencies (`scripts/requirements-v1.txt`) and VortexCFD;
4. checks that everything imports and prints `vortexcfd 1.0.0rc1`;
5. writes the command `~/.local/bin/vortexcfd` and a desktop entry, so WSLg lists VortexCFD in the Windows Start
   menu (under your Ubuntu distribution);
6. runs `vortexcfd --check-openfoam`.

It never uses sudo itself. When a system package is missing (for example `python3.12-venv`) it stops and prints
the command for you to run. Running it again is safe: it reuses the environment and refreshes the app (this is
also how you update after pulling a new version).

Other options: `--check-only` (the system checks, nothing installed), `--no-launcher`, `--ignore-os` (try another
Ubuntu version). Start the app with `vortexcfd`, or `vortexcfd path/to/project.vcfd`.

## 1.3 The start-up check

At every start VortexCFD looks for OpenFOAM v2606, in this order:

1. the environment variable `VORTEXCFD_OPENFOAM_BASHRC` (the path of an `etc/bashrc`);
2. the path you set in the app (Help > OpenFOAM Installation);
3. the standard places: `/usr/lib/openfoam/openfoam2606`, `/opt/openfoam2606`, `/opt/OpenFOAM/OpenFOAM-v2606`,
   `~/OpenFOAM/OpenFOAM-v2606`.

An installation counts when its bashrc says `WM_PROJECT_VERSION=v2606` and simpleFoam, snappyHexMesh and blockMesh
are in its `platforms/*/bin`. If none is found (or only another version), a dialog shows where it looked, the
install commands, and a field for the path of your `etc/bashrc` (checked before it is accepted, then remembered).

Without OpenFOAM the app still opens: you can open projects and look at their meshes and results. Generate Mesh,
Run Solver, the Mesh Study and the Polar Sweep stay disabled, and their tooltip says why. Once OpenFOAM is found
(Help > OpenFOAM Installation, Check) they are enabled without a restart.

From a terminal, without starting the window:

```bash
vortexcfd --check-openfoam
```

## 1.4 Notes

- The install script has been run in isolation on the development machine only; a test on a second machine is
  still owed (docs/RELEASE_v1.md).
- 3D drawing uses the GPU through WSLg (Mesa d3d12): VortexCFD selects the NVIDIA adapter at start-up unless you
  set `GALLIUM_DRIVER` / `MESA_D3D12_DEFAULT_ADAPTER_NAME` yourself.
