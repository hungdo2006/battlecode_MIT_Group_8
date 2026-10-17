@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0scripts\start_local_qa.ps1" (
  echo ERROR: scripts\start_local_qa.ps1 is missing.
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local_qa.ps1" -Stop
set "RC=%ERRORLEVEL%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %RC%
