@echo off
chcp 65001 >nul
echo Starting Stock Agent Python Backend...
cd /d "%~dp0\.."
python -m backend.api.app
