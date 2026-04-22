@echo off
cd /d "%~dp0"
del check_deps_output.txt 2>nul

echo ======================================== >> check_deps_output.txt
echo  Stock Agent System - Dependency Check >> check_deps_output.txt
echo ======================================== >> check_deps_output.txt
echo. >> check_deps_output.txt

setlocal enabledelayedexpansion

echo ============================== >> check_deps_output.txt
echo  System Prerequisites >> check_deps_output.txt
echo ============================== >> check_deps_output.txt

echo. >> check_deps_output.txt
echo Checking Java... >> check_deps_output.txt
where java >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=3" %%g in ('java -version 2^>^&1 ^| findstr /i "version"') do (
        set "JAVA_VER=%%g"
        set "JAVA_VER=!JAVA_VER:"=!"
        set "JAVA_VER=!JAVA_VER:~0,3!"
    )
    echo Java: OK (!JAVA_VER!) >> check_deps_output.txt
) else (
    echo Java: NOT FOUND >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo Checking Maven... >> check_deps_output.txt
where mvn >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('mvn -version 2^>^&1 ^| findstr /i "Apache Maven"') do (
        echo Maven: OK (%%g) >> check_deps_output.txt
    )
) else (
    echo Maven: NOT FOUND >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo Checking Python... >> check_deps_output.txt
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('python --version') do (
        echo Python: OK (%%g) >> check_deps_output.txt
    )
) else (
    echo Python: NOT FOUND >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo Checking Node.js... >> check_deps_output.txt
where node >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('node --version') do (
        echo Node.js: OK (%%g) >> check_deps_output.txt
    )
) else (
    echo Node.js: NOT FOUND >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo Checking pnpm... >> check_deps_output.txt
where pnpm >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%g in ('pnpm --version') do (
        echo pnpm: OK (%%g) >> check_deps_output.txt
    )
) else (
    echo pnpm: NOT FOUND >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo ============================== >> check_deps_output.txt
echo  Project Structure >> check_deps_output.txt
echo ============================== >> check_deps_output.txt

cd /d "%~dp0.."

if exist "stock-backend\pom.xml" (
    echo stock-backend/: OK (pom.xml found) >> check_deps_output.txt
) else (
    echo stock-backend/: MISSING >> check_deps_output.txt
)

if exist "stock-backend\target\*.jar" (
    set JAR_FOUND=false
    for %%f in (stock-backend\target\*.jar) do (
        echo Java JAR: OK (%%~nxf) >> check_deps_output.txt
        set JAR_FOUND=true
    )
    if "!JAR_FOUND!"=="false" (
        echo Java JAR: MISSING >> check_deps_output.txt
    )
) else (
    echo Java JAR: MISSING >> check_deps_output.txt
)

if exist "backend\api\app.py" (
    echo Python backend: OK (app.py found) >> check_deps_output.txt
) else (
    echo Python backend: MISSING >> check_deps_output.txt
)

if exist "venv_new\Scripts\activate.bat" (
    echo Python venv: OK (venv_new) >> check_deps_output.txt
) else if exist "venv\Scripts\activate.bat" (
    echo Python venv: OK (venv) >> check_deps_output.txt
) else (
    echo Python venv: MISSING >> check_deps_output.txt
)

if exist "frontend\package.json" (
    echo Frontend: OK (package.json found) >> check_deps_output.txt
) else (
    echo Frontend: MISSING >> check_deps_output.txt
)

echo. >> check_deps_output.txt
echo ============================== >> check_deps_output.txt
echo  Quick System Check Done >> check_deps_output.txt
echo ============================== >> check_deps_output.txt

if "!JAR_FOUND!"=="true" (
    echo. >> check_deps_output.txt
    echo SUCCESS: System is ready to start >> check_deps_output.txt
) else (
    echo. >> check_deps_output.txt
    echo WARNING: Java JAR not built. Run build_all.bat first >> check_deps_output.txt
)

echo Check complete. Output saved to check_deps_output.txt
