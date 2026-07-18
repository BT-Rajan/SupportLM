@echo off
REM ============================================================
REM SupportLM - one-time setup (Windows)
REM Creates a virtual environment and installs all dependencies.
REM Run this once before anything else.
REM ============================================================

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.11+ from
    echo https://www.python.org/downloads/windows/ and check
    echo "Add python.exe to PATH" during install, then re-run this script.
    pause
    exit /b 1
)

echo Creating virtual environment in .venv ...
python -m venv .venv

call .venv\Scripts\activate.bat

echo Upgrading pip ...
python -m pip install --upgrade pip

echo Installing dependencies (this can take a few minutes the first time
echo - sentence-transformers pulls in a sizeable ML stack) ...
pip install -r requirements.txt

echo.
echo ============================================================
echo Setup complete.
echo Next steps:
echo   1. Start MySQL from the XAMPP Control Panel.
echo   2. Edit .env if your MySQL root user has a password.
echo   3. Run 2_init_database.bat
echo ============================================================
pause
