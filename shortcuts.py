"""Put an icon on the desktop that starts the app, the native way for each system.

- macOS: a small app bundle, "Masterflex Pump.app", with the pump icon. Double-click it, or
  drag it into the Dock or Applications.
- Windows: a "Masterflex Pump" shortcut (.lnk) with the pump icon, made with PowerShell.
- Linux: a .desktop launcher, in the applications menu and on the desktop if there is one.

The icon starts the app the same way as the launchers: with the project's .venv if there
is one, without a console window. In a built app it starts the app itself.
No Qt here, so it can be tested on its own.
"""

import os
import plistlib
import subprocess
import sys

NAME = "Masterflex Pump"
BUNDLE_ID = "io.github.brandonbtm29.masterflex-reglo"


def button_label(platform=sys.platform):
    return {
        "darwin": "Add App Icon to Desktop",
        "win32": "Add Shortcut to Desktop",
    }.get(platform, "Add to Applications Menu")


def _frozen():
    return getattr(sys, "frozen", False)


def _python(root, windowed, platform):
    """The Python that should run the app: the project's .venv first, else this one."""
    if platform == "win32":
        name = "pythonw.exe" if windowed else "python.exe"
        venv = os.path.join(root, ".venv", "Scripts", name)
        if os.path.exists(venv):
            return venv
        alt = os.path.join(os.path.dirname(sys.executable), name)
        return alt if os.path.exists(alt) else sys.executable
    venv = os.path.join(root, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def _desktop(home):
    return os.path.join(home, "Desktop")


def create(root, assets, *, platform=sys.platform, home=None, run=subprocess.run):
    """Create the desktop icon. Returns its path. Raises OSError/RuntimeError with a message."""
    home = home or os.path.expanduser("~")
    if platform == "darwin":
        return _mac_app(root, assets, home)
    if platform == "win32":
        return _windows_shortcut(root, assets, run)
    return _linux_desktop_file(root, assets, home)


def _mac_app(root, assets, home):
    app = os.path.join(_desktop(home), f"{NAME}.app")
    macos = os.path.join(app, "Contents", "MacOS")
    resources = os.path.join(app, "Contents", "Resources")
    os.makedirs(macos, exist_ok=True)
    os.makedirs(resources, exist_ok=True)

    if _frozen():
        command = f'exec "{sys.executable}"'
    else:
        python = _python(root, windowed=True, platform="darwin")
        command = f'cd "{root}"\nexec "{python}" "{os.path.join(root, "pump_gui.py")}"'
    launcher = os.path.join(macos, "launcher")
    with open(launcher, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"#!/bin/bash\n# Starts {NAME} from {root}\n{command}\n")
    os.chmod(launcher, 0o755)

    with open(os.path.join(assets, "pump.icns"), "rb") as src:
        icon = src.read()
    with open(os.path.join(resources, "pump.icns"), "wb") as dst:
        dst.write(icon)

    info = {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "launcher",
        "CFBundleIconFile": "pump.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    os.utime(app)  # nudge Finder to pick up the icon
    return app


def _ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def windows_script(root, assets):
    """The PowerShell that makes the shortcut (separate so it can be tested anywhere)."""
    if _frozen():  # the .exe carries its own icon; the bundled files live in a temp folder
        target, arguments, icon = sys.executable, "", sys.executable
    else:
        target = _python(root, windowed=True, platform="win32")
        arguments = f'"{os.path.join(root, "pump_gui.py")}"'
        icon = os.path.join(assets, "pump.ico")
    lines = [
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$path = Join-Path $desktop {_ps_quote(NAME + '.lnk')}",
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)",
        f"$s.TargetPath = {_ps_quote(target)}",
        f"$s.Arguments = {_ps_quote(arguments)}",
        f"$s.WorkingDirectory = {_ps_quote(root)}",
        f"$s.IconLocation = {_ps_quote(icon + ',0')}",
        f"$s.Description = {_ps_quote('Control the Masterflex REGLO pump')}",
        "$s.Save()",
        "Write-Output $path",
    ]
    return "; ".join(lines)


def _windows_shortcut(root, assets, run):
    result = run(  # noqa: S603 - fixed program and script
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", windows_script(root, assets)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0:
        raise RuntimeError("Windows couldn't create the shortcut: " + (result.stderr or "").strip()[:300])
    return (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else NAME + ".lnk"


def _linux_desktop_file(root, assets, home):
    if _frozen():
        exec_line = f'"{sys.executable}"'
    else:
        exec_line = f'"{_python(root, True, "linux")}" "{os.path.join(root, "pump_gui.py")}"'
    text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Control the Masterflex REGLO pump\n"
        f"Exec={exec_line}\n"
        f"Path={root}\n"
        f"Icon={os.path.join(assets, 'pump.png')}\n"
        "Terminal=false\n"
        "Categories=Science;Utility;\n"
    )
    apps = os.path.join(home, ".local", "share", "applications")
    os.makedirs(apps, exist_ok=True)
    made = os.path.join(apps, "masterflex-reglo.desktop")
    targets = [made]
    if os.path.isdir(_desktop(home)):
        targets.append(os.path.join(_desktop(home), "masterflex-reglo.desktop"))
    for path in targets:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o755)
    return targets[-1]
