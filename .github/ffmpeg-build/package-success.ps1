Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$outRoot = $env:OUT_ROOT
if (-not (Test-Path $outRoot)) { throw "Output directory does not exist: $outRoot" }
foreach ($folder in 'stable','master') {
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

$date = Get-Date -Format 'yyyy-MM-dd'
$zipName = "ffmpeg-custom-windows-x64-$date.zip"
$zipPath = Join-Path $env:GITHUB_WORKSPACE $zipName
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $outRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = Get-FileHash -Algorithm SHA256 -Path $zipPath
Set-Content -Path "$zipPath.sha256.txt" -Value "$($zipHash.Hash.ToLowerInvariant())  $zipName" -Encoding ASCII
Write-Host "Created $zipPath"
