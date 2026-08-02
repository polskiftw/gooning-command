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
$mabsCommit = '0b9f91cb247cb1dce23d81d9ed7ee60ae26fb78c'
$logRoot = Join-Path $diagRoot 'logs'
$metaRoot = Join-Path $diagRoot 'metadata'
New-Item -ItemType Directory -Force -Path $buildRoot, $outRoot, $diagRoot, $logRoot, $metaRoot | Out-Null

$transcript = Join-Path $logRoot "workflow-$Variant-transcript.txt"
Start-Transcript -Path $transcript -Force | Out-Null

function Write-Stage([string]$Message) {
    Write-Host "`n========== $Message ==========" -ForegroundColor Cyan
    Set-Content -Path (Join-Path $diagRoot 'failed-step.txt') -Value $Message -Encoding UTF8
}

function Get-LogPath([string]$Name) {
    return Join-Path $logRoot (($Name -replace '[^A-Za-z0-9._-]', '_') + '.log')
}

function Invoke-Logged([string]$Name, [scriptblock]$Command, [switch]$AllowNonZeroExit) {
    Write-Stage $Name
    # Out-Host keeps the native process output visible without returning thousands
    # of log lines as the function's value when the caller captures the exit code.
    & $Command 2>&1 | Tee-Object -FilePath (Get-LogPath $Name) | Out-Host
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
        throw "$Name failed with exit code $exitCode"
    }
    return [int]$exitCode
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
--disable-indev=vfwcap
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
    if ($content.Contains($marker)) {
        foreach ($proof in '-I$(CURDIR) $(INTERNAL_CFLAGS)', '-I$(CURDIR)/ $(ASFLAGS)', '--depfile=$@ -I$(CURDIR)/ $(ASFLAGS)') {
            if (-not $content.Contains($proof)) { throw "Existing libvpx patch is incomplete; missing: $proof" }
        }
        return
    }

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

function Patch-MabsCleanup {
    $scriptPath = Join-Path $suiteRoot 'build\media-suite_helper.sh'
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw 'The MABS helper script is missing; cannot harden source cleanup.'
    }
    $content = [IO.File]::ReadAllText($scriptPath)
    $marker = '# GParty cleanup hardening v1.'
    if ($content.Contains($marker)) {
        foreach ($proof in 'cargo_bin="$(command -v cargo)"', 'PATH="/usr/bin:$MINGW_PREFIX/bin" find', '(patches|extras|ffmpeg-git|$)') {
            if (-not $content.Contains($proof)) { throw "Existing cleanup patch is incomplete; missing: $proof" }
        }
        return
    }

    $cargoAnchor = '        find . -maxdepth 3 -type f -name "Cargo.toml" -execdir cargo clean -q ";"'
    $removeAnchor = '                grep -Ev "^$LOCALBUILDDIR/(patches|extras|$)" | sort -u | xargs -r rm -rf'
    if (([regex]::Matches($content, [regex]::Escape($cargoAnchor))).Count -ne 1) {
        throw 'Expected exactly one MABS Cargo cleanup command.'
    }
    if (([regex]::Matches($content, [regex]::Escape($removeAnchor))).Count -ne 1) {
        throw 'Expected exactly one MABS source-removal filter.'
    }

    $cargoReplacement = @'
        # GParty cleanup hardening v1. GNU find refuses -execdir when PATH
        # contains the current directory. Resolve Cargo first, then give find
        # a fixed safe PATH so successful builds do not acquire exit code 1.
        cargo_bin="$(command -v cargo)"
        PATH="/usr/bin:$MINGW_PREFIX/bin" find . -maxdepth 3 -type f -name "Cargo.toml" -execdir "$cargo_bin" clean -q ";"
'@
    $removeReplacement = '                grep -Ev "^$LOCALBUILDDIR/(patches|extras|ffmpeg-git|$)" | sort -u | xargs -r rm -rf'
    $content = $content.Replace($cargoAnchor, $cargoReplacement.TrimEnd("`r","`n"))
    $content = $content.Replace($removeAnchor, $removeReplacement)
    [IO.File]::WriteAllText($scriptPath, $content, [System.Text.UTF8Encoding]::new($false))
}

