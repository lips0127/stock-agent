@echo off
cd /d "C:\Users\weizhou\Desktop\stock_agent\stock-backend"

echo [INFO] Starting Maven build...
echo [INFO] Output will be in mvn_build.log
mvn clean compile -DskipTests > mvn_build.log 2>&1

if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Build completed
    echo [INFO] Build log: mvn_build.log
    dir target
) else (
    echo [ERROR] Build failed!
    echo [INFO] Build log: mvn_build.log
    type mvn_build.log
)
