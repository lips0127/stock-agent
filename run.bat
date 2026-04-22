
@echo off
REM Activate the new clean Python venv
call venv_new\Scripts\activate.bat

REM Run the app
echo Starting Stock Agent with Clean Python Environment...
streamlit run app.py

pause
