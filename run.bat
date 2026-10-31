@echo off
setlocal
title Nexora - Local Development Server

echo ========================================================
echo   Nexora - Document Intelligence
echo ========================================================
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not switch to the project directory.
    pause
    exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher "py" was not found.
    echo Install Python 3.10 or newer and enable the Python Launcher.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment found.
)

echo [2/3] Installing / checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check requirements.txt and your internet connection.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting Nexora...
echo Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

if errorlevel 1 (
    echo.
    echo [ERROR] Nexora stopped with an error.
    pause
)
endlocal
