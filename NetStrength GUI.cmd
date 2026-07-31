@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" "scripts\run_gui.py"
  exit /b
)

where pyw >nul 2>&1
if %errorlevel%==0 (
  pyw -3 "scripts\run_gui.py"
  exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
  pythonw "scripts\run_gui.py"
  exit /b
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 "scripts\run_gui.py"
  exit /b
)

python "scripts\run_gui.py"
