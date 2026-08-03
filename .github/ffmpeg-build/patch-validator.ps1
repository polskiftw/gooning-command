Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$buildScript = Join-Path $PSScriptRoot 'build.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw 'build.ps1 is missing; cannot apply the API-set validator correction.'
}

$content = [IO.File]::ReadAllText($buildScript)
$marker = '# GParty Windows API-set validator correction v1.'

if ($content.Contains($marker)) {
    if ($content -notmatch [regex]::Escape('$isWindowsApiSet = $hasApiSetGrammar')) {
        throw 'The API-set validator correction marker exists, but its required logic is missing.'
    }
    exit 0
}

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

foreach ($required in $marker, '$isWindowsApiSet = $hasApiSetGrammar') {
    if (-not $content.Contains($required)) {
        throw "API-set validator correction postcondition failed; missing: $required"
    }
}
foreach ($forbidden in '$apiSetContracts.Contains', 'Windows API-set schema could not be parsed') {
    if ($content.Contains($forbidden)) {
        throw "API-set validator correction left forbidden legacy logic behind: $forbidden"
    }
}

[IO.File]::WriteAllText($buildScript, $content, [Text.UTF8Encoding]::new($false))

$tokens = $null
$parseErrors = $null
[void][Management.Automation.Language.Parser]::ParseFile($buildScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { Write-Host "$($_.Extent.StartLineNumber): $($_.Message)" }
    throw 'Patched build.ps1 failed PowerShell syntax validation.'
}

Write-Host 'Applied and verified Windows API-set validator correction v1.'
