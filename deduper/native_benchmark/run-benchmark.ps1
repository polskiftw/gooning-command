param(
    [Parameter(Mandatory = $true)]
    [string]$DatabasePath,

    [int]$PHashRadius = 18,
    [int]$PDQRadius = 48,
    [int]$Threads = 0,
    [switch]$KeepExport
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Here "hamming_benchmark.cpp"
$Exe = Join-Path $Here "hamming_benchmark.exe"
$Export = Join-Path $env:TEMP "gparty-native-hash-benchmark.bin"

function Find-Python {
    foreach ($candidate in @("py", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }
    throw "Python was not found in PATH."
}

function Build-Benchmark {
    $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
    if ($cl) {
        Write-Host "Building with MSVC..."
        & $cl.Source /nologo /O2 /EHsc /std:c++20 /arch:AVX2 /Fe:$Exe $Source
        if ($LASTEXITCODE -ne 0) { throw "MSVC build failed with exit code $LASTEXITCODE" }
        return
    }

    $gpp = Get-Command g++.exe -ErrorAction SilentlyContinue
    if ($gpp) {
        Write-Host "Building with g++..."
        & $gpp.Source -O3 -std=c++20 -march=native -pthread -o $Exe $Source
        if ($LASTEXITCODE -ne 0) { throw "g++ build failed with exit code $LASTEXITCODE" }
        return
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $install = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($install) {
            $devcmd = Join-Path $install "Common7\Tools\VsDevCmd.bat"
            if (Test-Path $devcmd) {
                Write-Host "Building with Visual Studio Build Tools..."
                $command = '"{0}" -arch=x64 -host_arch=x64 >nul && cl /nologo /O2 /EHsc /std:c++20 /arch:AVX2 /Fe:"{1}" "{2}"' -f $devcmd, $Exe, $Source
                & cmd.exe /d /s /c $command
                if ($LASTEXITCODE -ne 0) { throw "Visual Studio build failed with exit code $LASTEXITCODE" }
                return
            }
        }
    }

    throw "No C++ compiler was found. Install Visual Studio Build Tools with Desktop development with C++, or put g++ in PATH."
}

$resolvedDb = (Resolve-Path -LiteralPath $DatabasePath).Path
$python = Find-Python

try {
    Build-Benchmark

    Write-Host ""
    Write-Host "Exporting hashes from the database in read-only mode..."
    if ($python -eq "py") {
        & py -3 (Join-Path $Here "export_hashes.py") $resolvedDb $Export
    } else {
        & python (Join-Path $Here "export_hashes.py") $resolvedDb $Export
    }
    if ($LASTEXITCODE -ne 0) { throw "Hash export failed with exit code $LASTEXITCODE" }

    if ($Threads -le 0) {
        $Threads = [Environment]::ProcessorCount
    }

    Write-Host ""
    Write-Host "Starting exhaustive native comparison..."
    & $Exe $Export $PHashRadius $PDQRadius $Threads
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed with exit code $LASTEXITCODE" }
}
finally {
    if (-not $KeepExport -and (Test-Path $Export)) {
        Remove-Item -LiteralPath $Export -Force
    }
}
