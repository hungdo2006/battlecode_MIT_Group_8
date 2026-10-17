@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0scripts\start_local_qa.ps1" (
  echo ERROR: scripts\start_local_qa.ps1 is missing. Keep the repository files together.
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local_qa.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [NEON ARENA] Startup failed with exit code %RC%.
echo.
echo Press any key to close this window. Docker will keep running.
pause >nul
exit /b %RC%
