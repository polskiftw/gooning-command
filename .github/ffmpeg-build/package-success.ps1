param(
    [ValidateSet('stable','master','all')]
    [string]$Variant = 'all'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-NonEmptyFile([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing $Description."
    }
    if ((Get-Item -LiteralPath $Path).Length -le 0) {
        throw "$Description is empty."
    }
}

function Assert-ContainsLiteral([string]$Path, [string]$Literal, [string]$Description) {
    Assert-NonEmptyFile -Path $Path -Description $Description
    $text = [IO.File]::ReadAllText($Path)
    if (-not $text.Contains($Literal, [StringComparison]::Ordinal)) {
        throw "$Description is missing required proof: $Literal"
    }
}

$outRoot = $env:OUT_ROOT
if (-not (Test-Path -LiteralPath $outRoot -PathType Container)) {
    throw "Output directory does not exist: $outRoot"
}

$folders = if ($Variant -eq 'all') { @('stable','master') } else { @($Variant) }
$runtimeReports = @(
    'build-info.txt','ffprobe-version.txt','ffplay-version.txt',
    'pe-headers.txt','pe-dependencies.txt','cpu-smoke-test.txt',
    'encoders.txt','decoders.txt','filters.txt','devices.txt','protocols.txt',
    'hwaccels.txt','muxers.txt','demuxers.txt','verify-nvidia.cmd'
)
$staticReports = @('target-cpu-static-validation.txt','cpu-smoke-test.txt')
$alwaysReports = @('source-identity.txt','recovery-stage.txt')

foreach ($folder in $folders) {
    $path = Join-Path $outRoot $folder
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Missing completed build folder: $folder"
    }

    foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $exePath = Join-Path $path $exe
        Assert-NonEmptyFile -Path $exePath -Description "$folder/$exe"
        if ((Get-Item -LiteralPath $exePath).Length -lt 1MB) {
            throw "$folder/$exe is implausibly small."
        }
    }

    $dlls = @(Get-ChildItem -LiteralPath $path -Recurse -File -Filter *.dll -ErrorAction SilentlyContinue)
    if ($dlls.Count -gt 0) {
        throw "$folder contains forbidden DLL files: $($dlls.Name -join ', ')"
    }

    foreach ($report in $alwaysReports) {
        Assert-NonEmptyFile -Path (Join-Path $path $report) -Description "$folder validator report $report"
    }

    $staticPath = Join-Path $path 'target-cpu-static-validation.txt'
    $isStaticOnly = Test-Path -LiteralPath $staticPath -PathType Leaf
    $validationMode = if ($isStaticOnly) { 'target-cpu-static' } else { 'runtime' }

    if ($isStaticOnly) {
        Assert-ContainsLiteral -Path $staticPath -Literal 'TARGET_CPU_RUNTIME_TESTS_SKIPPED=1' -Description "$folder static validation report"
        foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
            Assert-ContainsLiteral -Path $staticPath -Literal "[$exe headers]" -Description "$folder static validation report"
            Assert-ContainsLiteral -Path $staticPath -Literal "[$exe dependencies]" -Description "$folder static validation report"
        }

        $smokePath = Join-Path $path 'cpu-smoke-test.txt'
        Assert-ContainsLiteral -Path $smokePath -Literal 'TARGET_CPU_RUNTIME_TESTS_SKIPPED=1' -Description "$folder CPU smoke-test deferral report"

        # The target binary must never be executed on an unspecified GitHub runner.
        # Runtime feature/version reports are therefore intentionally absent in this
        # mode. Reject a half-generated set, which would indicate control-flow drift.
        $presentRuntimeReports = @($runtimeReports | Where-Object {
            Test-Path -LiteralPath (Join-Path $path $_) -PathType Leaf
        })
        $allowedStaticRuntimeReports = @('cpu-smoke-test.txt','verify-nvidia.cmd')
        $unexpectedPartial = @($presentRuntimeReports | Where-Object { $_ -notin $allowedStaticRuntimeReports })
        if ($unexpectedPartial.Count -gt 0) {
            throw "$folder has a partial runtime-report set in static-only mode: $($unexpectedPartial -join ', ')"
        }
    } else {
        foreach ($report in $runtimeReports) {
            Assert-NonEmptyFile -Path (Join-Path $path $report) -Description "$folder validator report $report"
        }
        Assert-ContainsLiteral -Path (Join-Path $path 'cpu-smoke-test.txt') -Literal 'CPU_SMOKE_TEST_PASSED=1' -Description "$folder CPU smoke-test report"
    }

    $manifest = [System.Collections.Generic.List[string]]::new()
    $manifest.Add("variant=$folder")
    $manifest.Add("validation_mode=$validationMode")
    $manifest.Add("packaged_utc=$([datetime]::UtcNow.ToString('o'))")
    foreach ($name in @('ffmpeg.exe','ffprobe.exe','ffplay.exe') + $alwaysReports + $staticReports + $runtimeReports | Sort-Object -Unique) {
        $candidate = Join-Path $path $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $item = Get-Item -LiteralPath $candidate
            $manifest.Add("present`t$name`t$($item.Length)")
        } else {
            $manifest.Add("absent`t$name")
        }
    }
    Set-Content -LiteralPath (Join-Path $path 'VALIDATION-MANIFEST.txt') -Value $manifest -Encoding UTF8

    $hashLines = foreach ($exe in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $path $exe)
        "$($hash.Hash.ToLowerInvariant())  $exe"
    }
    Set-Content -LiteralPath (Join-Path $path 'SHA256SUMS.txt') -Value $hashLines -Encoding ASCII
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
