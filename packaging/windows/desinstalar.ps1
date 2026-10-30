<#
.SYNOPSIS
  Removes Monitor de red for the current user.

.PARAMETER BorrarDatos
  Also delete the inventory database (%LOCALAPPDATA%\MonitorRed). Kept by default.
#>
param([switch]$BorrarDatos)

$ErrorActionPreference = 'Stop'
$paths = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Monitor de red.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Monitor de red.lnk'),
    (Join-Path $env:LOCALAPPDATA 'Programs\MonitorRed')
)
if ($BorrarDatos) { $paths += (Join-Path $env:LOCALAPPDATA 'MonitorRed') }

foreach ($p in $paths) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "Eliminado: $p"
    }
}
if (-not $BorrarDatos) {
    Write-Host "Se conservó la base de datos en $(Join-Path $env:LOCALAPPDATA 'MonitorRed')."
}
