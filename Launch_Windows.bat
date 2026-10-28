@echo off
rem Double-click launcher for Windows. The first time, it sets the app up: it creates this
rem folder's own Python environment (.venv) and installs what the app needs, the same way
rem Setup_Windows.bat does. Then it starts the app without a console window. (The desktop
rem shortcut the app adds does the same.) Errors are written to logs\masterflex_pump.log in
rem the data folder.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto firstrun

:launch
set "PY=python"
set "PYW=pythonw"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
rem Check the packages first, so a missing one is shown here instead of failing silently.
"%PY%" -c "import PyQt6, pycomm3, qdarktheme" 2>nul
if errorlevel 1 (
  echo Some packages are missing, or Python isn't installed.
  echo.
  "%PY%" -c "import PyQt6, pycomm3, qdarktheme"
  echo.
  echo Double-click Setup_Windows.bat to install what the app needs, then try again.
  echo.
  pause
  exit /b 1
)
start "" "%PYW%" pump_gui.py
exit /b 0

rem First run: the same steps as Setup_Windows.bat, then start the app.
:firstrun
echo Setting up Masterflex Pump Control for the first time. This takes a minute or two.
echo It creates this folder's own Python environment (.venv) and installs what the app needs.
echo.
echo Creating .venv ...
py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython
set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import sys; sys.exit(sys.version_info < (3, 11))" || goto oldpython
"%PY%" -m pip install --upgrade pip || goto setupfailed
"%PY%" -m pip install -r requirements.txt || goto setupfailed
echo.
echo Setup finished. Starting Masterflex Pump Control...
goto launch

:nopython
echo.
echo Python 3.11 or newer isn't installed, or isn't on PATH.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then double-click Launch_Windows.bat again.
pause
exit /b 1

:oldpython
rem The .venv was only just made, so remove it: the next try then starts from scratch.
rmdir /s /q .venv
echo.
echo The newest Python on this computer is older than 3.11. Install a newer Python from
echo https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then double-click Launch_Windows.bat again.
pause
exit /b 1

:setupfailed
echo.
echo Setup didn't finish. Copy the messages above when asking for help.
echo Check the internet connection, then double-click Setup_Windows.bat to try again.
pause
exit /b 1
