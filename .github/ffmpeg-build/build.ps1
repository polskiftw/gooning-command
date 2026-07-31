param(
    [ValidateSet('stable','master')]
    [string]$Variant = 'stable',
    [switch]$ReuseSuite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$buildRoot = $env:BUILD_ROOT
$outRoot = $env:OUT_ROOT
$diagRoot = $env:DIAG_ROOT
$suiteRoot = Join-Path $buildRoot 'mabs'
$logRoot = Join-Path $diagRoot 'logs'
$metaRoot = Join-Path $diagRoot 'metadata'
New-Item -ItemType Directory -Force -Path $buildRoot, $outRoot, $diagRoot, $logRoot, $metaRoot | Out-Null

$transcript = Join-Path $logRoot "workflow-$Variant-transcript.txt"
Start-Transcript -Path $transcript -Force | Out-Null

function Write-Stage([string]$Message) {
    Write-Host "`n========== $Message ==========" -ForegroundColor Cyan
    Set-Content -Path (Join-Path $diagRoot 'failed-step.txt') -Value $Message -Encoding UTF8
}

function Invoke-Logged([string]$Name, [scriptblock]$Command) {
    Write-Stage $Name
    & $Command 2>&1 | Tee-Object -FilePath (Join-Path $logRoot (($Name -replace '[^A-Za-z0-9._-]', '_') + '.log'))
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

function Write-SafeEnvironment([string]$Path) {
    Get-ChildItem Env: |
        Sort-Object Name |
        ForEach-Object {
            $value = if ($_.Name -match '(?i)(token|secret|password|passwd|pwd|credential|private|key|cookie|auth)') {
                '[REDACTED]'
            } else {
                $_.Value
            }
            [PSCustomObject]@{
                Name = $_.Name
                Value = $value
            }
        } |
        Format-Table -AutoSize |
        Out-File $Path -Encoding UTF8
}

function Write-Ini([string]$FfmpegPath) {
    $ini = @"
[compiler list]
arch=3
license2=1
standalone=2
av1an=2
vpx2=1
aom=1
rav1e=1
dav1d=1
libavif=1
libheif=1
jpegxl=1
x2643=1
x2652=1
other265=2
svthevc=2
xvc=2
vvc=2
uvg266=2
vvenc=2
vvdec=2
svtav1=1
svtvp9=2
flac=1
fdkaac=1
faac=2
exhale=2
mediainfo=2
soxB=2
ffmpegB2=1
ffmpegPath=$FfmpegPath
ffmpegUpdate=1
ffmpegChoice=1
ffmpegKeepLegacyOpts=0
mp4box=2
rtmpdump=2
mplayer2=2
mpv=2
bmx=2
curl=2
ffmbc=2
cyanrip2=2
redshift=2
ripgrep=2
jq=2
dssim=2
avs2=2
dovitool=2
hdr10plustool=2
gifski=3
jo=2
vlc=2
CC=2
zlib=1
cores=1
deleteSource=1
strip=1
pack=2
logging=1
updateSuite=2
timeStamp=1
ccache=2
noMintty=1
pkgUpdateTime=0
"@
    Set-Content -Path (Join-Path $suiteRoot 'build\media-autobuild_suite.ini') -Value $ini -Encoding ASCII
}

function Write-FfmpegOptions {
    $options = @'
--disable-autodetect
--enable-gpl
--enable-version3
--enable-nonfree
--enable-static
--disable-shared
--enable-ffmpeg
--enable-ffprobe
--enable-ffplay
--disable-debug
--disable-doc
--enable-runtime-cpudetect
--enable-x86asm
--enable-pthreads
--cpu=raptorlake
--extra-cflags=-O3 -march=raptorlake -mtune=raptorlake
--extra-cxxflags=-O3 -march=raptorlake -mtune=raptorlake
--extra-ldflags=-static
--extra-libs=-lcfgmgr32
--enable-bzlib
--enable-iconv
--enable-lzma
--enable-zlib
--enable-openssl
--disable-gnutls
--disable-schannel
--enable-sdl2
--enable-fontconfig
--enable-libass
--enable-libfreetype
--enable-libfribidi
--enable-libharfbuzz
--enable-libxml2
--enable-libmp3lame
--enable-libopus
--enable-libvorbis
--enable-libtheora
--enable-libsoxr
--enable-librubberband
--enable-libspeex
--enable-libtwolame
--enable-libgsm
--enable-libopencore-amrnb
--enable-libopencore-amrwb
--enable-libvo-amrwbenc
--enable-libfdk-aac
--enable-libx264
--enable-libx265
--enable-libvpx
--enable-libaom
--enable-libdav1d
--enable-librav1e
--enable-libsvtav1
--enable-libwebp
--enable-libopenjpeg
--enable-libjxl
--enable-libvmaf
--enable-libplacebo
--enable-libzimg
--enable-libvidstab
--enable-libbluray
--enable-libdvdnav
--enable-libdvdread
--enable-libcdio
--enable-chromaprint
--enable-vulkan
--enable-vulkan-static
--enable-d3d11va
--enable-d3d12va
--disable-dxva2
--enable-ffnvcodec
--enable-nvenc
--enable-nvdec
--enable-cuvid
--enable-cuda-llvm
--disable-cuda-nvcc
--disable-libnpp
--disable-amf
--disable-libmfx
--disable-libvpl
--disable-opencl
--disable-opengl
--disable-vapoursynth
--disable-avisynth
--disable-frei0r
--disable-libtesseract
--disable-libaribb24
--disable-librist
--disable-libsrt
--disable-librtmp
--disable-libssh
--disable-libzmq
--disable-openal
--disable-decklink
--disable-libdc1394
--disable-indev=dshow
--disable-indev=gdigrab
--disable-outdev=sdl
--enable-network
--disable-protocols
--enable-protocol=file
--enable-protocol=pipe
--enable-protocol=concat
--enable-protocol=crypto
--enable-protocol=data
--enable-protocol=http
--enable-protocol=https
--enable-protocol=httpproxy
--enable-protocol=tcp
--enable-protocol=tls
'@
    Set-Content -Path (Join-Path $suiteRoot 'build\ffmpeg_options.txt') -Value $options -Encoding ASCII
}

function Patch-MabsLibvpxIncludePath {
    $scriptPath = Join-Path $suiteRoot 'build\media-suite_compile.sh'
    if (-not (Test-Path $scriptPath)) {
        throw 'The MABS compile script is missing; cannot apply the libvpx include-path fix.'
    }

    $content = [IO.File]::ReadAllText($scriptPath)
    $marker = '# GParty libvpx generated-include patch v2.'
    if ($content.Contains($marker)) { return }

    $newline = if ($content.Contains("`r`n")) { "`r`n" } else { "`n" }
    $pristine = @(
        '    sed -i ''s;HAVE_GNU_STRIP=yes;HAVE_GNU_STRIP=no;'' -- ./*.mk'
        '    do_make'
    ) -join $newline
    $legacy = @(
        '    sed -i ''s;HAVE_GNU_STRIP=yes;HAVE_GNU_STRIP=no;'' -- ./*.mk'
        '    # GParty: force libvpx to include its generated out-of-tree build directory.'
        '    sed -i ''s;$(CC) $(INTERNAL_CFLAGS) $(CFLAGS);$(CC) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CFLAGS);g'' Makefile'
        '    sed -i ''s;$(CXX) $(INTERNAL_CFLAGS) $(CXXFLAGS);$(CXX) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CXXFLAGS);g'' Makefile'
        '    do_make'
    ) -join $newline

    [string[]]$candidates = @($pristine, $legacy) | Where-Object { $content.Contains($_) }
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one supported libvpx build hook in MABS, found $($candidates.Count)."
    }

    $replacement = @(
        '    sed -i ''s;HAVE_GNU_STRIP=yes;HAVE_GNU_STRIP=no;'' -- ./*.mk'
        '    # GParty libvpx generated-include patch v2.'
        '    test -f Makefile || { echo "libvpx Makefile was not generated." >&2; exit 1; }'
        '    test -s vpx_config.h || { echo "libvpx vpx_config.h was not generated." >&2; exit 1; }'
        '    sed -i ''s;$(CC) $(INTERNAL_CFLAGS) $(CFLAGS);$(CC) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CFLAGS);g'' Makefile'
        '    sed -i ''s;$(CXX) $(INTERNAL_CFLAGS) $(CXXFLAGS);$(CXX) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CXXFLAGS);g'' Makefile'
        '    sed -i ''s;$(AS) $(ASFLAGS);$(AS) -I$(CURDIR)/ $(ASFLAGS);g'' Makefile'
        '    sed -i ''s;--depfile=$@ $(ASFLAGS);--depfile=$@ -I$(CURDIR)/ $(ASFLAGS);g'' Makefile'
        '    grep -Fq ''$(CC) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CFLAGS)'' Makefile || { echo "libvpx C include-path patch did not apply." >&2; exit 1; }'
        '    grep -Fq ''$(CXX) -I$(CURDIR) $(INTERNAL_CFLAGS) $(CXXFLAGS)'' Makefile || { echo "libvpx C++ include-path patch did not apply." >&2; exit 1; }'
        '    grep -Fq ''$(AS) -I$(CURDIR)/ $(ASFLAGS)'' Makefile || { echo "libvpx assembler include-path patch did not apply." >&2; exit 1; }'
        '    grep -Fq -- ''--depfile=$@ -I$(CURDIR)/ $(ASFLAGS)'' Makefile || { echo "libvpx assembler dependency-path patch did not apply." >&2; exit 1; }'
        '    if grep -Fq ''$(CC) $(INTERNAL_CFLAGS) $(CFLAGS)'' Makefile || grep -Fq ''$(CXX) $(INTERNAL_CFLAGS) $(CXXFLAGS)'' Makefile || grep -Fq ''$(AS) $(ASFLAGS)'' Makefile || grep -Fq -- ''--depfile=$@ $(ASFLAGS)'' Makefile; then'
        '        echo "libvpx still contains an unpatched generated-include command." >&2'
        '        exit 1'
        '    fi'
        '    do_make'
    ) -join $newline

    $content = $content.Replace($candidates[0], $replacement)
    [IO.File]::WriteAllText($scriptPath, $content, [System.Text.UTF8Encoding]::new($false))
}

function Resolve-LatestStableTag {
    Write-Stage 'Resolve latest stable FFmpeg tag'
    $tags = Invoke-RestMethod -Headers @{ 'User-Agent' = 'custom-ffmpeg-builder' } -Uri 'https://api.github.com/repos/FFmpeg/FFmpeg/tags?per_page=100'
    $stable = $tags | Where-Object { $_.name -match '^n\d+\.\d+(\.\d+)?$' } | Sort-Object {
        [version](($_.name.TrimStart('n')) -replace '^([0-9]+\.[0-9]+)$','$1.0')
    } -Descending | Select-Object -First 1
    if (-not $stable) { throw 'Unable to resolve latest stable FFmpeg tag.' }
    return $stable.name
}

function Write-SourceCommits {
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path (Join-Path $suiteRoot '.git')) {
        $sha = (& git -C $suiteRoot rev-parse HEAD 2>$null | Select-Object -First 1)
        if ($sha) { $lines.Add("media-autobuild_suite=$sha") }
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
                        $lines.Add("$name=$sha")
                    }
                } catch {}
            }
    }
    $lines | Sort-Object -Unique | Set-Content -Path (Join-Path $metaRoot 'source-commits.txt') -Encoding UTF8
}

