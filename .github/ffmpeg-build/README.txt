CUSTOM WINDOWS FFMPEG BUILD
===========================

Run the workflow named "Build Custom FFmpeg" manually from GitHub Actions.

SUCCESS
-------
Download the single artifact named:
  ffmpeg-custom-windows-x64-<run id>

It contains one ZIP with:
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
Download the single artifact named:
  ffmpeg-build-diagnostics-<run id>

Attach ffmpeg-build-diagnostics.zip to ChatGPT. It contains the build transcript,
failed stage, environment information, source versions, configuration files,
patches, and relevant dependency logs. Partial binaries are not packaged.

BUILD POLICY
------------
* Windows x64, MinGW-w64 GCC, UCRT.
* Fresh sources and clean compilation every run. No cache.
* Latest stable and current master.
* Static-only selected runtime dependencies; no bundled codec DLLs.
* Aggressive i7-14700KF tuning: -O3, Raptor Lake target, LTO.
* RTX 4070 Super paths: NVENC, NVDEC, CUDA headers, D3D11VA, D3D12VA,
  Vulkan and libplacebo. Intel QSV and AMD AMF are excluded.
* Normal local media, yt-dlp interoperability, subtitles, consumer codecs,
  image formats, analysis filters, and disc reading are included.
* OCR, AI runtimes, live capture, professional hardware, enterprise streaming,
  broad network transports, AviSynth, VapourSynth, frei0r and OpenCL are excluded.
* The build fails rather than silently dropping a required feature or replacing a
  selected source dependency with an unexplained prebuilt runtime library.

IMPORTANT LIMITS
----------------
NVIDIA driver DLLs and normal Windows system DLLs remain runtime requirements.
They are supplied by Windows and the installed NVIDIA driver, not bundled beside
FFmpeg.

Blu-ray AACS/BD+ keys or configuration data are not included. FFmpeg/libbluray
support does not itself supply disc keys.

The GitHub runner has no RTX 4070 Super, so presence is checked in CI and actual
NVENC execution is checked by verify-nvidia.cmd on the target computer.
