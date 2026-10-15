"""shortcuts.py: the desktop icon for each operating system."""

import os
import plistlib
import subprocess

import shortcuts

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def test_labels():
    assert shortcuts.button_label("darwin") == "Add App Icon to Desktop"
    assert shortcuts.button_label("win32") == "Add Shortcut to Desktop"
    assert shortcuts.button_label("linux") == "Add to Applications Menu"


def test_mac_app_bundle(tmp_path):
    root = tmp_path / "My Repo"
    root.mkdir()
    app = shortcuts.create(str(root), ASSETS, platform="darwin", home=str(tmp_path))
    assert app == os.path.join(str(tmp_path), "Desktop", "Masterflex Pump.app")
    with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleExecutable"] == "launcher" and info["CFBundleIconFile"] == "pump.icns"
    assert os.path.getsize(os.path.join(app, "Contents", "Resources", "pump.icns")) > 1000
    launcher = os.path.join(app, "Contents", "MacOS", "launcher")
    text = open(launcher, encoding="utf-8").read()
    assert text.startswith("#!/bin/bash") and f'"{os.path.join(str(root), "pump_gui.py")}"' in text
    if os.name != "nt":
        assert os.access(launcher, os.X_OK)


def test_windows_shortcut_script_and_call(tmp_path):
    root = r"C:\Users\Someone\GitHub Projects\It's here"
    script = shortcuts.windows_script(root, ASSETS)
    assert "CreateShortcut" in script and "GetFolderPath('Desktop')" in script
    assert "It''s here" in script  # quotes escaped for PowerShell
    assert "pump.ico,0" in script

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="C:\\Desktop\\Masterflex Pump.lnk\n", stderr="")

    path = shortcuts.create(root, ASSETS, platform="win32", run=fake_run)
    assert path.endswith("Masterflex Pump.lnk")
    assert calls[0][0] == "powershell" and calls[0][-1] == script


def test_windows_failure_is_reported():
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Access denied")

    try:
        shortcuts.create("C:\\x", ASSETS, platform="win32", run=fake_run)
    except RuntimeError as e:
        assert "Access denied" in str(e)
    else:
        raise AssertionError("expected an error")


def test_linux_desktop_file(tmp_path):
    (tmp_path / "Desktop").mkdir()
    path = shortcuts.create(str(tmp_path / "repo"), ASSETS, platform="linux", home=str(tmp_path))
    text = open(path, encoding="utf-8").read()
    assert "Name=Masterflex Pump" in text and "pump.png" in text
    assert os.path.exists(tmp_path / ".local" / "share" / "applications" / "masterflex-reglo.desktop")
