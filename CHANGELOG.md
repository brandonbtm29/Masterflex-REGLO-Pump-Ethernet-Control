# Changelog

All notable changes to Masterflex REGLO Pump Control. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow
[Semantic Versioning](https://semver.org/): new features bump the middle number, fixes bump
the last, and changes that break existing settings or workflows bump the first.

## [Unreleased]

## [1.3.0] - 2026-10-28

### Added
- **Only one copy at a time.** Two copies of the app controlling the same pump would both send
  it commands every 100 ms, so one could keep starting the pump while the other stops it.
  Opening the app while it's already open now brings the open window to the front instead.
  Restart, Update and Restart, and changing the settings folder hand over to the new copy
  cleanly.
- **Open Log Folder and Copy Diagnostics** in ⚙ → App. Copy Diagnostics copies the version,
  system details, the app's folders, whether the pump is connected, the pump model (if Search
  Network found it) and the end of the error log, ready to paste into a GitHub issue or an
  email. The pump's IP address, its network name and the computer's name are left out.
- **Check for updates when the app starts**: a new option in ⚙ → App (on by default). Turn it
  off and the app only checks when you click Check for Updates.
- **The window remembers its size and position** (and whether it was maximized) on each
  computer. This is kept in `window_state.json` in the app's folder, not in the synced
  settings, so a laptop and a lab PC each keep their own.

### Changed
- **The launchers set the app up the first time.** Double-click `Launch_Windows.bat` or
  `Launch_Mac.command` on a new computer and it creates the `.venv` and installs what the app
  needs (a minute or two), then starts the app. If something goes wrong, the window stays open
  and says what happened. The `Setup_*` scripts are now only needed to repair or reinstall.
- **Updates reinstall the app's packages when a release changes `pyproject.toml` too**, not
  only `requirements.txt`, and install them the same way the Setup scripts do.

### Fixed
- **The error log keeps older errors.** The pump library wrote a line for every message to the
  pump (about 40 a second), so the log only reached back about ten minutes and Copy
  Diagnostics showed nothing but those lines. They're left out now; the library's warnings and
  errors still go in.
- **A failed update always goes back to the version you had.** Before, if installing the new
  packages took more than 15 minutes or couldn't start, the app was left half-updated and the
  Check for Updates button stayed greyed out. Now any failure after the download puts the app
  back as it was, says why, and the button works again. Git also no longer waits for a sign-in
  window that can't appear.
- **Changing the settings folder no longer restarts the app while the pump is running** or a
  Time/Volume program is in progress (restarting would stop it). The app says so instead, like
  Update does; stop the pump, then close and reopen the app.

## [1.2.0] - 2026-10-17

Shows when it's out of date, keeps its desktop icon current, runs without a console window,
logs errors, and measures Time/Volume dispenses more accurately.

### Added
- **Version shown bottom right.** It turns orange with "Update available: vX" when GitHub has a
  newer release (checked at launch and daily), and the event log mentions it once. Click it to
  open ⚙ → App.
- **Desktop icon made for you**: the first time the app runs on a computer it adds a
  "Masterflex Pump" icon with the pump logo, and refreshes it when the icon image, the app's
  folder or its Python changes (for example after an update). Delete it and it stays deleted;
  ⚙ → App adds it back.
- **Error log**: errors, with tracebacks (also from background threads), go to `logs/masterflex_pump.log`
  in the data folder. An unexpected error is shown in a dialog and the app keeps running instead of closing,
  so a running program isn't cut off.
- `Setup_Windows.bat` / `Setup_Mac.command`: one double-click creates the `.venv` and installs everything.
- Dependabot keeps the GitHub Actions and Python dependencies up to date.

### Changed
- **No console or Terminal window.** The Windows launcher starts the app without a console; the
  Mac launcher starts it and closes its Terminal window. The desktop icons never open one. If
  packages are missing, the launchers say so and point to the Setup scripts.

### Fixed
- **Time and Volume dispenses ran over by up to one extra poll interval** (about 0.1 s of flow,
  more on Windows and on slow machines). Each dispense was counted from the first status reading
  that showed the pump running, so whatever it pumped between the run command and that reading
  wasn't counted. Dispenses are now measured from the run command; the only overshoot left is
  that a stop can only be sent at a poll (at most one poll interval of flow).
- **The automatic connect at launch could disconnect you**: if you clicked Connect within the
  first 2 seconds, the timer then toggled the connection off again, stopping the pump and any
  running program. It now only connects, and does nothing if you're already connected.
- The end-to-end dispensing test failed intermittently on Windows and macOS CI because of both
  bugs above (and a pump address saved by an earlier test). It now checks each dispense against
  the measured poll gaps instead of a fixed limit.

## [1.1.0] - 2026-10-15

