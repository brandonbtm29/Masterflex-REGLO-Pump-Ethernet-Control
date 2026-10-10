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
- **Transition status (Oct 2026):** the app still writes its data relative to the folder it's launched from, so lab runs still use the copy inside SyncThing. Planned change: add a per-machine "data folder" setting (stored in the gitignored config) that defaults to the SyncThing path above. Once that lands, run the app from this clone and keep only data in SyncThing.
