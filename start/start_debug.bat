@echo off
echo ========================================
echo  Stock Agent - DEBUG Start
echo ========================================
echo.

cd /d "%~dp0"

echo Checking Java JAR...
cd /d "%~dp0..\stock-backend"

set JAR_FILE=
for %%f in (target\*.jar) do (
    if "!JAR_FILE!"=="" set JAR_FILE=%%f
)

if defined JAR_FILE (
    echo Found JAR: %JAR_FILE%
) else (
    echo JAR not found!
)

echo.
echo Checking Python venv...
cd /d "%~dp0.."
if exist "venv_new\Scripts\activate.bat" (
    echo Found venv_new
) else if exist "venv\Scripts\activate.bat" (
    echo Found venv
) else (
    echo No venv found!
)

echo.
echo Checking frontend...
cd /d "%~dp0..\frontend"
if exist "package.json" (
    echo Found package.json
) else (
    echo No package.json!
)

echo.
echo ========================================
echo  Configuration OK. Now testing individual modules...
echo ========================================
pause
