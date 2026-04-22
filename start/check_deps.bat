@echo off
echo ========================================
echo  Stock Agent System - Dependency Check
echo ========================================
echo.

setlocal enabledelayedexpansion

echo ==============================
echo  System Prerequisites
echo ==============================

echo.
echo Checking Java...
where java >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=3" %%g in ('java -version 2^>^&1 ^| findstr /i "version"') do (
        set "JAVA_VER=%%g"
        set "JAVA_VER=!JAVA_VER:"=!"
        set "JAVA_VER=!JAVA_VER:~0,3!"
    )
    echo Java: OK (!JAVA_VER!)
) else (
    echo Java: NOT FOUND
)

echo.
echo Checking Maven...
where mvn >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('mvn -version 2^>^&1 ^| findstr /i "Apache Maven"') do (
        echo Maven: OK (%%g)
    )
) else (
    echo Maven: NOT FOUND
)

echo.
echo Checking Python...
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('python --version') do (
        echo Python: OK (%%g)
    )
) else (
    echo Python: NOT FOUND
)

echo.
echo Checking Node.js...
where node >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('node --version') do (
        echo Node.js: OK (%%g)
    )
) else (
    echo Node.js: NOT FOUND
)

echo.
echo Checking pnpm...
where pnpm >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('pnpm --version') do (
        echo pnpm: OK (%%g)
    )
) else (
    echo pnpm: NOT FOUND
)

echo.
echo ==============================
echo  Project Structure
echo ==============================

cd /d "%~dp0.."

if exist "stock-backend\pom.xml" (
    echo stock-backend/: OK (pom.xml found)
) else (
    echo stock-backend/: MISSING
)

if exist "stock-backend\target\*.jar" (
    for %%f in (stock-backend\target\*.jar) do (
        echo Java JAR: OK (%%~nxf)
        set JAR_FOUND=true
    )
    if not defined JAR_FOUND (
        echo Java JAR: MISSING
    )
) else (
    echo Java JAR: MISSING
)

if exist "backend\api\app.py" (
    echo Python backend: OK (app.py found)
) else (
    echo Python backend: MISSING
)

if exist "venv_new\Scripts\activate.bat" (
    echo Python venv: OK (venv_new)
) else if exist "venv\Scripts\activate.bat" (
    echo Python venv: OK (venv)
) else (
    echo Python venv: MISSING
)

if exist "frontend\package.json" (
    echo Frontend: OK (package.json found)
) else (
    echo Frontend: MISSING
)

echo.
echo ==============================
echo  Quick System Check Done
echo ==============================

if defined JAR_FOUND (
    echo.
    echo SUCCESS: System is ready to start
) else (
    echo.
    echo WARNING: Java JAR not built. Run build_all.bat first
)
