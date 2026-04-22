@echo off
echo ========================================
echo  Testing Java Backend
echo ========================================
cd /d "%~dp0..\stock-backend"

echo.
echo Checking Java version...
java -version

echo.
echo Checking for JAR file...
dir target\*.jar

echo.
echo Trying to start Java backend (will exit after 10 seconds)...
start "Java Test" cmd /c "echo Starting Java... && java -jar target\stock-backend-0.0.1-SNAPSHOT.jar --spring.profiles.active=dev 2>&1 || echo ERROR: Java failed to start"

echo.
echo Waiting 10 seconds...
timeout /t 10 /nobreak

echo.
echo Done. Check the "Java Test" window for output.
pause
