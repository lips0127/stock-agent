@echo off
echo ========================================
echo  Starting Python Backend Only
echo ========================================
cd /d "%~dp0"
call start_all.bat --no-java --no-frontend
