CUSTOM WINDOWS FFMPEG BUILD
===========================

Run the workflow named "Build Custom FFmpeg 18" manually from GitHub Actions.

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
  source-identity.txt
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
* media-autobuild_suite is pinned to the audited commit recorded in build.ps1;
  moving upstream code cannot silently change a four-hour build.
* One compiler thread for the entire build.
* Stable is built and uploaded before master begins.
* Latest stable and current master are resolved to exact immutable commits before
  each compilation.
* Stable FFmpeg release tags are resolved through Git, not the GitHub REST API.
* MABS output streams live and is also logged. A non-zero exit code is forgiven only
  when MABS printed its success marker and all three executables were freshly linked.
* The checked-in build script is the script that runs. No workflow-time scripts patch
  or reconstruct the validator.
* Static-only selected runtime dependencies; no bundled codec DLLs.
* Windows API-set contract imports are recognized as operating-system dependencies
  even when their virtual DLL names do not exist as files in System32.
* Aggressive i7-14700KF tuning: -O3 and Raptor Lake target.
* RTX 4070 Super paths: NVENC, NVDEC, CUDA headers, D3D11VA, D3D12VA,
  Vulkan and libplacebo. Intel QSV and AMD AMF are excluded.
* Normal local media, yt-dlp interoperability, subtitles, consumer codecs,
  image formats, analysis filters, and disc reading are included.
* OCR, AI runtimes, live capture, professional hardware, enterprise streaming,
  broad network transports, AviSynth, VapourSynth, frei0r and OpenCL are excluded.
* The build fails rather than silently dropping a required feature or replacing a
  selected source dependency with an unexplained prebuilt runtime library.
* Every executable must be PE32+ AMD64, pass dumpbin inspection, identify the intended
  FFmpeg source revision, and expose every explicitly requested configure option.

MAINTENANCE RULE
----------------
Every committed change to this custom FFmpeg build must increment both the visible
"name:" and "run-name:" values to "Build Custom FFmpeg N" and update this README
to match. The workflow must remain manual-only with only "workflow_dispatch" under
"on:". This keeps new runs visually distinct without triggering builds on commits.

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
