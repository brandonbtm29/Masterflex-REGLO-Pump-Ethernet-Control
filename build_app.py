"""Build a standalone app with PyInstaller.

    pip install -e ".[build]"      (or: pip install -r requirements.txt)
    python build_app.py

Windows: dist/MasterFlex_Pump_GUI.exe (one file). macOS: dist/MasterFlex_Pump_GUI.app.
Linux: dist/MasterFlex_Pump_GUI/ (a folder with the program inside).
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "MasterFlex_Pump_GUI"


def build():
    if not _has_module("PyInstaller"):
        sys.exit('PyInstaller isn\'t installed. Run: pip install -e ".[build]"')

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",  # no console window; on macOS this makes a .app
        "--name",
        NAME,
        "--add-data",
        f"assets{sep}assets",  # window icon and shortcut icons
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "PyQt5",
    ]
    if sys.platform == "darwin":
        # A .app bundle; PyInstaller recommends folder mode (--onedir) for these.
        cmd += ["--onedir", "--icon", os.path.join("assets", "pump.icns")]
    elif sys.platform == "win32":
        cmd += ["--onefile", "--icon", os.path.join("assets", "pump.ico")]
    else:
        cmd += ["--onedir"]
    cmd.append("pump_gui.py")

    print("Running:", " ".join(cmd))
    try:
        subprocess.check_call(cmd, cwd=HERE)
    except subprocess.CalledProcessError as e:
        sys.exit(f"Build failed: {e}")

    target = {"darwin": f"{NAME}.app", "win32": f"{NAME}.exe"}.get(sys.platform, NAME)
    print(f"\nBuild complete: dist/{target}")
    if sys.platform == "darwin":
        print("Drag it into Applications, or use Settings > App > Add App Icon to Desktop.")
    elif sys.platform == "win32":
        print("Use Settings > App > Add Shortcut to Desktop, or right-click it > Pin to Start.")


def _has_module(name):
    import importlib.util

    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    build()
