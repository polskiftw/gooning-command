Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$diagRoot = $env:DIAG_ROOT
$buildRoot = $env:BUILD_ROOT
$workspace = $env:GITHUB_WORKSPACE
New-Item -ItemType Directory -Force -Path $diagRoot | Out-Null

if (-not (Test-Path (Join-Path $diagRoot 'SUMMARY.txt'))) {
    Set-Content -Path (Join-Path $diagRoot 'SUMMARY.txt') -Value 'The build failed before a detailed exception summary was written. Inspect the collected logs.' -Encoding UTF8
}

$usefulRoots = @(
    (Join-Path $buildRoot 'mabs\build'),
    (Join-Path $buildRoot 'mabs\msys64\var\log'),
    (Join-Path $buildRoot 'mabs\local64')
)
foreach ($root in $usefulRoots) {
    if (-not (Test-Path $root)) { continue }
    $safeName = ($root -replace '[:\\/ ]','_').Trim('_')
    $dest = Join-Path $diagRoot $safeName
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -in '.log','.txt','.ini','.sh','.bat','.ps1','.patch','.diff' -or
            $_.Name -match 'config|version|option|error|fail'
        } |
        ForEach-Object {
            try {
                $relative = $_.FullName.Substring($root.Length).TrimStart('\\','/')
                $target = Join-Path $dest $relative
                New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
                Copy-Item $_.FullName $target -Force
            } catch {}
        }
}

$zipPath = Join-Path $workspace 'ffmpeg-build-diagnostics.zip'
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $diagRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Created $zipPath"
