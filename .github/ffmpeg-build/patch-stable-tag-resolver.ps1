Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$buildScript = Join-Path $PSScriptRoot 'build.ps1'
$content = [IO.File]::ReadAllText($buildScript)

$old = @'
function Resolve-LatestStableTag {
    Write-Stage 'Resolve latest stable FFmpeg tag'
    $tags = Invoke-RestMethod -Headers @{ 'User-Agent' = 'custom-ffmpeg-builder' } -Uri 'https://api.github.com/repos/FFmpeg/FFmpeg/tags?per_page=100'
    $stable = $tags | Where-Object { $_.name -match '^n\d+\.\d+(\.\d+)?$' } | Sort-Object {
        [version](($_.name.TrimStart('n')) -replace '^([0-9]+\.[0-9]+)$','$1.0')
    } -Descending | Select-Object -First 1
    if (-not $stable) { throw 'Unable to resolve latest stable FFmpeg tag.' }
    return $stable.name
}
'@

$new = @'
function Resolve-LatestStableTag {
    Write-Stage 'Resolve latest stable FFmpeg tag with Git'
    $remoteTags = & git ls-remote --tags --refs https://github.com/FFmpeg/FFmpeg.git 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query FFmpeg tags with Git:`n$($remoteTags | Out-String)"
    }

    $stable = $remoteTags |
        ForEach-Object {
            if ($_ -match 'refs/tags/(n\d+\.\d+(?:\.\d+)?)$') {
                $Matches[1]
            }
        } |
        Where-Object { $_ } |
        Sort-Object {
            [version](($_.TrimStart('n')) -replace '^([0-9]+\.[0-9]+)$','$1.0')
        } -Descending |
        Select-Object -First 1

    if (-not $stable) {
        throw 'Unable to resolve latest stable FFmpeg tag from Git.'
    }
    return $stable
}
'@

$count = ([regex]::Matches($content, [regex]::Escape($old))).Count
if ($count -ne 1) {
    throw "Expected exactly one original REST stable-tag resolver, found $count."
}

$updated = $content.Replace($old, $new)
if ($updated -match 'api\.github\.com/repos/FFmpeg/FFmpeg/tags') {
    throw 'The FFmpeg REST tag lookup remains after patching.'
}

[IO.File]::WriteAllText($buildScript, $updated, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Replaced FFmpeg REST tag lookup with Git tag lookup.'
