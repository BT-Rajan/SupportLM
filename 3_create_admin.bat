@echo off
REM ============================================================
REM SupportLM - create your first tenant + admin login (Windows)
REM Run this once after 2_init_database.bat.
REM ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo .venv not found - run 1_setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo This creates a tenant (your organization) and its first admin login.
echo.
set /p TENANT_NAME="Tenant display name (e.g. Acme Corp): "
set /p TENANT_SLUG="Tenant URL slug, lowercase-hyphenated (e.g. acme-corp): "
set /p ADMIN_EMAIL="Admin email: "
set /p ADMIN_PASSWORD="Admin password: "

python scripts\create_tenant.py "%TENANT_NAME%" "%TENANT_SLUG%" --owner-email "%ADMIN_EMAIL%" --owner-password "%ADMIN_PASSWORD%"

echo.
echo ============================================================
echo If you saw "Tenant created" above, you're ready to run the app.
echo Next: run 4_start_server.bat, then visit:
echo   Chat:  http://localhost:8000/t/%TENANT_SLUG%/
echo   Admin: http://localhost:8000/t/%TENANT_SLUG%/admin
echo ============================================================
pause
