# Masterflex REGLO Pump Controller

PyQt6 GUI that controls a Masterflex REGLO digital pump over EtherNet/IP using `pycomm3`. Part of Brandon's UAkron lab workspace (shared conventions in `../CLAUDE.md` when the repos are cloned side by side in `GitHub Projects/UAkron/`). GitHub: `brandonbtm29/Masterflex-REGLO-Pump-Ethernet-Control`.

## Run / build
- `pip install -r requirements.txt` (PyQt6, pyqtdarktheme, pycomm3, pyinstaller)
- Run: `python pump_gui.py`. Build: `python build_app.py` → `dist/`
- Settings live in `pump_config.json`. Run logs are `run_log*.csv` (gitignored). The RTD dashboard reads these logs.

## Read README.md "Critical Project Learnings" before changing comms code
- `PumpDriver` subclasses `pycomm3.LogixDriver` and overrides `_initialize_driver` with `pass`. The pump crashes if the normal identity/tag-list handshake runs.
- 100 ms watchdog: in Remote Control mode the full 28-byte output array must be re-sent about every 100 ms (`poll_pump_data` thread), or the motor stops.
- Use raw CIP assembly messaging (class 0x04, attribute 0x03): instance **100** = 56-byte input (read), instance **112** = 28-byte output (write). Tag writes are not supported. Byte maps are in the README.

## Code map (`pump_gui.py`, ~1,500 lines)
`SignalManager` (Qt signals), `SettingsDialog`, `MasterflexPumpGUI(QMainWindow)`.

## Where code and data live
- **Code** (this repo) is cloned outside SyncThing: `C:\Users\Brand\GitHub Projects\UAkron\Masterflex-REGLO-Pump-Ethernet-Control` on Windows, `~/GitHub Projects/UAkron/Masterflex-REGLO-Pump-Ethernet-Control` on the Mac. It syncs through GitHub only.
- **Instrument data** stays in SyncThing: `C:\Users\Brand\SyncThing\UAkron Playground\MasterFlex Pump\` (Mac: `/Users/brandonmcreynolds/SyncThing/UAkron Playground/MasterFlex Pump/`). Never copy data, `config.json` or `secrets.json` into the repo.
- **How it works (since 10 Oct 2026):** at startup the app `chdir`s into its SyncThing data folder (`DATA_DIR`, override with `UAKRON_APP_DATA_DIR` or `UAKRON_DATA_DIR`). Every relative path (`Data/`, `Data Backups/`, `Sessions/`, run logs, local config such as `config.json` / `pump_config.json` / `jebao_config.json` / `secrets.json` / `global_rois.json`) therefore resolves inside SyncThing. Files that ship with the code (icons, the OCR model) must be loaded via `script_dir` / `__file__`, never by bare relative name. Run the app from this clone.

## Launch
Double-click `Launch_Windows.bat` / `Launch_Mac.command`. They use this repo's `.venv` (create it with `python -m venv .venv` and `pip install -r requirements.txt`). Windows Smart App Control is on for BTM-NOVA; if a DLL import is "blocked by an Application Control policy", retry once before investigating.