function Resolve-LatestStableTag {
    Write-Stage 'Resolve latest stable FFmpeg tag with Git'
    $remoteTags = & git ls-remote --tags --refs https://github.com/FFmpeg/FFmpeg.git 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query FFmpeg tags with Git:`n$($remoteTags | Out-String)"
    }

    $stable = $remoteTags |
        ForEach-Object {
            if ($_ -match 'refs/tags/(n\d+\.\d+(?:\.\d+)?)$') { $Matches[1] }
        } |
        Where-Object { $_ } |
        Sort-Object {
            [version](($_.TrimStart('n')) -replace '^([0-9]+\.[0-9]+)$','$1.0')
        } -Descending |
        Select-Object -First 1

    if (-not $stable) { throw 'Unable to resolve latest stable FFmpeg tag from Git.' }
    return $stable
}

function Resolve-RemoteCommit([string]$Ref) {
    $result = & git ls-remote https://github.com/FFmpeg/FFmpeg.git $Ref 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve FFmpeg ref '$Ref':`n$($result | Out-String)"
    }
    $matches = @($result | ForEach-Object {
        if ($_ -match '^([0-9a-f]{40})\s+') { $Matches[1].ToLowerInvariant() }
    })
    if ($matches.Count -ne 1) {
        throw "Expected exactly one commit for FFmpeg ref '$Ref', found $($matches.Count)."
    }
    return $matches[0]
}

function Resolve-RemoteTagCommit([string]$Tag) {
    $result = & git ls-remote https://github.com/FFmpeg/FFmpeg.git "refs/tags/$Tag" "refs/tags/$Tag^{}" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve FFmpeg tag '$Tag':`n$($result | Out-String)"
    }
    $direct = $null
    $peeled = $null
    foreach ($line in $result) {
        if ($line -match '^([0-9a-f]{40})\s+refs/tags/.+\^\{\}$') { $peeled = $Matches[1].ToLowerInvariant() }
        elseif ($line -match '^([0-9a-f]{40})\s+refs/tags/') { $direct = $Matches[1].ToLowerInvariant() }
    }
    $commit = if ($peeled) { $peeled } else { $direct }
    if (-not $commit) { throw "FFmpeg tag '$Tag' did not resolve to a commit." }
    return $commit
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

function Find-FfmpegSource {
    $candidates = @(Get-ChildItem -Path (Join-Path $suiteRoot 'build') -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.git') } |
        Where-Object {
            $remote = & git -C $_.FullName remote get-url origin 2>$null
            $LASTEXITCODE -eq 0 -and $remote -match '(?i)(?:github\.com[/:])FFmpeg/FFmpeg(?:\.git)?$'
        })
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one FFmpeg source checkout, found $($candidates.Count)."
    }
    return $candidates[0].FullName
}

function Assert-SourceIdentity(
    [string]$Label,
    [string]$ExpectedStableTag,
    [string]$ExpectedStableCommit,
    [string]$ExpectedMasterCommit
) {
    Write-Stage "Validate $Label source identity"
    $source = Find-FfmpegSource
    $head = (& git -C $source rev-parse HEAD 2>&1 | Select-Object -First 1).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
        throw "Unable to resolve the $Label FFmpeg source commit."
    }

    if ($Label -eq 'stable') {
        $tagCommit = (& git -C $source rev-list -n 1 "$ExpectedStableTag^{commit}" 2>&1 | Select-Object -First 1).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0 -or $head -ne $tagCommit -or $head -ne $ExpectedStableCommit) {
            throw "Stable source mismatch: HEAD $head is not exact tag $ExpectedStableTag resolved before build ($ExpectedStableCommit; local tag $tagCommit)."
        }
    } else {
        if ($head -ne $ExpectedMasterCommit) {
            throw "Master source mismatch: HEAD $head is not the exact master commit resolved at build start ($ExpectedMasterCommit)."
        }
    }

    Set-Content -Path (Join-Path $metaRoot "ffmpeg-source-$Label.txt") -Value @(
        "path=$source"
        "commit=$head"
        "stable_tag=$ExpectedStableTag"
        "stable_at_start=$ExpectedStableCommit"
        "master_at_start=$ExpectedMasterCommit"
    ) -Encoding UTF8
    return $head
}

