# Changelog

All notable changes to Masterflex REGLO Pump Control. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow
[Semantic Versioning](https://semver.org/): new features bump the middle number, fixes bump
the last, and changes that break existing settings or workflows bump the first.

## [Unreleased]

### Fixed
- **Time mode works.** It used to run until stopped; now it runs for On Time seconds.
- **Off/Interval and Batch Total are honoured** in Time and Volume modes: dispense, pause,
  repeat (Batch Total 0 = until stopped). The Batch tile shows progress, e.g. "2/5".
- **Communication problems are reported.** If the pump stops answering or rejects a command,
  the event log says so once, the status bar shows "No response from pump", and the app logs
  again when the pump is back. The dashboard no longer acts on stale data in the meantime.

### Changed
- Time and Volume modes refuse to start with an On Time or volume of 0 (Volume mode with 0
  used to run until stopped).
- Removed an unused duplicate of the restart function (no behaviour change).

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
