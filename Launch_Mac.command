#!/bin/bash
# Double-click launcher for macOS. Starts the app in the background and closes this Terminal
# window. (The "Masterflex Pump" icon the app adds to your Desktop opens no Terminal at all.)
# Errors are written to logs/masterflex_pump.log in the data folder.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi

# Check the packages first, so a missing one is shown here instead of failing silently.
if ! "$PY" -c "import PyQt6, pycomm3, qdarktheme" 2>/dev/null; then
  echo "Some packages are missing, or Python isn't installed."
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
