@echo off
echo ========================================
echo  Starting Java Backend Only
echo ========================================
cd /d "%~dp0"
call start_all.bat --no-python --no-frontend