function Run-Mabs(
    [string]$Label,
    [string]$FfmpegPath,
    [string]$ExpectedStableTag = '',
    [string]$ExpectedStableCommit = '',
    [string]$ExpectedMasterCommit = ''
) {
    Write-Ini -FfmpegPath $FfmpegPath
    Write-FfmpegOptions
    $optionsPath = Join-Path $suiteRoot 'build\ffmpeg_options.txt'
    $expectedOptionsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $optionsPath).Hash

    $binDir = Join-Path $suiteRoot 'local64\bin-video'
    $requiredExecutables = @('ffmpeg.exe','ffprobe.exe','ffplay.exe')
    $target = Join-Path $outRoot $Label
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($name in $requiredExecutables) {
        Remove-Item -LiteralPath (Join-Path $binDir $name) -Force -ErrorAction SilentlyContinue
    }
    $buildStartedUtc = [datetime]::UtcNow

    $mabsExitCode = Invoke-Logged "Build $Label" { cmd.exe /d /c "cd /d $suiteRoot && media-autobuild_suite.bat" } -AllowNonZeroExit

    # The old executables were deleted before MABS started, so anything present now
    # was produced by this invocation. Stage every available binary immediately,
    # before trusting the log marker, patch checks, options file, source checkout, or
    # any feature validator. A validator bug must never destroy a four-hour build.
    $recovered = [System.Collections.Generic.List[string]]::new()
    foreach ($name in $requiredExecutables) {
        $source = Join-Path $binDir $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $target $name) -Force
            $item = Get-Item -LiteralPath $source
            $recovered.Add("$name`t$($item.Length)`t$($item.LastWriteTimeUtc.ToString('o'))")
        }
    }
    Set-Content -LiteralPath (Join-Path $target 'recovery-stage.txt') -Value @(
        "label=$Label"
        "mabs_exit_code=$mabsExitCode"
        "build_started_utc=$($buildStartedUtc.ToString('o'))"
        "staged_utc=$([datetime]::UtcNow.ToString('o'))"
        'name size_bytes source_last_write_utc'
        $recovered
    ) -Encoding UTF8

    $mabsLog = Get-LogPath "Build $Label"
    if (-not (Test-Path -LiteralPath $mabsLog -PathType Leaf)) {
        throw "The $Label MABS log is missing."
    }
    $mabsText = [IO.File]::ReadAllText($mabsLog)
    if ($mabsText -notmatch '(?i)\bCompilation successful\b') {
        throw "MABS did not print its compilation-success marker for $Label (exit code $mabsExitCode)."
    }
    if ($mabsExitCode -ne 0) {
        Write-Warning "MABS returned exit code $mabsExitCode after printing its success marker; validating all produced binaries before accepting it."
    }
    $actualOptionsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $optionsPath).Hash
    if ($actualOptionsHash -ne $expectedOptionsHash) {
        throw "MABS modified ffmpeg_options.txt during the $Label build; validation inputs are no longer trustworthy."
    }
    if (-not ([IO.File]::ReadAllText((Join-Path $suiteRoot 'build\media-suite_compile.sh')).Contains('# GParty libvpx generated-include patch v2.'))) {
        throw 'The libvpx patch disappeared during the build.'
    }
    if (-not ([IO.File]::ReadAllText((Join-Path $suiteRoot 'build\media-suite_helper.sh')).Contains('# GParty cleanup hardening v1.'))) {
        throw 'The cleanup hardening patch disappeared during the build.'
    }

    foreach ($name in $requiredExecutables) {
        $source = Join-Path $binDir $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "MABS reported success but did not freshly produce $name for $Label."
        }
        $item = Get-Item -LiteralPath $source
        if ($item.Length -lt 1MB -or $item.LastWriteTimeUtc -lt $buildStartedUtc.AddSeconds(-2)) {
            throw "$name is empty, implausibly small, or older than the $Label build invocation."
        }
    }

    $sourceCommit = Assert-SourceIdentity -Label $Label -ExpectedStableTag $ExpectedStableTag -ExpectedStableCommit $ExpectedStableCommit -ExpectedMasterCommit $ExpectedMasterCommit
    Copy-Item -LiteralPath (Join-Path $metaRoot "ffmpeg-source-$Label.txt") -Destination (Join-Path $target 'source-identity.txt') -Force
    return [PSCustomObject]@{ Folder = $target; SourceCommit = $sourceCommit }
}

