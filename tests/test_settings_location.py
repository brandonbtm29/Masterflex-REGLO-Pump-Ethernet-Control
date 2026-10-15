"""settings_location.py: where the settings files live."""

import json
import os

import settings_location as sl


def test_default_is_the_app_folder(tmp_path, monkeypatch):
    monkeypatch.delenv(sl.ENV_VAR, raising=False)
    app, data = tmp_path / "app", tmp_path / "data"
    app.mkdir()
    assert sl.resolve(str(app), str(data)) == str(app)


def test_pointer_relative_to_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv(sl.ENV_VAR, raising=False)
    app, data = tmp_path / "app", tmp_path / "data"
    app.mkdir()
    (app / sl.POINTER).write_text(json.dumps({"settings_dir": "Settings"}), encoding="utf-8")
    resolved = sl.resolve(str(app), str(data))
    assert resolved == os.path.normpath(str(data / "Settings"))
    assert os.path.isdir(resolved)


def test_env_var_overrides_pointer(tmp_path, monkeypatch):
    app, data, other = tmp_path / "app", tmp_path / "data", tmp_path / "elsewhere"
    app.mkdir()
    (app / sl.POINTER).write_text(json.dumps({"settings_dir": "Settings"}), encoding="utf-8")
    monkeypatch.setenv(sl.ENV_VAR, str(other))
    assert sl.resolve(str(app), str(data)) == os.path.normpath(str(other))


def test_portable_paths(tmp_path):
    data = tmp_path / "data"
    assert sl.portable(str(data / "Settings"), str(data)) == "Settings"
    home_path = os.path.join(os.path.expanduser("~"), "SomeFolder")
    assert sl.portable(home_path, str(data)) == "~/SomeFolder"


def test_change_copies_missing_files_and_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.delenv(sl.ENV_VAR, raising=False)
    app, data = tmp_path / "app", tmp_path / "data"
    app.mkdir()
    (app / "a.json").write_text("from app", encoding="utf-8")
    (app / "b.json").write_text("from app", encoding="utf-8")
    target = data / "Settings"
    target.mkdir(parents=True)
    (target / "b.json").write_text("synced", encoding="utf-8")

    new_dir, copied, kept = sl.change(str(app), str(data), str(target), ["a.json", "b.json"])

    assert new_dir == os.path.normpath(str(target))
    assert copied == ["a.json"] and kept == ["b.json"]
    assert (target / "b.json").read_text(encoding="utf-8") == "synced"
    assert json.loads((app / sl.POINTER).read_text(encoding="utf-8")) == {"settings_dir": "Settings"}
