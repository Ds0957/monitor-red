<#
.SYNOPSIS
  Installs Monitor de red for the current user (no administrator rights needed).

.DESCRIPTION
  Copies MonitorRed.exe to %LOCALAPPDATA%\Programs\MonitorRed and creates
  Desktop and Start Menu shortcuts. The shortcut opens the monitor in Windows
  Terminal when it is installed, otherwise in the classic console.
  The inventory database lives in %LOCALAPPDATA%\MonitorRed\red.db and is kept
  across reinstalls.

.PARAMETER Excel
  Optional inventory spreadsheet to import right after installing.

.PARAMETER Reemplazar
  With -Excel: replace the current inventory instead of refusing when it has data.

.EXAMPLE
  .\instalar.ps1 -Excel "C:\Users\soporte\Downloads\Organización de Red de Equipos Sede Principal.xlsx"
#>
param(
    [string]$Excel,
    [switch]$Reemplazar
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'MonitorRed.exe'
if (-not (Test-Path $source)) {
    throw "No se encuentra MonitorRed.exe junto a este script ($PSScriptRoot)."
}

$installDir = Join-Path $env:LOCALAPPDATA 'Programs\MonitorRed'
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$exe = Join-Path $installDir 'MonitorRed.exe'
Copy-Item -Force $source $exe
Write-Host "Programa copiado en $installDir"

# Prefer Windows Terminal: better colors and resizing than the classic console.
$wt = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\wt.exe'
$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Monitor de red.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Monitor de red.lnk')
)
foreach ($lnkPath in $targets) {
    $lnk = $shell.CreateShortcut($lnkPath)
    if (Test-Path $wt) {
        $lnk.TargetPath = $wt
        $lnk.Arguments = "new-tab --title `"Monitor de red`" --suppressApplicationTitle `"$exe`""
    } else {
        $lnk.TargetPath = $exe
        $lnk.Arguments = ''
    }
    $lnk.WorkingDirectory = $installDir
    $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,186"
    $lnk.Description = 'Monitor de red: inventario de IPs y ping en tiempo real'
    $lnk.Save()
    Write-Host "Acceso directo creado: $lnkPath"
}

if ($Excel) {
    $importArgs = @('importar', $Excel)
    if ($Reemplazar) { $importArgs += '--reemplazar' }
    & $exe @importArgs
    if ($LASTEXITCODE -ne 0) { Write-Warning 'La importación no se completó (ver mensaje arriba).' }
}

Write-Host ''
Write-Host 'Listo. Abre "Monitor de red" desde el escritorio o el menú Inicio.'
Write-Host "Base de datos: $(Join-Path $env:LOCALAPPDATA 'MonitorRed\red.db')"