function Assert-Features(
    [string]$Folder,
    [string]$Label,
    [string]$SourceCommit,
    [string]$StableTag = ''
) {
    Write-Stage "Validate $Label features"
    $ffmpeg = Join-Path $Folder 'ffmpeg.exe'
    $reports = @{}
    $checks = [ordered]@{
        encoders = @('libx264','libx265','libvpx-vp9','libsvtav1','libaom-av1','librav1e','h264_nvenc','hevc_nvenc','av1_nvenc','libfdk_aac','libopus','libmp3lame','libvorbis','libtheora','libwebp_anim')
        decoders = @('h264','hevc','av1','libdav1d','aac','opus','flac','ass','pgssub','dvdsub','libjxl')
        filters  = @('ass','subtitles','libplacebo','libvmaf','loudnorm','zscale','scale_cuda','vidstabdetect','vidstabtransform','rubberband')
        devices = @('lavfi')
        protocols = @('file','pipe','concat','crypto','data','http','https','httpproxy','tcp','tls')
        hwaccels = @('cuda','d3d11va','d3d12va','vulkan')
        muxers = @('matroska','webm','mp4','gif','image2','null')
        demuxers = @('concat','matroska','mov','gif','image2')
    }
    foreach ($entry in $checks.GetEnumerator()) {
        $text = & $ffmpeg "-$($entry.Key)" 2>&1 | Out-String
        $reportExitCode = $LASTEXITCODE
        Set-Content -Path (Join-Path $Folder "$($entry.Key).txt") -Value $text -Encoding UTF8
        if ($reportExitCode -ne 0) {
            throw "$Label feature report command '-$($entry.Key)' failed with exit code $reportExitCode."
        }
        $reports[$entry.Key] = $text
        foreach ($required in $entry.Value) {
            $pattern = '(?m)^\s*(?:[A-Z\.]{1,8}\s+)?(?:[A-Za-z0-9_.-]+,)*' + [regex]::Escape($required) + '(?:,[A-Za-z0-9_.-]+)*(?:\s|$)'
            if ($text -notmatch $pattern) {
                throw "$Label is missing required $($entry.Key) feature: $required"
            }
        }
    }

    # A configure line can claim that a component was disabled while the runtime
    # tables still expose it. Check the concrete feature names for every disabled
    # family that has an observable runtime representation.
    $forbiddenFeatures = [ordered]@{
        encoders = @('h264_amf','hevc_amf','av1_amf','h264_qsv','hevc_qsv','av1_qsv','mjpeg_qsv','mpeg2_qsv','vp9_qsv')
        decoders = @('h264_qsv','hevc_qsv','av1_qsv','mjpeg_qsv','mpeg2_qsv','vc1_qsv','vp8_qsv','vp9_qsv','libaribb24')
        filters = @('avgblur_opencl','boxblur_opencl','colorkey_opencl','convolution_opencl','deshake_opencl','dilation_opencl','erosion_opencl','nlmeans_opencl','overlay_opencl','pad_opencl','program_opencl','remap_opencl','roberts_opencl','sobel_opencl','tonemap_opencl','transpose_opencl','unsharp_opencl','xfade_opencl','frei0r','frei0r_src','ocr')
        devices = @('openal','decklink','libdc1394','dshow','gdigrab','vfwcap','sdl','sdl2')
        protocols = @('rist','srt','rtmp','rtmpe','rtmps','rtmpt','rtmpte','rtmpts','ssh','zmq')
        hwaccels = @('dxva2','qsv')
        demuxers = @('avisynth','vapoursynth')
    }
    foreach ($entry in $forbiddenFeatures.GetEnumerator()) {
        foreach ($forbiddenName in $entry.Value) {
            $pattern = '(?m)^\s*(?:[A-Z\.]{1,8}\s+)?(?:[A-Za-z0-9_.-]+,)*' + [regex]::Escape($forbiddenName) + '(?:,[A-Za-z0-9_.-]+)*(?:\s|$)'
            if ($reports[$entry.Key] -match $pattern) {
                throw "$Label unexpectedly exposes disabled $($entry.Key) feature: $forbiddenName"
            }
        }
    }
    $forbiddenRuntimeFamilies = [ordered]@{
        encoders = '(?im)^\s*[A-Z\.]{1,8}\s+[A-Za-z0-9_.-]+_(?:amf|qsv)(?:\s|$)'
        decoders = '(?im)^\s*[A-Z\.]{1,8}\s+[A-Za-z0-9_.-]+_qsv(?:\s|$)'
        filters = '(?im)^\s*[A-Z\.]{1,8}\s+[A-Za-z0-9_.-]*(?:opencl|_qsv|_npp)[A-Za-z0-9_.-]*(?:\s|$)'
    }
    foreach ($entry in $forbiddenRuntimeFamilies.GetEnumerator()) {
        if ($reports[$entry.Key] -match $entry.Value) {
            throw "$Label exposes a disabled runtime feature family in $($entry.Key): $($Matches[0].Trim())"
        }
    }

    $version = & $ffmpeg -version 2>&1 | Out-String
    $versionExitCode = $LASTEXITCODE
    Set-Content -Path (Join-Path $Folder 'build-info.txt') -Value $version -Encoding UTF8
    if ($versionExitCode -ne 0) { throw "$Label ffmpeg.exe -version failed with exit code $versionExitCode." }
    $toolVersions = [ordered]@{ 'ffmpeg.exe' = $version }
    foreach ($name in 'ffprobe.exe','ffplay.exe') {
        $tool = Join-Path $Folder $name
        $toolVersion = & $tool -version 2>&1 | Out-String
        $toolExitCode = $LASTEXITCODE
        Set-Content -Path (Join-Path $Folder (($name -replace '\.exe$','') + '-version.txt')) -Value $toolVersion -Encoding UTF8
        if ($toolExitCode -ne 0 -or $toolVersion -notmatch '(?im)^ff(?:probe|play) version\s+') {
            throw "$Label $name did not return a valid version report (exit code $toolExitCode)."
        }
        $toolVersions[$name] = $toolVersion
    }

    $expectedOptions = @(Get-Content -LiteralPath (Join-Path $suiteRoot 'build\ffmpeg_options.txt') |
        Where-Object { $_ -match '^--(?:enable|disable)-' } |
        Where-Object { $_ -notin @('--enable-static','--disable-shared') })
    foreach ($option in $expectedOptions) {
        if ($version -notmatch ('(?:^|\s)' + [regex]::Escape($option) + '(?:\s|$)')) {
            throw "$Label build configuration dropped requested option: $option"
        }
    }
    if ($version -match '(?:^|\s)--enable-shared(?:\s|$)') {
        throw "$Label was configured with shared FFmpeg libraries."
    }
    $stableVersion = $StableTag.TrimStart('n')
    foreach ($toolEntry in $toolVersions.GetEnumerator()) {
        $toolBase = [IO.Path]::GetFileNameWithoutExtension($toolEntry.Key)
        if ($toolEntry.Value -notmatch ('(?im)^' + [regex]::Escape($toolBase) + ' version\s+')) {
            throw "$Label $($toolEntry.Key) has a version report for the wrong executable."
        }
        if ($Label -eq 'stable' -and $toolEntry.Value -notmatch ('(?im)^' + [regex]::Escape($toolBase) + ' version\s+n?' + [regex]::Escape($stableVersion) + '(?:[-\s]|$)')) {
            throw "Stable $($toolEntry.Key) does not identify itself as resolved tag $StableTag."
        }
        if ($Label -eq 'master' -and $toolEntry.Value -notmatch ('(?i)' + [regex]::Escape($SourceCommit.Substring(0, 7)))) {
            throw "Master $($toolEntry.Key) version does not contain validated source commit prefix $($SourceCommit.Substring(0, 7))."
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
        throw 'dumpbin.exe is unavailable, so static dependency verification cannot be trusted.'
    }
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
    # This is intentionally an explicit allowlist, not "anything found in System32".
    # It is the complete ordinary Windows import set observed across the audited
    # ffmpeg/ffprobe/ffplay binaries. A newly introduced OS dependency must be
    # reviewed and added deliberately instead of passing merely because it exists.
    $allowedWindowsDlls = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    @(
        'ADVAPI32.dll','bcrypt.dll','CFGMGR32.dll','CRYPT32.dll',
        'GDI32.dll','IMM32.dll','KERNEL32.dll','ntdll.dll','ole32.dll','OLEAUT32.dll',
        'SETUPAPI.dll','SHELL32.dll','SHLWAPI.dll','USER32.dll','VERSION.dll',
        'WINMM.dll','WS2_32.dll'
    ) | ForEach-Object { [void]$allowedWindowsDlls.Add($_) }
    $allowedDriverDlls = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    @('VULKAN-1.dll','NVENCODEAPI64.dll','NVCUVID.dll','NVCUDA.dll') |
        ForEach-Object { [void]$allowedDriverDlls.Add($_) }

    Set-Content -Path (Join-Path $Folder 'pe-dependencies.txt') -Value "dumpbin=$dumpbinPath" -Encoding UTF8
    foreach ($exe in Get-ChildItem $Folder -Filter *.exe) {
        $headers = & $dumpbinPath /headers $exe.FullName 2>&1 | Out-String
        $headersExitCode = $LASTEXITCODE
        Add-Content -Path (Join-Path $Folder 'pe-headers.txt') -Value "`n[$($exe.Name)]`n$headers"
        if ($headersExitCode -ne 0) {
            throw "dumpbin /headers failed for $($exe.Name) with exit code $headersExitCode."
        }
        if ($headers -notmatch '(?im)^\s*8664 machine \(x64\)\s*$') {
            throw "$Label $($exe.Name) is not an AMD64 PE32+ executable."
        }
        if ($headers -notmatch '(?im)^\s*20B\s+magic\s+#\s+\(PE32\+\)\s*$') {
            throw "$Label $($exe.Name) is AMD64 but does not have the PE32+ optional-header magic."
        }

        $deps = & $dumpbinPath /dependents $exe.FullName 2>&1 | Out-String
        $depsExitCode = $LASTEXITCODE
        Add-Content -Path (Join-Path $Folder 'pe-dependencies.txt') -Value "`n[$($exe.Name)]`n$deps"
        if ($depsExitCode -ne 0) {
            throw "dumpbin /dependents failed for $($exe.Name) with exit code $depsExitCode."
        }
        $dependencyNames = [regex]::Matches($deps, '(?im)^\s*([A-Z0-9._-]+\.dll)\s*$') |
            ForEach-Object { $_.Groups[1].Value } |
            Sort-Object -Unique
        if (-not $dependencyNames) {
            throw "dumpbin returned no parseable dependencies for $($exe.Name); refusing a false static-link pass."
        }
        $forbidden = $dependencyNames | Where-Object {
            $name = $_
            $isTargetDriverRuntime = $allowedDriverDlls.Contains($name)
            # API-set aliases have a rigid canonical version suffix. This accepts
            # Windows loader contracts without turning every api-ms-win-* string
            # into a blanket third-party-DLL bypass.
            $hasApiSetGrammar = $name -match '(?i)^(API|EXT)-MS-(WIN|ONECORE)-[A-Z0-9-]+-L\d+-\d+(?:-\d+)?\.dll$'
            $isWindowsApiSet = $hasApiSetGrammar -and
                $apiSetContracts.Contains(([IO.Path]::GetFileNameWithoutExtension($name)))
            (-not $isTargetDriverRuntime) -and
                (-not $isWindowsApiSet) -and
                (-not ($allowedWindowsDlls.Contains($name) -and
                    (Test-Path -LiteralPath (Join-Path ([Environment]::SystemDirectory) $name) -PathType Leaf)))
        }
        if ($forbidden) { throw "$Label has non-system DLL dependencies:`n$($forbidden -join "`n")" }
    }
}

function Assert-CpuSmokeTest([string]$Folder, [string]$Label) {
    Write-Stage "Run $Label CPU encode, mux, probe, and decode smoke test"
    $ffmpeg = Join-Path $Folder 'ffmpeg.exe'
    $ffprobe = Join-Path $Folder 'ffprobe.exe'
    $smokePath = Join-Path $Folder '_validator-smoke.mp4'
    $reportPath = Join-Path $Folder 'cpu-smoke-test.txt'
    Remove-Item -LiteralPath $smokePath -Force -ErrorAction SilentlyContinue

    try {
        $encodeOutput = & $ffmpeg -hide_banner -loglevel warning `
            -f lavfi -i 'testsrc2=size=320x240:rate=10' `
            -f lavfi -i 'sine=frequency=1000:sample_rate=48000' `
            -t 1 -vf 'scale=160:120,format=yuv420p' `
            -c:v libx264 -preset ultrafast -c:a libfdk_aac `
            -movflags '+faststart' -y $smokePath 2>&1 | Out-String
        $encodeExitCode = $LASTEXITCODE
        Set-Content -LiteralPath $reportPath -Value "[encode exit=$encodeExitCode]`n$encodeOutput" -Encoding UTF8
        if ($encodeExitCode -ne 0 -or -not (Test-Path -LiteralPath $smokePath -PathType Leaf)) {
            throw "$Label CPU smoke encode/mux failed with exit code $encodeExitCode."
        }
        if ((Get-Item -LiteralPath $smokePath).Length -lt 1024) {
            throw "$Label CPU smoke output is implausibly small."
        }

        $probeOutput = & $ffprobe -v error -show_entries 'stream=index,codec_type,codec_name,width,height' -of json $smokePath 2>&1 | Out-String
        $probeExitCode = $LASTEXITCODE
        Add-Content -LiteralPath $reportPath -Value "`n[probe exit=$probeExitCode]`n$probeOutput" -Encoding UTF8
        if ($probeExitCode -ne 0) { throw "$Label CPU smoke probe failed with exit code $probeExitCode." }
        try { $probe = $probeOutput | ConvertFrom-Json } catch { throw "$Label CPU smoke probe did not return valid JSON." }
        $video = @($probe.streams | Where-Object codec_type -eq 'video')
        $audio = @($probe.streams | Where-Object codec_type -eq 'audio')
        if ($video.Count -ne 1 -or $video[0].codec_name -ne 'h264' -or $video[0].width -ne 160 -or $video[0].height -ne 120) {
            throw "$Label CPU smoke probe did not confirm the expected H.264 160x120 video stream."
        }
        if ($audio.Count -ne 1 -or $audio[0].codec_name -ne 'aac') {
            throw "$Label CPU smoke probe did not confirm the expected AAC audio stream."
        }

        $decodeOutput = & $ffmpeg -hide_banner -loglevel warning -i $smokePath `
            -map '0:v:0' -map '0:a:0' -f null NUL 2>&1 | Out-String
        $decodeExitCode = $LASTEXITCODE
        Add-Content -LiteralPath $reportPath -Value "`n[decode exit=$decodeExitCode]`n$decodeOutput" -Encoding UTF8
        if ($decodeExitCode -ne 0) { throw "$Label CPU smoke decode failed with exit code $decodeExitCode." }
        Add-Content -LiteralPath $reportPath -Value "`nCPU_SMOKE_TEST_PASSED" -Encoding UTF8
    }
    finally {
        Remove-Item -LiteralPath $smokePath -Force -ErrorAction SilentlyContinue
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
echo === H.264 NVENC and CUDA decode ===
ffmpeg.exe -hide_banner -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 -c:v h264_nvenc -y "%TEMP%\ffmpeg-h264-nvenc-test.mp4" || goto :fail
ffprobe.exe -v error -show_streams "%TEMP%\ffmpeg-h264-nvenc-test.mp4" || goto :fail
ffmpeg.exe -hide_banner -hwaccel cuda -i "%TEMP%\ffmpeg-h264-nvenc-test.mp4" -f null NUL || goto :fail
echo.
echo === HEVC NVENC ===
ffmpeg.exe -hide_banner -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 -c:v hevc_nvenc -y "%TEMP%\ffmpeg-hevc-nvenc-test.mkv" || goto :fail
ffprobe.exe -v error -show_streams "%TEMP%\ffmpeg-hevc-nvenc-test.mkv" || goto :fail
echo.
echo === AV1 NVENC ===
ffmpeg.exe -hide_banner -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 -c:v av1_nvenc -y "%TEMP%\ffmpeg-av1-nvenc-test.mkv" || goto :fail
ffprobe.exe -v error -show_streams "%TEMP%\ffmpeg-av1-nvenc-test.mkv" || goto :fail
del /q "%TEMP%\ffmpeg-h264-nvenc-test.mp4" "%TEMP%\ffmpeg-hevc-nvenc-test.mkv" "%TEMP%\ffmpeg-av1-nvenc-test.mkv" 2>nul
echo.
echo ALL LOCAL HARDWARE TESTS PASSED.
pause
exit /b 0
:fail
del /q "%TEMP%\ffmpeg-h264-nvenc-test.mp4" "%TEMP%\ffmpeg-hevc-nvenc-test.mkv" "%TEMP%\ffmpeg-av1-nvenc-test.mkv" 2>nul
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
        Invoke-Logged 'Initialize media-autobuild_suite checkout' { git init $suiteRoot }
        Invoke-Logged 'Add media-autobuild_suite origin' { git -C $suiteRoot remote add origin https://github.com/m-ab-s/media-autobuild_suite.git }
        Invoke-Logged 'Fetch pinned media-autobuild_suite commit' { git -C $suiteRoot fetch --depth 1 origin $mabsCommit }
        Invoke-Logged 'Check out pinned media-autobuild_suite commit' { git -C $suiteRoot checkout --detach $mabsCommit }
        $checkedOutMabs = (& git -C $suiteRoot rev-parse HEAD 2>&1 | Select-Object -First 1).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0 -or $checkedOutMabs -ne $mabsCommit) {
            throw "Pinned media-autobuild_suite identity check failed: expected $mabsCommit, got $checkedOutMabs."
        }
        Copy-Item (Join-Path $repoRoot '.github\ffmpeg-build\README.txt') $diagRoot -Force
    }

    Patch-MabsLibvpxIncludePath
    Patch-MabsCleanup

    $versionsPath = Join-Path $metaRoot 'resolved-versions.txt'
    if ($Variant -eq 'stable') {
        $stableTag = Resolve-LatestStableTag
        $stableCommit = Resolve-RemoteTagCommit $stableTag
        Set-Content -Path $versionsPath -Value "stable_tag=$stableTag`nstable_commit=$stableCommit`nmaster=not built" -Encoding UTF8
        $result = Run-Mabs -Label 'stable' -FfmpegPath "https://github.com/FFmpeg/FFmpeg.git#tag=$stableTag" -ExpectedStableTag $stableTag -ExpectedStableCommit $stableCommit
    } else {
        $masterAtStart = Resolve-RemoteCommit 'refs/heads/master'
        $result = Run-Mabs -Label 'master' -FfmpegPath "https://github.com/FFmpeg/FFmpeg.git#commit=$masterAtStart" -ExpectedMasterCommit $masterAtStart
    }

    $folder = $result.Folder
    $sourceCommit = $result.SourceCommit
    if ($Variant -eq 'master') {
        $stableLines = if (Test-Path -LiteralPath $versionsPath) {
            @(Get-Content -LiteralPath $versionsPath | Where-Object { $_ -match '^stable_(tag|commit)=' })
        } else {
            @('stable_tag=not recorded','stable_commit=not recorded')
        }
        Set-Content -Path $versionsPath -Value @($stableLines + @("master_commit=$sourceCommit", "master_at_start=$masterAtStart")) -Encoding UTF8
    }

    Assert-Features -Folder $folder -Label $Variant -SourceCommit $sourceCommit -StableTag $(if ($Variant -eq 'stable') { $stableTag } else { '' })
    Assert-CpuSmokeTest -Folder $folder -Label $Variant
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
