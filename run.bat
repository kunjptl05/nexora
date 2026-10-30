@echo off
echo ========================================================
echo   Starting Nexora (Document Intelligence Platform)
echo ========================================================
echo.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    echo Starting server with virtual environment Python...
    .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
) else (
    echo Starting server with global Python...
    py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
)
pause
