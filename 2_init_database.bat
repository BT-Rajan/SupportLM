@echo off
REM ============================================================
REM SupportLM - database setup (Windows)
REM Creates the MySQL database (if needed) and runs every migration
REM in migrations/. Make sure MySQL is running in XAMPP first.
REM ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo .venv not found - run 1_setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python scripts\init_db.py

echo.
echo ============================================================
echo If you saw "Done." above, the database is ready.
echo Next: run 3_create_admin.bat to create your first login.
echo ============================================================
pause
