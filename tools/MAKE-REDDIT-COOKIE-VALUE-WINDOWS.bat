@echo off
setlocal
color 0A
title Gooning Party - Make Reddit Cookie Value

echo ============================================================
echo       GOONING PARTY - MAKE REDDIT COOKIE VALUE
echo ============================================================
echo.
echo This does NOT use Reddit's API.
echo It converts your exported reddit cookies.txt file into one
 echo long line that Railway can store safely.
echo.
echo FIRST: export Reddit cookies in Netscape cookies.txt format.
echo THEN: drag that cookies.txt file onto this BAT file.
echo.

if "%~1"=="" (
  echo No file was given to me.
  echo.
  echo Drag your cookies.txt file directly onto this BAT file.
  echo Do not double-click the BAT by itself.
  echo.
  pause
  exit /b 1
)

if not exist "%~1" (
  echo I cannot find this file:
  echo %~1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[Convert]::ToBase64String([IO.File]::ReadAllBytes('%~f1')); Set-Clipboard $b; [IO.File]::WriteAllText('%~dp0REDDIT-COOKIE-VALUE.txt',$b,[Text.UTF8Encoding]::new($false))"
if errorlevel 1 (
  echo.
  echo Something failed. Nothing was changed online.
  pause
  exit /b 1
)

echo.
echo DONE.
echo.
echo The long cookie value is now:
echo   1. copied to your Windows clipboard
 echo   2. saved beside this BAT as REDDIT-COOKIE-VALUE.txt
echo.
echo In Railway, make this variable:
echo   REDDIT_COOKIES_BASE64
echo.
echo Paste the entire long line as its value.
echo Never paste that value into chat or GitHub.
echo.
pause
