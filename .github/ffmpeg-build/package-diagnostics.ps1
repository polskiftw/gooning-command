Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$diagRoot = $env:DIAG_ROOT
$buildRoot = $env:BUILD_ROOT
New-Item -ItemType Directory -Force -Path $diagRoot | Out-Null

if (-not (Get-ChildItem -Path $diagRoot -Filter 'SUMMARY-*.txt' -ErrorAction SilentlyContinue)) {
    Set-Content -Path (Join-Path $diagRoot 'SUMMARY.txt') -Value 'The build failed before a detailed exception summary was written. Inspect the collected logs.' -Encoding UTF8
}

$suiteRoot = Join-Path $buildRoot 'mabs'
$mabsZip = Join-Path $suiteRoot 'build\logs.zip'
if (Test-Path $mabsZip) {
    $expanded = Join-Path $diagRoot 'mabs-logs'
    Remove-Item $expanded -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $expanded | Out-Null
    try {
        Expand-Archive -LiteralPath $mabsZip -DestinationPath $expanded -Force
    } catch {
        $_ | Out-File (Join-Path $diagRoot 'mabs-logs-expand-error.txt') -Encoding UTF8
    }
}

$usefulRoots = @(
    (Join-Path $suiteRoot 'build'),
    (Join-Path $suiteRoot 'msys64\var\log'),
    (Join-Path $suiteRoot 'local64')
)
foreach ($root in $usefulRoots) {
    if (-not (Test-Path $root)) { continue }
    $safeName = ($root -replace '[:\\/ ]','_').Trim('_')
    $dest = Join-Path $diagRoot $safeName
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -ne 'logs.zip' -and (
                $_.Extension -in '.log','.txt','.ini','.sh','.bat','.ps1','.patch','.diff' -or
                $_.Name -match 'config|version|option|error|fail'
            )
        } |
        ForEach-Object {
            try {
                $relative = [IO.Path]::GetRelativePath($root, $_.FullName)
                $target = Join-Path $dest $relative
                New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
                Copy-Item $_.FullName $target -Force
            } catch {}
        }
}

$commitLines = [System.Collections.Generic.List[string]]::new()
if (Test-Path (Join-Path $suiteRoot '.git')) {
    $sha = (& git -C $suiteRoot rev-parse HEAD 2>$null | Select-Object -First 1)
    if ($sha) { $commitLines.Add("media-autobuild_suite=$sha") }
}
$sourceRoot = Join-Path $suiteRoot 'build'
if (Test-Path $sourceRoot) {
    Get-ChildItem -Path $sourceRoot -Directory -Recurse -Force -Filter '.git' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $source = $_.Parent.FullName
            try {
                $sha = (& git -C $source rev-parse HEAD 2>$null | Select-Object -First 1)
                if ($sha) {
                    $name = [IO.Path]::GetRelativePath($sourceRoot, $source) -replace '\\','/'
                    $commitLines.Add("$name=$sha")
                }
            } catch {}
        }
}
$commitLines | Sort-Object -Unique | Set-Content -Path (Join-Path $diagRoot 'source-commits.txt') -Encoding UTF8

Write-Host "Prepared direct diagnostics artifact at $diagRoot"
