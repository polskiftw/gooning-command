@echo off
setlocal
cd /d "%~dp0"
title GParty Native Hamming Benchmark

echo.
echo ============================================================
echo   GParty Native Hamming Benchmark
echo ============================================================
echo.
echo This tool ONLY READS your deduper database.
echo It does not modify the database, R2, pairs, or deletion queues.
echo.

set "DB=%~1"
if not defined DB (
  echo Drag your deduper .db file onto RUN-BENCHMARK.bat
  echo or paste its full path below.
  echo.
  set /p "DB=Database path: "
)

set "DB=%DB:"=%"
if not exist "%DB%" (
  echo.
  echo ERROR: Database not found:
  echo %DB%
  echo.
  pause
  exit /b 1
)

set "PACKED=%TEMP%\gparty-hamming-%RANDOM%-%RANDOM%.bin"

echo.
echo [1/2] Exporting hashes from the database...
export_hashes.exe "%DB%" "%PACKED%"
if errorlevel 1 goto :failed

echo.
echo [2/2] Running full native XOR/POPCNT benchmark...
echo.
hamming_benchmark.exe "%PACKED%" 18 48
set "RESULT=%ERRORLEVEL%"

del /q "%PACKED%" >nul 2>nul

echo.
if not "%RESULT%"=="0" goto :failed_after_cleanup

echo Benchmark complete. Please send Rin the entire Results section above.
echo.
pause
exit /b 0

:failed
del /q "%PACKED%" >nul 2>nul
:failed_after_cleanup
echo.
echo Benchmark failed. Please send Rin everything shown in this window.
echo.
pause
exit /b 1
