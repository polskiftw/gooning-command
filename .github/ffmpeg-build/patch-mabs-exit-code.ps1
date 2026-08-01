Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$buildScript = Join-Path $PSScriptRoot 'build.ps1'
$content = [IO.File]::ReadAllText($buildScript)

$oldFunction = @'
function Invoke-Logged([string]$Name, [scriptblock]$Command) {
    Write-Stage $Name
    & $Command 2>&1 | Tee-Object -FilePath (Join-Path $logRoot (($Name -replace '[^A-Za-z0-9._-]', '_') + '.log'))
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}
'@

$newFunction = @'
function Invoke-Logged([string]$Name, [scriptblock]$Command, [switch]$AllowNonZeroExit) {
    Write-Stage $Name
    & $Command 2>&1 | Tee-Object -FilePath (Join-Path $logRoot (($Name -replace '[^A-Za-z0-9._-]', '_') + '.log'))
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
        throw "$Name failed with exit code $exitCode"
    }
    return $exitCode
}
'@

$oldCall = '    Invoke-Logged "Build $Label" { cmd.exe /d /c "cd /d $suiteRoot && media-autobuild_suite.bat" }'
$newCall = '    $mabsExitCode = Invoke-Logged "Build $Label" { cmd.exe /d /c "cd /d $suiteRoot && media-autobuild_suite.bat" } -AllowNonZeroExit'

if (([regex]::Matches($content, [regex]::Escape($oldFunction))).Count -ne 1) {
    throw 'Expected exactly one original Invoke-Logged function.'
}
if (([regex]::Matches($content, [regex]::Escape($oldCall))).Count -ne 1) {
    throw 'Expected exactly one original MABS Invoke-Logged call.'
}

$updated = $content.Replace($oldFunction, $newFunction).Replace($oldCall, $newCall)

$marker = @'
    if ($mabsExitCode -ne 0) {
        Write-Warning "MABS returned exit code $mabsExitCode; verifying the produced binaries before deciding whether the build failed."
    }

'@
$anchor = "`n    if (-not (Test-Path -LiteralPath `$expectedFfmpeg -PathType Leaf)) {"
if (-not $updated.Contains($anchor)) {
    throw 'Could not find the post-MABS binary verification anchor.'
}
$updated = $updated.Replace($anchor, "`n$marker    if (-not (Test-Path -LiteralPath `$expectedFfmpeg -PathType Leaf)) {")

[IO.File]::WriteAllText($buildScript, $updated, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Patched MABS exit-code handling; binary verification remains authoritative.'
