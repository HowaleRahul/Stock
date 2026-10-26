$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    Write-Host "[Signal Desk] Auto-detected virtual environment. Launching with .venv python..." -ForegroundColor Green
    & "$ScriptDir\.venv\Scripts\python.exe" start.py
} elseif (Test-Path "$ScriptDir\venv\Scripts\python.exe") {
    Write-Host "[Signal Desk] Auto-detected virtual environment. Launching with venv python..." -ForegroundColor Green
    & "$ScriptDir\venv\Scripts\python.exe" start.py
} else {
    Write-Host "[Signal Desk] Launching with system python..." -ForegroundColor Yellow
    python start.py
}
