param(
    [ValidateSet('stable','master','all')]
    [string]$Variant = 'all'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$outRoot = $env:OUT_ROOT
if (-not (Test-Path $outRoot)) { throw "Output directory does not exist: $outRoot" }
$folders = if ($Variant -eq 'all') { @('stable','master') } else { @($Variant) }

foreach ($folder in $folders) {
    $path = Join-Path $outRoot $folder
    if (-not (Test-Path $path)) { throw "Missing completed build folder: $folder" }
    foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        if (-not (Test-Path (Join-Path $path $exe))) { throw "Missing $folder/$exe" }
    }
    $hashLines = foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $hash = Get-FileHash -Algorithm SHA256 -Path (Join-Path $path $exe)
        "$($hash.Hash.ToLowerInvariant())  $exe"
    }
    Set-Content -Path (Join-Path $path 'SHA256SUMS.txt') -Value $hashLines -Encoding ASCII
}

Write-Host "Prepared direct artifact contents for: $($folders -join ', ')"
