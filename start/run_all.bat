@echo off
echo ========================================
echo  Stock Agent System - Starting via Python
echo ========================================
echo.

cd /d "%~dp0"

REM Try to use the existing venv
if exist "..\venv_new\Scripts\python.exe" (
    echo Using venv_new Python...
    "..\venv_new\Scripts\python.exe" start_all.py
) else if exist "..\venv\Scripts\python.exe" (
    echo Using venv Python...
    "..\venv\Scripts\python.exe" start_all.py
) else (
    echo Using system Python...
    python start_all.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo The script exited with an error.
    pause
)
