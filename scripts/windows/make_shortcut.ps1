<#
.SYNOPSIS
    Creates a Start-menu shortcut (and a desktop one) that starts VortexCFD in WSL with the logo as its icon (D-179).

.DESCRIPTION
    Run it from Windows PowerShell, after scripts/install.sh has installed VortexCFD in the WSL distribution:

        powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu-24.04\home\<you>\...\scripts\windows\make_shortcut.ps1

    The shortcut runs  wsl.exe -d <Distro> -- <InstallPath>/bin/vortexcfd  (minimised, so its console window does not
    show). Its icon is the logo's vortexcfd.ico, copied to %LOCALAPPDATA%\VortexCFD\ first: an icon path on \\wsl$ is
    not reliable (Windows reads it only while the distribution runs). Pin the Start-menu shortcut to the taskbar to keep
    the logo there. Running it again replaces the shortcuts and the icon (idempotent).

.PARAMETER Distro
    The WSL distribution VortexCFD is installed in (wsl.exe -l -v lists them). Default: Ubuntu-24.04.

.PARAMETER InstallPath
    The virtual environment scripts/install.sh made, as a Linux path. Default: ~/.local/share/vortexcfd/venv of the
    distribution's default user (asked from WSL).

.PARAMETER IconSource
    The .ico to use. Default: assets\branding\vortexcfd.ico next to this script's checkout, else the copy install.sh
    put in <InstallPath>/share/vortexcfd/icons/.

.PARAMETER NoDesktop
    Only the Start-menu shortcut.
#>
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$InstallPath = "",
    [string]$IconSource = "",
    [switch]$NoDesktop
)
$ErrorActionPreference = "Stop"

$wsl = Join-Path $env:WINDIR "System32\wsl.exe"
if (-not (Test-Path $wsl)) { throw "wsl.exe not found ($wsl): is WSL installed?" }

if (-not $InstallPath) {
    $home_ = (& $wsl -d $Distro -- sh -c 'printf %s "$HOME"')
    if ($LASTEXITCODE -ne 0 -or -not $home_) { throw "Could not ask WSL for the home directory in '$Distro'." }
    $InstallPath = "$home_/.local/share/vortexcfd/venv"
}
$InstallPath = $InstallPath.TrimEnd("/")
$exe = "$InstallPath/bin/vortexcfd"
& $wsl -d $Distro -- test -x $exe
if ($LASTEXITCODE -ne 0) { throw "$exe is not in '$Distro': run scripts/install.sh there first, or pass -InstallPath." }

if (-not $IconSource) {
    $IconSource = Join-Path $PSScriptRoot "..\..\assets\branding\vortexcfd.ico"
    if (-not (Test-Path $IconSource)) {
        $IconSource = "\\wsl.localhost\$Distro" + ("$InstallPath/share/vortexcfd/icons/vortexcfd.ico" -replace "/", "\")
    }
}
if (-not (Test-Path $IconSource)) { throw "The icon $IconSource was not found: pass -IconSource." }
$iconDir = Join-Path $env:LOCALAPPDATA "VortexCFD"
New-Item -ItemType Directory -Force -Path $iconDir | Out-Null
$icon = Join-Path $iconDir "vortexcfd.ico"
Copy-Item -Force -Path $IconSource -Destination $icon

$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath("Programs"))
if (-not $NoDesktop) { $places += [Environment]::GetFolderPath("Desktop") }
foreach ($place in $places) {
    $path = Join-Path $place "VortexCFD.lnk"
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $wsl
    $link.Arguments = "-d `"$Distro`" -- `"$exe`""
    $link.WorkingDirectory = $env:USERPROFILE
    $link.IconLocation = "$icon,0"
    $link.WindowStyle = 7  # minimised: the console of wsl.exe stays out of the way
    $link.Description = "VortexCFD (OpenFOAM ESI v2606 in WSL: $Distro)"
    $link.Save()
    Write-Host "Shortcut: $path"
}
Write-Host "Icon: $icon"
Write-Host "Pin the Start-menu shortcut to the taskbar to keep the VortexCFD logo there."
