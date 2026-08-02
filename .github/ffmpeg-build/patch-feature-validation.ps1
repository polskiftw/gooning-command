Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$buildScript = Join-Path $PSScriptRoot 'build.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "FFmpeg build script not found: $buildScript"
}

$content = [IO.File]::ReadAllText($buildScript)
$replacements = [ordered]@{
    "'hdmv_pgs_subtitle'" = "'pgssub'"
    "'vmaf','loudnorm'"   = "'libvmaf','loudnorm'"
    "indevs = @('lavfi')" = "devices = @('lavfi')"
    '[A-Z\.]{3,8}'       = '[A-Z\.]{1,8}'
    '$text = & $ffmpeg "-$($entry.Key)" 2>&1 | Out-String' = @'
$text = & $ffmpeg "-$($entry.Key)" 2>&1 | Out-String
        $reportExitCode = $LASTEXITCODE
'@
}

foreach ($pair in $replacements.GetEnumerator()) {
    $count = ([regex]::Matches($content, [regex]::Escape($pair.Key))).Count
    if ($count -ne 1) {
        throw "Expected exactly one '$($pair.Key)' validation entry in build.ps1, found $count."
    }
    $content = $content.Replace($pair.Key, $pair.Value)
}

$reportWrite = '        Set-Content -Path (Join-Path $Folder "$($entry.Key).txt") -Value $text -Encoding UTF8'
$reportWriteCount = ([regex]::Matches($content, [regex]::Escape($reportWrite))).Count
if ($reportWriteCount -ne 1) {
    throw "Expected exactly one feature-report write in build.ps1, found $reportWriteCount."
}
$reportExitCheck = @'
        Set-Content -Path (Join-Path $Folder "$($entry.Key).txt") -Value $text -Encoding UTF8
        if ($reportExitCode -ne 0) {
            throw "$Label feature report command '-$($entry.Key)' failed with exit code $reportExitCode."
        }
'@
$content = $content.Replace($reportWrite, $reportExitCheck)

# These are FFmpeg's actual command-line feature names. The codec ID is
# HDMV_PGS_SUBTITLE, but `ffmpeg -decoders` reports the decoder as `pgssub`.
# Likewise, the libvmaf filter is listed as `libvmaf`, not `vmaf`.
# `ffmpeg -devices` is the runtime report containing the lavfi input device;
# `-indevs` is a configure-script option and is not accepted by ffmpeg.exe.
# Device rows may have only a one-character capability token (`D`), while filters,
# encoders, and decoders use longer tokens. Accepting 1-8 characters lets the same
# anchored parser validate every requested report without matching feature names
# only because they happen to appear in a description. Native-command exit codes
# are checked separately so an invalid report command cannot look like a missing
# compiled feature.
[IO.File]::WriteAllText($buildScript, $content, [System.Text.UTF8Encoding]::new($false))

Write-Host 'Corrected FFmpeg validation names, report command, row prefixes, and exit-code handling.'
