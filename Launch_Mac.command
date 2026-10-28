#!/bin/bash
# Double-click launcher for macOS. The first time, it sets the app up: it creates this folder's
# own Python environment (.venv) and installs what the app needs, the same way Setup_Mac.command
# does. Then it starts the app in the background and closes this Terminal window. (The
# "Masterflex Pump" icon the app adds to your Desktop opens no Terminal at all.)
# Errors are written to logs/masterflex_pump.log in the data folder.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
fail() { echo; echo "$1"; read -r -p "Press Enter to close"; exit 1; }
new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }

# First run: the same steps as Setup_Mac.command, then start the app.
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Masterflex Pump Control for the first time. This takes a minute or two."
  echo "It creates this folder's own Python environment (.venv) and installs what the app needs."
  echo
  PYTHON=""
  for p in python3.12 python3.13 python3.11 python3; do
    if command -v "$p" >/dev/null && new_enough "$p"; then PYTHON="$p"; break; fi
  done
  [ -n "$PYTHON" ] || fail "Python 3.11 or newer isn't installed. Get it from https://www.python.org/downloads/ and double-click Launch_Mac.command again."
  echo "Creating .venv with $PYTHON ..."
  "$PYTHON" -m venv .venv || fail "Couldn't create the .venv folder."
  SETUP_FAILED="Setup didn't finish. Copy the messages above when asking for help. Check the internet connection, then double-click Setup_Mac.command to try again."
  .venv/bin/python -m pip install --upgrade pip || fail "$SETUP_FAILED"
  .venv/bin/python -m pip install -r requirements.txt || fail "$SETUP_FAILED"
  echo
  echo "Setup finished. Starting Masterflex Pump Control..."
fi

if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi

# Check the packages first, so a missing one is shown here instead of failing silently.
if ! "$PY" -c "import PyQt6, pycomm3, qdarktheme" 2>/dev/null; then
  echo "Some packages are missing, or Python isn't installed."
  echo
  "$PY" -c "import PyQt6, pycomm3, qdarktheme"
  echo
  echo "Double-click Setup_Mac.command to install what the app needs, then try again."
  read -r -p "Press Enter to close"
  exit 1
fi

REGLO_DETACH=1 nohup "$PY" pump_gui.py >/dev/null 2>&1 &
disown
# Close this window once the shell has exited. The helper leaves the Terminal session first
# (setsid) so Terminal doesn't see a running process and ask before closing. macOS may ask once
# whether Terminal may be controlled; if you say no, the window just stays open.
"$PY" -c '
import os, subprocess, time
os.setsid()
time.sleep(1)
subprocess.run(["osascript", "-e",
    "tell application \"Terminal\" to close (every window whose name contains \"Launch_Mac\")"])
' </dev/null >/dev/null 2>&1 &
disown
exit 0
