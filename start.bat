@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    echo [Signal Desk] Auto-detected virtual environment.
    ".venv\Scripts\python.exe" start.py
) else if exist "venv\Scripts\python.exe" (
    echo [Signal Desk] Auto-detected virtual environment.
    "venv\Scripts\python.exe" start.py
) else (
    echo [Signal Desk] Running with default Python...
    python start.py
)
pause
