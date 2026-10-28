@echo off
rem Repair or reinstall Masterflex Pump Control. You don't need this to start the app the first
rem time: Launch_Windows.bat sets itself up. Run this if the app stops starting (for example after
rem a Python upgrade): it creates this folder's own Python environment (.venv) if it's missing and
rem installs everything the app needs again.
cd /d "%~dp0"
echo Setting up Masterflex Pump Control in %CD%
echo.
if exist ".venv\Scripts\python.exe" (
  echo Using the existing .venv folder.
) else (
  echo Creating .venv ...
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" goto nopython
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import sys; sys.exit(sys.version_info < (3, 11))" || goto oldpython
"%PY%" -m pip install --upgrade pip || goto failed
"%PY%" -m pip install -r requirements.txt || goto failed

echo.
echo Checking that the app can start...
"%PY%" -c "import PyQt6.QtWidgets, qdarktheme, pycomm3" || goto failed
echo.
echo Done. Start Masterflex Pump Control with Launch_Windows.bat.
pause
exit /b 0

:nopython
echo.
echo Python 3.11 or newer isn't installed, or isn't on PATH.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1

:oldpython
echo.
echo The .venv folder uses a Python older than 3.11. Delete the .venv folder, install a newer
echo Python from https://www.python.org/downloads/, then run this again.
pause
exit /b 1

:failed
echo.
echo Setup didn't finish. Copy the messages above when asking for help.
pause
exit /b 1
