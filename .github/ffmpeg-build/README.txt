CUSTOM WINDOWS FFMPEG BUILD
===========================

Run the workflow named "Build Custom FFmpeg 6" manually from GitHub Actions.

SUCCESS
-------
The stable build is uploaded immediately after it passes:
  ffmpeg-stable-windows-x64-<run id>

If master also passes, download:
  ffmpeg-custom-windows-x64-<run id>

GitHub supplies the artifact as a ZIP. There is no second ZIP inside it.
Opening the completed artifact once shows:
  stable\   latest stable FFmpeg release available when the workflow ran
  master\   current FFmpeg master commit available when the workflow ran

Each folder contains:
  ffmpeg.exe
  ffprobe.exe
  ffplay.exe
  build-info.txt
  feature reports
  SHA256SUMS.txt
  verify-nvidia.cmd

Copy ffmpeg.exe and ffprobe.exe beside yt-dlp.exe or another program that needs them.
No PATH changes or installer are used.

FAILURE
-------
Download the artifact named:
  ffmpeg-build-diagnostics-<run id>

GitHub supplies one ZIP whose files are immediately visible when opened. It contains
the build transcripts, failed stage, environment information, exact source commits,
configuration files, patches, MABS logs, and relevant dependency logs. There is no
inner diagnostics ZIP.

If stable passed before master failed or reached GitHub's time limit, the completed
stable artifact remains downloadable.

BUILD POLICY
------------
* Windows x64, MinGW-w64 GCC, UCRT.
* Fresh sources and clean compilation every run. No cache.
* One compiler thread for the entire build.
* Stable is built and uploaded before master begins.
* Latest stable and current master.
* Static-only selected runtime dependencies; no bundled codec DLLs.
* Aggressive i7-14700KF tuning: -O3 and Raptor Lake target.
* RTX 4070 Super paths: NVENC, NVDEC, CUDA headers, D3D11VA, D3D12VA,
  Vulkan and libplacebo. Intel QSV and AMD AMF are excluded.
* Normal local media, yt-dlp interoperability, subtitles, consumer codecs,
  image formats, analysis filters, and disc reading are included.
* OCR, AI runtimes, live capture, professional hardware, enterprise streaming,
  broad network transports, AviSynth, VapourSynth, frei0r and OpenCL are excluded.
* The build fails rather than silently dropping a required feature or replacing a
  selected source dependency with an unexplained prebuilt runtime library.

MAINTENANCE RULE
----------------
Every committed change to this custom FFmpeg build must increment the visible
"Build Custom FFmpeg N" workflow number and update this README to match. This keeps
new runs visually distinct from runs made with older build code.

IMPORTANT LIMITS
----------------
GitHub-hosted jobs have a hard six-hour execution limit.

NVIDIA driver DLLs and normal Windows system DLLs remain runtime requirements.
They are supplied by Windows and the installed NVIDIA driver, not bundled beside
FFmpeg.

Blu-ray AACS/BD+ keys or configuration data are not included. FFmpeg/libbluray
support does not itself supply disc keys.

The GitHub runner has no RTX 4070 Super, so presence is checked in CI and actual
NVENC execution is checked by verify-nvidia.cmd on the target computer.
