@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title NEON ARENA - Local Bot Battle

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 goto checkdeps
    echo Existing Python environment is invalid. Recreating it...
    rmdir /s /q ".venv"
)
echo Creating local Python environment...
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
) else (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python 3.11+ and enable "Add python.exe to PATH".
        echo See README.md for the Windows setup instructions.
        pause
        exit /b 1
    )
    python -m venv .venv
)
if errorlevel 1 goto failed

:checkdeps
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, multipart, websockets" >nul 2>&1
if not errorlevel 1 goto run
echo Installing project dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run
echo.
echo Open http://127.0.0.1:8000 in your browser.
echo Only run trusted bots. Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Could not start NEON ARENA. Read the error above and README.md.
pause
exit /b 1
