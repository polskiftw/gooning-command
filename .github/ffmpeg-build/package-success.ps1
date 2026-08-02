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
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Missing completed build folder: $folder" }
    foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $exePath = Join-Path $path $exe
        if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw "Missing $folder/$exe" }
        if ((Get-Item -LiteralPath $exePath).Length -lt 1MB) { throw "$folder/$exe is implausibly small." }
    }
    $dlls = @(Get-ChildItem -LiteralPath $path -Recurse -File -Filter *.dll -ErrorAction SilentlyContinue)
    if ($dlls.Count -gt 0) { throw "$folder contains forbidden DLL files: $($dlls.Name -join ', ')" }
    foreach ($report in 'source-identity.txt','recovery-stage.txt','build-info.txt','ffprobe-version.txt','ffplay-version.txt','pe-headers.txt','pe-dependencies.txt','cpu-smoke-test.txt','encoders.txt','decoders.txt','filters.txt','devices.txt','protocols.txt','hwaccels.txt','muxers.txt','demuxers.txt','verify-nvidia.cmd') {
        if (-not (Test-Path -LiteralPath (Join-Path $path $report) -PathType Leaf)) {
            throw "$folder is missing validator report $report."
        }
    }
    $hashLines = foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $hash = Get-FileHash -Algorithm SHA256 -Path (Join-Path $path $exe)
        "$($hash.Hash.ToLowerInvariant())  $exe"
    }
    Set-Content -Path (Join-Path $path 'SHA256SUMS.txt') -Value $hashLines -Encoding ASCII
}

if ($Variant -eq 'all') {
    foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $stableHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $outRoot "stable\$exe")).Hash
        $masterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $outRoot "master\$exe")).Hash
        if ($stableHash -eq $masterHash) {
            throw "Stable and master $exe are byte-for-byte identical; refusing a mislabeled two-build artifact."
        }
    }
}

Write-Host "Prepared direct artifact contents for: $($folders -join ', ')"
