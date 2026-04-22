@echo off
echo ========================================
echo  Testing Python Backend
echo ========================================
cd /d "%~dp0..\backend"

echo.
echo Checking Python version...
python --version

echo.
echo Activating virtual environment...
cd /d "%~dp0.."
if exist "venv_new\Scripts\activate.bat" (
    echo Using venv_new...
    call venv_new\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo Using venv...
    call venv\Scripts\activate.bat
) else (
    echo ERROR: No virtual environment found!
    exit /b 1
)

echo.
echo Checking pip list...
pip list | findstr flask
pip list | findstr akshare

echo.
echo Checking if app module exists...
dir backend\api\app.py

echo.
echo Starting Python backend (will run in this window)...
echo.
echo ========================================
echo  Python Backend Output
echo ========================================
python -m backend.api.app
