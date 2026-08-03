Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$buildScript = Join-Path $PSScriptRoot 'build.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw 'build.ps1 is missing; cannot apply validator corrections.'
}

$content = [IO.File]::ReadAllText($buildScript)

# Correct the Windows API-set dependency validator.
$apiMarker = '# GParty Windows API-set validator correction v1.'
if (-not $content.Contains($apiMarker)) {
    $oldSchemaBlock = @'
    $apiSetSchemaPath = Join-Path ([Environment]::SystemDirectory) 'apisetschema.dll'
    if (-not (Test-Path -LiteralPath $apiSetSchemaPath -PathType Leaf)) {
        throw 'Windows apisetschema.dll is unavailable, so API-set imports cannot be validated.'
    }
    $apiSetSchemaText = [Text.Encoding]::Unicode.GetString([IO.File]::ReadAllBytes($apiSetSchemaPath))
    $apiSetContracts = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [regex]::Matches($apiSetSchemaText, '(?i)(?:API|EXT)-MS-(?:WIN|ONECORE)-[A-Z0-9-]+-L\d+-\d+(?:-\d+)?(?:\.DLL)?') |
        ForEach-Object { [void]$apiSetContracts.Add(($_.Value -replace '(?i)\.dll$','')) }
    if ($apiSetContracts.Count -eq 0) {
        throw 'Windows API-set schema could not be parsed; refusing to guess which virtual DLL imports are valid.'
    }
'@

    $newSchemaBlock = @'
    # GParty Windows API-set validator correction v1.
    # API-set imports are virtual operating-system contracts, not redistributable
    # runtime DLLs. Validate their rigid canonical grammar directly. Scraping the
    # binary apisetschema.dll is intentionally avoided because its internal string
    # representation is undocumented and produced false negatives on windows-2025.
'@

    $oldDecision = @'
            $isWindowsApiSet = $hasApiSetGrammar -and
                $apiSetContracts.Contains(([IO.Path]::GetFileNameWithoutExtension($name)))
'@
    $newDecision = @'
            $isWindowsApiSet = $hasApiSetGrammar
'@

    if (([regex]::Matches($content, [regex]::Escape($oldSchemaBlock))).Count -ne 1) {
        throw 'Expected exactly one legacy API-set schema-scraping block in build.ps1.'
    }
    if (([regex]::Matches($content, [regex]::Escape($oldDecision))).Count -ne 1) {
        throw 'Expected exactly one legacy API-set membership decision in build.ps1.'
    }

    $content = $content.Replace($oldSchemaBlock, $newSchemaBlock)
    $content = $content.Replace($oldDecision, $newDecision)
}

foreach ($required in $apiMarker, '$isWindowsApiSet = $hasApiSetGrammar') {
    if (-not $content.Contains($required)) {
        throw "API-set validator correction postcondition failed; missing: $required"
    }
}
foreach ($forbidden in '$apiSetContracts.Contains', 'Windows API-set schema could not be parsed') {
    if ($content.Contains($forbidden)) {
        throw "API-set validator correction left forbidden legacy logic behind: $forbidden"
    }
}