Safer pump control, working Time mode, one-click updates and a desktop icon. These changes
were tested with a simulated pump (including real threads); check a short Time and Volume
run on your pump before relying on them for an experiment.

### Fixed
- **Time mode works.** It used to run until stopped; now it runs for On Time seconds.
- **Off/Interval and Batch Total are honoured** in Time and Volume modes: dispense, pause,
  repeat (Batch Total 0 = until stopped). The Batch tile shows progress, e.g. "2/5".
- **Communication problems are reported.** If the pump stops answering or rejects a command,
  the event log says so once, the status bar shows "No response from pump", and the app logs
  again when the pump is back. The dashboard no longer acts on stale data in the meantime.
- **Stops don't depend on the window.** Time/Volume programs run in the communication thread,
  so a busy or frozen window can't delay a stop.
- **Disconnect and closing the app stop a running pump** first, and log the end of the run
  (before, no END row was written).
- **A program won't restart a pump you stopped on its touchscreen**, and gives up with a
  message if the pump doesn't start within 5 s (e.g. not in remote mode).
- **Connecting no longer freezes the window** while a missing pump times out, including the
  automatic connect at launch.
- **RPM tile** showed the flow number; it now estimates speed from the pump's own maximum
  flow, and is labelled "RPM (est.)".
- **"Calc. Time"** was always labelled "min", even for /hr, /s and /day units. It's replaced by
  **Run Time** (and "Last Run" when stopped), plus the time left in a dispense.
- **Run log columns no longer shift** when metadata tokens are added, removed or reordered;
  older files with extra values keep them as "Extra" columns.
- **Deleting runs** asks first, keeps the previous backup file as `.bak`, and no longer reverses
  the backup file's order.
- **Settings** are saved in one step, and an unreadable settings file is kept and reported
  instead of silently replaced with defaults.
- "System & Hardware" showed as "System_Hardware".

### Added
- **⚙ → App tab**: **Check for Updates** (updates a git clone to the latest GitHub release,
  reinstalls dependencies if needed, then restarts) and a **desktop icon** button: a
  "Masterflex Pump" app on macOS, a shortcut on Windows, a menu entry on Linux.
- Head-open warning in the status bar.
- `masterflex-reglo` command after `pip install -e .`.
- macOS (`.icns`) and multi-size Windows (`.ico`) icons in `assets/`; built apps include them.

### Changed
- Time and Volume modes refuse to start with an On Time or volume of 0 (Volume mode with 0
  used to run until stopped). Apply refuses flows of 0 or below, flows outside the pump's
  calibrated range, and negative times, volumes or batch counts.
- **The Restart buttons are gone** (top bar and Settings). The app still restarts itself after
  an update or a settings-folder change.
- The Remote Mode label is light blue, readable on the dark theme.
- `build_app.py` no longer runs pip by itself; install with `pip install -e ".[build]"`.
- Code split into `protocol.py`, `dispense.py`, `runlog.py`, `updates.py` and `shortcuts.py`,
  each with tests. Importing `pump_gui` no longer changes directory or creates folders.

## [1.0.0] - 2026-10-14

First tracked release. The app has been in lab use since June 2026; this release adds
documentation, tests and CI around it without changing what it does.
Earlier versions were co-developed with Google Gemini in Antigravity; development continues
with Claude (Anthropic).

### Features in this release
- Connect to a REGLO pump with Advanced Connectivity over EtherNet/IP by IP address or network
  search, with the identity handshake skipped and the 100 ms watchdog kept fed.
- Live dashboard (flow rate, cumulative volume, estimated time and RPM, batch, status, remote
  mode, tube size) with tiles you can reorder.
- Continuous and Volume modes; Volume mode stops the pump in software at the target volume and
  shows an estimated run time.
- Run history with Auto-Log to CSV, manual save/delete of runs, experiment notes and custom
  metadata tokens in every log row.
- Settings remembered between sessions, with an optional shared settings folder.
- Firmware USB helper, collapsible panels, icon or text buttons, and Windows/macOS launchers.

### Added
- README rewritten for newcomers: screenshot, features, setup per OS, file locations,
  configuration, how the protocol works, limitations, development and release steps, and how
  the app was built.
- `pump_config.example.json`, `SECURITY.md`, `.gitattributes` and this changelog.
- `pyproject.toml` with minimum dependency versions and a single version number
  (`pump_gui.__version__`).
- Headless tests and GitHub Actions CI (Windows, Linux and macOS; Python 3.11–3.13) with a
  full-history secret scan.
- `scripts/make_screenshot.py` to regenerate the README screenshot with sample data.

### Changed
- Code formatted and linted with ruff (no behaviour change).
- Old screenshots that showed real experiment details were replaced.

### Known issues
- Time mode likely runs continuously, Off/Interval and Batch Total are ignored, and
  communication errors are not logged (all fixed in the next release).
