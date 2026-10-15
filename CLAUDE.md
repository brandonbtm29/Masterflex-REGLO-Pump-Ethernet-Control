# Masterflex REGLO Pump Controller

PyQt6 GUI that controls a Masterflex REGLO digital pump over EtherNet/IP using `pycomm3`. Part of the UAkron lab app family (shared conventions in `../CLAUDE.md` when the repos are cloned side by side). GitHub: `brandonbtm29/Masterflex-REGLO-Pump-Ethernet-Control`.

Machine-specific notes (clone paths, machine names) go in `CLAUDE.local.md`, which is gitignored. Never put personal paths, machine names or emails in this file: the repo is public.

## Run / build / check
- `python -m venv .venv`, then `pip install -e ".[dev]"` (or `pip install -r requirements.txt` to just run it)
- Run: `python pump_gui.py`, or the `Launch_Windows.bat` / `Launch_Mac.command` launchers (they use `.venv`). Build: `python build_app.py` → `dist/`
- Before committing: `ruff check . && ruff format --check . && pytest` (tests run headless with `QT_QPA_PLATFORM=offscreen`; no pump needed)
- Version lives only in `pump_gui.py` (`__version__`). Release steps are in README "Development"; update `CHANGELOG.md`.

## Read README.md "How it works" before changing comms code
- `PumpDriver` subclasses `pycomm3.LogixDriver` and overrides `_initialize_driver` with `pass`. The pump crashes if the normal identity/tag-list handshake runs.
- 100 ms watchdog: in Remote Control mode the full 28-byte output array must be re-sent about every 100 ms (`poll_pump_data` thread), or the motor stops.
- Use raw CIP assembly messaging (class 0x04, attribute 0x03): instance **100** = 56-byte input (read), instance **112** = 28-byte output (write). Tag writes are not supported. Byte maps are in the README.

## Code map (`pump_gui.py`, ~1,500 lines)
`SignalManager` (Qt signals), `SettingsDialog`, `MasterflexPumpGUI(QMainWindow)`. Comms: `_read_input` / `_send_output` / `_poll_once` (background thread) report failures through `_report_comm` → `link_state_signal`. `dispense.py` (no Qt) runs Time/Volume programs in software; the drive is always kept in continuous mode (byte 4 = 0) because it locks up when switched over EtherNet/IP. `settings_location.py` is shared (identical copy in every UAkron repo). Tests use `FakePump` from `tests/conftest.py`.

## Where code and data live
- **Code** (this repo) is cloned outside SyncThing and syncs through GitHub only.
- **Instrument data** stays in the SyncThing data folder, `~/SyncThing/UAkron Playground/MasterFlex Pump/` by default. Never copy data into the repo, and never commit the settings files listed below.
- **How it works:** at startup the app `chdir`s into its data folder (`DATA_DIR`, override with `UAKRON_APP_DATA_DIR` or `UAKRON_DATA_DIR`). Every relative data path therefore resolves inside SyncThing. Run logs are `Data/run_log.csv` and `Data/run_log_backup.csv` there (`RUN_LOG`, `RUN_LOG_BACKUP`). Files that ship with the code (the icon) must be loaded via `script_dir`, never by bare relative name.
- **Settings folder:** `pump_config.json` is read from `CONFIG_DIR`, resolved by `settings_location.py`. Default: this repo folder (gitignored), so a fresh clone starts from the app's defaults. The per-machine pointer `settings_location.json` (gitignored), set from the app's "Settings Folder" box, can move it; a relative path is relative to the data folder (e.g. `Settings`). `UAKRON_SETTINGS_DIR` overrides the pointer. `pump_config.example.json` documents the keys.
- Tests and `scripts/make_screenshot.py` point both env vars at a temp folder so they never touch real data or settings.

## Commits
One concern per commit. End every commit with a `Co-Authored-By:` trailer for the assistant that did the work. Use the GitHub noreply address as the author email (set per repo).