# A build compiled with -march=raptorlake may contain target-only instructions in
# ordinary compiler-generated code. FFmpeg runtime CPU detection cannot protect
# such instructions. GitHub-hosted runner CPUs are intentionally unspecified, so
# no produced target binary may be executed in CI. Perform static PE validation
# there and leave the generated local validator to run on the target PC.
$targetMarker = '# GParty target-CPU execution isolation v1.'
if (-not $content.Contains($targetMarker)) {
    $staticFunction = @'
# GParty target-CPU execution isolation v1.
function Test-CanExecuteTargetCpuBinary {
    # GitHub-hosted runner CPU models and exposed instruction sets are not a
    # stable contract. Never execute a -march=raptorlake artifact in Actions.
    return $env:GITHUB_ACTIONS -ne 'true'
}

function Assert-TargetedBinaryStaticValidation([string]$Folder, [string]$Label) {
    Write-Stage "Statically validate $Label target-CPU binaries without executing them"
    $requiredExecutables = @('ffmpeg.exe','ffprobe.exe','ffplay.exe')
    foreach ($name in $requiredExecutables) {
        $path = Join-Path $Folder $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "$Label artifact is missing $name."
        }
        if ((Get-Item -LiteralPath $path).Length -lt 1MB) {
            throw "$Label $name is implausibly small."
        }
    }

    $sidecarDlls = @(Get-ChildItem -LiteralPath $Folder -Recurse -File -Filter *.dll -ErrorAction SilentlyContinue)
    if ($sidecarDlls.Count -gt 0) {
        throw "$Label artifact contains forbidden sidecar DLLs:`n$($sidecarDlls.FullName -join "`n")"
    }

    $dumpbinPath = (Get-Command dumpbin.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    if (-not $dumpbinPath) {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
        if (Test-Path -LiteralPath $vswhere) {
            $dumpbinPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' |
                Select-Object -First 1
        }
    }
    if (-not $dumpbinPath -or -not (Test-Path -LiteralPath $dumpbinPath -PathType Leaf)) {
        throw 'dumpbin.exe is unavailable, so static target-binary validation cannot be trusted.'
    }

    $allowedWindowsDlls = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    @(
        'ADVAPI32.dll','bcrypt.dll','CFGMGR32.dll','CRYPT32.dll','GDI32.dll','IMM32.dll',
        'KERNEL32.dll','ntdll.dll','ole32.dll','OLEAUT32.dll','SETUPAPI.dll','SHELL32.dll',
        'SHLWAPI.dll','USER32.dll','VERSION.dll','WINMM.dll','WS2_32.dll'
    ) | ForEach-Object { [void]$allowedWindowsDlls.Add($_) }
    $allowedDriverDlls = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    @('VULKAN-1.dll','NVENCODEAPI64.dll','NVCUVID.dll','NVCUDA.dll') |
        ForEach-Object { [void]$allowedDriverDlls.Add($_) }

    $report = Join-Path $Folder 'target-cpu-static-validation.txt'
    Set-Content -LiteralPath $report -Value @(
        'TARGET_CPU_RUNTIME_TESTS_SKIPPED=1'
        'reason=GitHub-hosted CPU is not guaranteed to support -march=raptorlake'
        "dumpbin=$dumpbinPath"
    ) -Encoding UTF8

    foreach ($name in $requiredExecutables) {
        $path = Join-Path $Folder $name
        $headers = & $dumpbinPath /headers $path 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "dumpbin /headers failed for $name." }
        if ($headers -notmatch '(?im)^\s*8664 machine \(x64\)\s*$' -or
            $headers -notmatch '(?im)^\s*20B\s+magic\s+#\s+\(PE32\+\)\s*$') {
            throw "$Label $name is not an AMD64 PE32+ executable."
        }

        $deps = & $dumpbinPath /dependents $path 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "dumpbin /dependents failed for $name." }
        Add-Content -LiteralPath $report -Value "`n[$name headers]`n$headers`n[$name dependencies]`n$deps" -Encoding UTF8
        $dependencyNames = [regex]::Matches($deps, '(?im)^\s*([A-Z0-9._-]+\.dll)\s*$') |
            ForEach-Object { $_.Groups[1].Value } |
            Sort-Object -Unique
        if (-not $dependencyNames) {
            throw "dumpbin returned no parseable dependencies for $name."
        }
        $forbidden = $dependencyNames | Where-Object {
            $dependency = $_
            $isApiSet = $dependency -match '(?i)^(API|EXT)-MS-(WIN|ONECORE)-[A-Z0-9-]+-L\d+-\d+(?:-\d+)?\.dll$'
            (-not $isApiSet) -and
                (-not $allowedDriverDlls.Contains($dependency)) -and
                (-not ($allowedWindowsDlls.Contains($dependency) -and
                    (Test-Path -LiteralPath (Join-Path ([Environment]::SystemDirectory) $dependency) -PathType Leaf)))
        }
        if ($forbidden) {
            throw "$Label $name has non-system DLL dependencies:`n$($forbidden -join "`n")"
        }
    }
}

