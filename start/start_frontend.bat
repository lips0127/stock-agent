@echo off
echo ========================================
echo  Starting Frontend Dev Server Only
echo ========================================
cd /d "%~dp0"
call start_all.bat --no-java --no-python
