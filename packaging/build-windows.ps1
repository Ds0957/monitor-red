<#
.SYNOPSIS
  Builds MonitorRed.exe and the MonitorRed-windows.zip installer package.

.DESCRIPTION
  Run on Windows from the project root (or any copy of it):
    powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
  Requires Python 3.10+ on PATH. Creates .venv-win, installs the app and
  PyInstaller there, and writes dist\MonitorRed-windows\ and its .zip.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = Join-Path $root '.venv-win'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    python -m venv $venv
}
$py = Join-Path $venv 'Scripts\python.exe'
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet . pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# Textual and Rich import some modules dynamically; collect them explicitly.
& $py -m PyInstaller --noconfirm --clean --onefile --console `
    --name MonitorRed `
    --collect-submodules textual --collect-data textual `
    --collect-submodules rich `
    --distpath build\pyinstaller-dist --workpath build\pyinstaller-work --specpath build `
    packaging\entry.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$out = Join-Path $root 'dist\MonitorRed-windows'
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path $out | Out-Null
Copy-Item build\pyinstaller-dist\MonitorRed.exe $out
Copy-Item packaging\windows\* $out
$zip = Join-Path $root 'dist\MonitorRed-windows.zip'
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip
Write-Host "Paquete listo: $zip"