function Run-Mabs([string]$Label, [string]$FfmpegPath) {
    Write-Ini -FfmpegPath $FfmpegPath
    Write-FfmpegOptions

    $binDir = Join-Path $suiteRoot 'local64\bin-video'
    $expectedFfmpeg = Join-Path $binDir 'ffmpeg.exe'
    $beforeWriteTime = if (Test-Path $expectedFfmpeg) {
        (Get-Item -LiteralPath $expectedFfmpeg).LastWriteTimeUtc
    } else {
        [datetime]::MinValue
    }

    Invoke-Logged "Build $Label" { cmd.exe /d /c "cd /d $suiteRoot && media-autobuild_suite.bat" }

    if (-not (Test-Path -LiteralPath $expectedFfmpeg -PathType Leaf)) {
        throw "MABS completed but the expected $Label binary is missing: $expectedFfmpeg"
    }
    $afterWriteTime = (Get-Item -LiteralPath $expectedFfmpeg).LastWriteTimeUtc
    if ($afterWriteTime -le $beforeWriteTime) {
        throw "MABS did not refresh the expected $Label ffmpeg.exe; refusing to package a stale binary."
    }

    $target = Join-Path $outRoot $Label
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($name in 'ffmpeg.exe','ffprobe.exe','ffplay.exe') {
        $source = Join-Path $binDir $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "$name was not produced in the expected MABS bin-video directory for $Label."
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    return $target
}

function Assert-Features([string]$Folder, [string]$Label) {
    Write-Stage "Validate $Label features"
    $ffmpeg = Join-Path $Folder 'ffmpeg.exe'
    $checks = [ordered]@{
        encoders = @('libx264','libx265','libsvtav1','libaom-av1','librav1e','h264_nvenc','hevc_nvenc','av1_nvenc','libfdk_aac','libopus','libmp3lame')
        decoders = @('h264','hevc','av1','aac','opus','flac','ass','hdmv_pgs_subtitle','dvdsub')
        filters  = @('subtitles','libplacebo','vmaf','loudnorm','zscale','scale_cuda')
        indevs = @('lavfi')
        protocols = @('file','pipe','http','https','tcp','tls','crypto','data')
        hwaccels = @('cuda','d3d11va','d3d12va','vulkan')
    }
    foreach ($entry in $checks.GetEnumerator()) {
        $text = & $ffmpeg "-$($entry.Key)" 2>&1 | Out-String
        Set-Content -Path (Join-Path $Folder "$($entry.Key).txt") -Value $text -Encoding UTF8
        foreach ($required in $entry.Value) {
            $pattern = '(?m)^\s*(?:[A-Z\.]{3,8}\s+)?' + [regex]::Escape($required) + '(?:\s|$)'
            if ($text -notmatch $pattern) {
                throw "$Label is missing required $($entry.Key) feature: $required"
            }
        }
    }
    $version = & $ffmpeg -version 2>&1 | Out-String
    Set-Content -Path (Join-Path $Folder 'build-info.txt') -Value $version -Encoding UTF8
    if ($version -match '(?m)--enable-shared(?:\s|$)') {
        throw "$Label was configured with shared FFmpeg libraries."
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
        throw 'dumpbin.exe is unavailable, so static dependency verification cannot be trusted.'
    }

    foreach ($exe in Get-ChildItem $Folder -Filter *.exe) {
        $deps = & $dumpbinPath /dependents $exe.FullName 2>&1 | Out-String
        Add-Content -Path (Join-Path $Folder 'pe-dependencies.txt') -Value "`n[$($exe.Name)]`n$deps"
        $dependencyNames = [regex]::Matches($deps, '(?im)^\s*([A-Z0-9._-]+\.dll)\s*$') |
            ForEach-Object { $_.Groups[1].Value } |
            Sort-Object -Unique
        $forbidden = $dependencyNames | Where-Object {
            $name = $_
            ($name -notmatch '(?i)^(VULKAN-1|NVENCODEAPI64|NVCUVID|NVCUDA)\.dll$') -and
                (-not (Test-Path -LiteralPath (Join-Path ([Environment]::SystemDirectory) $name) -PathType Leaf))
        }
        if ($forbidden) { throw "$Label has non-system DLL dependencies:`n$($forbidden -join "`n")" }
    }
}

function Write-LocalValidation([string]$Folder) {
    $cmd = @'
@echo off
setlocal
cd /d "%~dp0"
echo === FFmpeg version ===
ffmpeg.exe -version || goto :fail
echo.
echo === NVIDIA encoders ===
ffmpeg.exe -hide_banner -encoders | findstr /i "nvenc" || goto :fail
echo.
echo === Hardware accelerators ===
ffmpeg.exe -hide_banner -hwaccels || goto :fail
echo.
echo === CUDA/NVENC test ===
ffmpeg.exe -hide_banner -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 -c:v h264_nvenc -y "%TEMP%\ffmpeg-nvenc-test.mp4" || goto :fail
ffprobe.exe -v error -show_streams "%TEMP%\ffmpeg-nvenc-test.mp4" || goto :fail
del /q "%TEMP%\ffmpeg-nvenc-test.mp4" 2>nul
echo.
echo ALL LOCAL HARDWARE TESTS PASSED.
pause
exit /b 0
:fail
echo.
echo A TEST FAILED. Save this window or rerun from Command Prompt and send the output.
pause
exit /b 1
'@
    Set-Content -Path (Join-Path $Folder 'verify-nvidia.cmd') -Value $cmd -Encoding ASCII
}

try {
    Write-Stage "Record $Variant environment"
    Get-ComputerInfo | Out-File (Join-Path $metaRoot "environment-$Variant.txt") -Encoding UTF8
    Write-SafeEnvironment -Path (Join-Path $metaRoot "environment-variables-$Variant.txt")

    if ($ReuseSuite) {
        if (-not (Test-Path (Join-Path $suiteRoot 'media-autobuild_suite.bat'))) {
            throw 'The reusable MABS workspace is missing.'
        }
    } else {
        if (Test-Path $suiteRoot) { Remove-Item $suiteRoot -Recurse -Force }
        Invoke-Logged 'Clone media-autobuild_suite fresh' { git clone --depth 1 https://github.com/m-ab-s/media-autobuild_suite.git $suiteRoot }
        Copy-Item (Join-Path $repoRoot '.github\ffmpeg-build\README.txt') $diagRoot -Force
    }

    Patch-MabsLibvpxIncludePath

    $versionsPath = Join-Path $metaRoot 'resolved-versions.txt'
    if ($Variant -eq 'stable') {
        $stableTag = Resolve-LatestStableTag
        Set-Content -Path $versionsPath -Value "stable=$stableTag`nmaster=HEAD at build time" -Encoding UTF8
        $folder = Run-Mabs -Label 'stable' -FfmpegPath "https://github.com/FFmpeg/FFmpeg.git#tag=$stableTag"
    } else {
        if (-not (Test-Path $versionsPath)) {
            Set-Content -Path $versionsPath -Value "stable=not built`nmaster=HEAD at build time" -Encoding UTF8
        }
        $folder = Run-Mabs -Label 'master' -FfmpegPath 'https://github.com/FFmpeg/FFmpeg.git#branch=master'
    }

    Assert-Features -Folder $folder -Label $Variant
    Write-LocalValidation -Folder $folder
    Write-SourceCommits
    Copy-Item $versionsPath $outRoot -Force
    Copy-Item (Join-Path $metaRoot 'source-commits.txt') $outRoot -Force
    Copy-Item (Join-Path $repoRoot '.github\ffmpeg-build\README.txt') $outRoot -Force
    Remove-Item (Join-Path $diagRoot 'failed-step.txt') -Force -ErrorAction SilentlyContinue
    Stop-Transcript | Out-Null
    exit 0
}
catch {
    $_ | Format-List * -Force | Out-File (Join-Path $diagRoot "SUMMARY-$Variant.txt") -Encoding UTF8
    Write-Error $_
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
