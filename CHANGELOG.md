# Changelog

All notable changes to Masterflex REGLO Pump Control. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow
[Semantic Versioning](https://semver.org/): new features bump the middle number, fixes bump
the last, and changes that break existing settings or workflows bump the first.

## [Unreleased]

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
- Time mode likely runs continuously: the drive is kept in continuous mode for every mode
  (since the Volume mode fix in August 2026) and only Volume mode has a software stop.
- Errors in the background comms loop are swallowed silently, so a dropped connection isn't
  logged.
- `cmd_restart_app` is defined twice in `pump_gui.py`; the second definition is the one used.
