@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" -c "import uvicorn" 2>nul || "%PY%" -m pip install -r requirements.txt

"%PY%" -m uvicorn lanq.main:app --host 0.0.0.0 --port 8000

pause
