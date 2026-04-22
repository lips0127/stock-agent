@echo off
echo ========================================
echo  Stock Agent System - Starting All Modules
echo ========================================
echo.

cd /d "%~dp0"

echo ==============================
echo  Configuration
echo ==============================
echo Java Port: 8080
echo Python Port: 5000
echo Frontend Dev Port: 10086 (H5)
echo.

set START_JAVA=true
set START_PYTHON=true
set START_FRONTEND=true

:parse_args
if "%~1"=="" goto check_prerequisites
if /i "%~1"=="--no-java" (
    set START_JAVA=false
    shift
    goto parse_args
)
if /i "%~1"=="--no-python" (
    set START_PYTHON=false
    shift
    goto parse_args
)
if /i "%~1"=="--no-frontend" (
    set START_FRONTEND=false
    shift
    goto parse_args
)
shift
goto parse_args

:check_prerequisites
echo ==============================
echo  Checking Prerequisites
echo ==============================

if "%START_JAVA%"=="true" (
    where java >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Error: Java not found. Please install Java 17+
        exit /b 1
    )
    echo Java: OK
)

if "%START_PYTHON%"=="true" (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Error: Python not found. Please install Python 3.8+
        exit /b 1
    )
    echo Python: OK
)

if "%START_FRONTEND%"=="true" (
    where pnpm >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Error: pnpm not found. Please install pnpm
        exit /b 1
    )
    echo pnpm: OK
)
echo.

:start_java
if "%START_JAVA%"=="true" (
    echo ==============================
    echo  Starting Java Backend (Port 8080)
    echo ==============================
    cd /d "%~dp0..\stock-backend"

    set JAR_FILE=
    for %%f in (target\*.jar) do (
        set JAR_FILE=%%f
        goto :jar_found
    )

    :jar_found
    if not defined JAR_FILE (
        echo.
        echo Warning: JAR file not found in target directory. Building...
        call "%~dp0..\build\build_java.bat"
        if %ERRORLEVEL% NEQ 0 (
            echo Error: Java build failed
            exit /b 1
        )
        for %%f in (target\*.jar) do (
            set JAR_FILE=%%f
        )
    )

    echo.
    echo Starting Java backend from %JAR_FILE%
    start "Java Backend" cmd /k "java -jar %JAR_FILE% --spring.profiles.active=dev"
)

:start_python
if "%START_PYTHON%"=="true" (
    echo ==============================
    echo  Starting Python Backend (Port 5000)
    echo ==============================
    cd /d "%~dp0..\backend"

    if exist "..\venv_new\Scripts\activate.bat" (
        set VENV_PATH=..\venv_new
    ) else if exist "..\venv\Scripts\activate.bat" (
        set VENV_PATH=..\venv
    ) else (
        echo.
        echo Warning: Virtual environment not found. Setting up...
        call "%~dp0..\build\build_python.bat"
        set VENV_PATH=..\venv
    )

    echo.
    echo Starting Python backend using %VENV_PATH%
    start "Python Backend" cmd /k "cd /d "%~dp0..\backend" && call "%VENV_PATH%\Scripts\activate.bat" && python -m backend.api.app"
)

:start_frontend
if "%START_FRONTEND%"=="true" (
    echo ==============================
    echo  Starting Frontend Dev Server (H5, Port 10086)
    echo ==============================
    cd /d "%~dp0..\frontend"

    echo.
    echo Starting Taro H5 dev server...
    start "Frontend Dev" cmd /k "cd /d "%~dp0..\frontend" && call pnpm dev:h5"
)

:complete
echo.
echo ==============================
echo  All Modules Starting
echo ==============================
echo.
echo Modules started in separate windows:
if "%START_JAVA%"=="true" (
    echo - Java Backend (Port 8080)
)
if "%START_PYTHON%"=="true" (
    echo - Python Backend (Port 5000)
)
if "%START_FRONTEND%"=="true" (
    echo - Frontend Dev Server (H5, Port 10086)
)
echo.
echo Access URLs:
if "%START_FRONTEND%"=="true" (
    echo - Frontend H5: http://localhost:10086
)
if "%START_JAVA%"=="true" (
    echo - Java API: http://localhost:8080
    echo - Swagger UI: http://localhost:8080/swagger-ui.html
)
if "%START_PYTHON%"=="true" (
    echo - Python API: http://localhost:5000
)
echo.
echo To stop all modules:
echo 1. Close the individual console windows
echo 2. Or press Ctrl+C in each window
echo.
echo ========================================
echo  System Startup Complete!
echo ========================================