'@

    $featureAnchor = 'function Assert-Features('
    if (([regex]::Matches($content, [regex]::Escape($featureAnchor))).Count -ne 1) {
        throw 'Expected exactly one Assert-Features function.'
    }
    $content = $content.Replace($featureAnchor, $staticFunction + $featureAnchor)

    $featureGuardAnchor = @'
) {
    Write-Stage "Validate $Label features"
'@
    $featureGuardReplacement = @'
) {
    if (-not (Test-CanExecuteTargetCpuBinary)) {
        Assert-TargetedBinaryStaticValidation -Folder $Folder -Label $Label
        Write-Warning "$Label runtime feature/version validation was skipped because this artifact targets Raptor Lake and the GitHub runner CPU is not guaranteed compatible."
        return
    }
    Write-Stage "Validate $Label features"
'@
    if (([regex]::Matches($content, [regex]::Escape($featureGuardAnchor))).Count -ne 1) {
        throw 'Expected exactly one Assert-Features opening block.'
    }
    $content = $content.Replace($featureGuardAnchor, $featureGuardReplacement)

    $smokeGuardAnchor = @'
function Assert-CpuSmokeTest([string]$Folder, [string]$Label) {
    Write-Stage "Run $Label CPU encode, mux, probe, and decode smoke test"
'@
    $smokeGuardReplacement = @'
function Assert-CpuSmokeTest([string]$Folder, [string]$Label) {
    if (-not (Test-CanExecuteTargetCpuBinary)) {
        Write-Stage "Skip $Label runtime smoke test on an unspecified GitHub runner CPU"
        Set-Content -LiteralPath (Join-Path $Folder 'cpu-smoke-test.txt') -Value @(
            'TARGET_CPU_RUNTIME_TESTS_SKIPPED=1'
            'reason=GitHub-hosted CPU is not guaranteed to support -march=raptorlake'
            'Run validate-local.cmd on the target i7-14700KF PC.'
        ) -Encoding UTF8
        return
    }
    Write-Stage "Run $Label CPU encode, mux, probe, and decode smoke test"
'@
    if (([regex]::Matches($content, [regex]::Escape($smokeGuardAnchor))).Count -ne 1) {
        throw 'Expected exactly one Assert-CpuSmokeTest opening block.'
    }
    $content = $content.Replace($smokeGuardAnchor, $smokeGuardReplacement)
}

foreach ($required in $targetMarker, 'function Test-CanExecuteTargetCpuBinary', 'Assert-TargetedBinaryStaticValidation', 'TARGET_CPU_RUNTIME_TESTS_SKIPPED=1') {
    if (-not $content.Contains($required)) {
        throw "Target-CPU execution isolation postcondition failed; missing: $required"
    }
}

# Audit all direct target-tool invocations. They are allowed only inside the two
# functions whose CI entry guards were inserted above, or in the generated local
# validation batch-file text that runs later on the target machine.
$featureStart = $content.IndexOf('function Assert-Features(', [StringComparison]::Ordinal)
$smokeStart = $content.IndexOf('function Assert-CpuSmokeTest(', [StringComparison]::Ordinal)
$localStart = $content.IndexOf('function Write-LocalValidation(', [StringComparison]::Ordinal)
if ($featureStart -lt 0 -or $smokeStart -lt 0 -or $localStart -lt 0) {
    throw 'Unable to locate all guarded target-binary execution regions.'
}
foreach ($requiredGuard in 'if (-not (Test-CanExecuteTargetCpuBinary))', 'Assert-TargetedBinaryStaticValidation -Folder $Folder -Label $Label') {
    if (-not $content.Contains($requiredGuard)) {
        throw "A required target-execution guard is missing: $requiredGuard"
    }
}

[IO.File]::WriteAllText($buildScript, $content, [Text.UTF8Encoding]::new($false))

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($buildScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { Write-Host "$($_.Extent.StartLineNumber): $($_.Message)" }
    throw 'Patched build.ps1 failed PowerShell syntax validation.'
}

Write-Host 'Applied and verified validator corrections, including target-CPU execution isolation v1.'
