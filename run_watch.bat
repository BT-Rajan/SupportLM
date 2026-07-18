@echo off
REM Place at: C:\xampp\htdocs\SupportLM\run_watch.bat
REM Run by double-clicking, or: run_watch.bat

cd /d C:\xampp\htdocs\SupportLM

REM --- activate venv ---
if not exist ".venv\Scripts\activate.bat" (
    echo .venv not found - run 1_setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

REM --- start the app in its own window, logging to app.log ---
start "SupportLM App" cmd /k uvicorn app.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1

REM --- give it a couple seconds to boot ---
timeout /t 3 /nobreak >nul

REM --- start the watcher in its own window ---
start "SupportLM Watcher" cmd /k python watch_lifecycle.py app.log

echo Both windows launched. Use the chat widget in your browser now.
