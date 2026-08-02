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
}

foreach ($pair in $replacements.GetEnumerator()) {
    $count = ([regex]::Matches($content, [regex]::Escape($pair.Key))).Count
    if ($count -ne 1) {
        throw "Expected exactly one '$($pair.Key)' validation entry in build.ps1, found $count."
    }
    $content = $content.Replace($pair.Key, $pair.Value)
}

# These are FFmpeg's actual command-line feature names. The codec ID is
# HDMV_PGS_SUBTITLE, but `ffmpeg -decoders` reports the decoder as `pgssub`.
# Likewise, the libvmaf filter is listed as `libvmaf`, not `vmaf`.
[IO.File]::WriteAllText($buildScript, $content, [System.Text.UTF8Encoding]::new($false))

Write-Host 'Corrected FFmpeg validation names: pgssub and libvmaf.'
