@echo off
REM ============================================================
REM SupportLM - start the server (Windows)
REM Leave this window open while you use the app. Ctrl+C to stop.
REM ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo .venv not found - run 1_setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Starting SupportLM on http://localhost:8000
echo (Make sure MySQL is running in the XAMPP Control Panel.)
echo Press Ctrl+C to stop the server.
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
