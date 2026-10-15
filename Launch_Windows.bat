@echo off
rem Double-click launcher for Windows. Starts the app without a console window.
rem (The desktop shortcut the app adds does the same.) Errors are written to
rem logs\masterflex_pump.log in the data folder.
cd /d "%~dp0"
set "PY=python"
set "PYW=pythonw"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
rem Check the packages first, so a missing one is shown here instead of failing silently.
"%PY%" -c "import PyQt6, pycomm3, qdarktheme" 2>nul
if errorlevel 1 (
  echo Some packages are missing, or Python isn't installed.
  echo Double-click Setup_Windows.bat to install what the app needs, then try again.
  echo.
  pause
  exit /b 1
)
start "" "%PYW%" pump_gui.py
