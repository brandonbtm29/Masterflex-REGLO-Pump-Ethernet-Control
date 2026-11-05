"""Smoke tests for the pump GUI. They run headless and never open a network connection."""

import importlib.metadata
import os
import struct

import pytest
from conftest import fake_input


def test_version_matches_package_metadata(pump_gui):
    assert importlib.metadata.version("masterflex-reglo-control") == pump_gui.__version__


def test_import_uses_the_test_data_folder(pump_gui):
    assert pump_gui.PYCOMM3_AVAILABLE
    assert os.path.normcase(pump_gui.DATA_DIR) == os.path.normcase(os.environ["UAKRON_APP_DATA_DIR"])
    assert pump_gui.RUN_LOG.startswith(pump_gui.DATA_DIR)
    assert os.path.normcase(pump_gui.CONFIG_DIR) == os.path.normcase(os.environ["UAKRON_SETTINGS_DIR"])


def test_window_builds_with_defaults(window, pump_gui):
    assert window.windowTitle() == "Masterflex REGLO Pump Control"
    assert window.unit_menu.count() == len(pump_gui.FLOW_UNITS) == 16
    assert window.unit_menu.currentText() == "mL/min"
    assert not window.connected


def test_dashboard_decodes_the_input_assembly(window):
    window.connected = True
    window.input_data = fake_input(flow=5.0, cum_vol=18.75, tube=18)
    window.update_dashboard()

    assert window.lbl_mon_flow.text() == "Flow Rate\n5.0000 mL/min"
    assert window.lbl_mon_vol.text() == "Cum. Volume\n18.7500 mL"
    assert window.lbl_mon_status.text() == "Status OK: YES"
    assert window.remote_indicator.text() == "Remote Mode"
    assert window.running_indicator.text() == "● Pump Running"
    assert window.tube_indicator.text() == "Tube Code 18 (1.52 mm ID)"
    assert "Min: 0.02 | Max: 14.69" in window.flow_limits_label.text()


def test_dashboard_shows_local_mode_and_stopped(window):
    window.connected = True
    window.input_data = fake_input(status=0b1, flow=0.0)
    window.update_dashboard()

    assert window.remote_indicator.text() == "Local Mode"
    assert window.running_indicator.text() == "● Pump Stopped"


def test_apply_params_packs_the_output_assembly(window):
    window.flow_entry.setText("2.5")
    window.volume_entry.setText("40")
    window.on_time_entry.setText("10")
    window.off_time_entry.setText("5")
    window.batch_entry.setText("3")
    window.cmd_apply_params()

    out = window.output_data
    assert len(out) == 28
    assert struct.unpack_from("<f", out, 8)[0] == 2.5
    assert struct.unpack_from("<f", out, 12)[0] == 40.0
    assert struct.unpack_from("<f", out, 16)[0] == 10.0
    assert struct.unpack_from("<f", out, 20)[0] == 5.0
    assert struct.unpack_from("<i", out, 24)[0] == 3
    assert out[4] == 0  # the drive always stays in continuous mode; volume mode is done in software


def test_unit_and_direction_bits(window, pump_gui):
    window.cmd_update_unit("uL/min")
    assert window.output_data[6] == 6

    window.dir_cw_radio.setChecked(True)
    assert not window.output_data[0] & 0b01000000
    window.dir_ccw_radio.setChecked(True)
    assert window.output_data[0] & 0b01000000


def test_flow_outside_the_pumps_limits_is_refused(connected):
    window, pump = connected
    window._poll_once()
    window.update_dashboard()  # learns the limits 0.02 to 14.69
    window.flow_entry.setText("20")
    assert window.cmd_apply_params() is None
    assert "outside the pump's calibrated range" in window.console_textbox.toPlainText()
    window.flow_entry.setText("14.69")
    assert window.cmd_apply_params() is not None


def test_negative_and_zero_values_are_refused(window):
    window.flow_entry.setText("0")
    assert window.cmd_apply_params() is None
    window.flow_entry.setText("5")
    window.off_time_entry.setText("-1")
    assert window.cmd_apply_params() is None
    log = window.console_textbox.toPlainText()
    assert "Flow rate must be above 0" in log and "Off/Interval can't be negative" in log


def test_changing_unit_forgets_the_old_limits(connected):
    window, pump = connected
    pump.input_data = fake_input(status=0b10000001)  # stopped: no need to ask first
    window._poll_once()
    window.update_dashboard()
    assert window._flow_limits
    window.unit_menu.setCurrentText("uL/min")
    assert window._flow_limits is None


def test_dashboard_rpm_run_time_and_head_open(connected, monkeypatch):
    window, pump = connected
    pump.input_data = fake_input(status=0b10010011, flow=7.345, hi=14.69)
    window._poll_once()
    monkeypatch.setattr("pump_gui.time.time", lambda: 1000.0)
    window.update_dashboard()  # run starts at t=1000
    assert window.lbl_mon_rpm.text() == "RPM (est.)\n80.0"  # half the max flow -> half of 160 RPM
    assert window.lbl_mon_status.text() == "Status OK: YES (head open)"
    monkeypatch.setattr("pump_gui.time.time", lambda: 1075.0)
    window.update_dashboard()
    assert window.lbl_mon_calctime.text() == "Run Time\n1:15"
    assert "#4da3ff" in window.remote_indicator.styleSheet()  # readable on the dark theme


def test_history_delete_asks_first_and_keeps_order(window, pump_gui, monkeypatch):
    import runlog

    for path in (pump_gui.RUN_LOG, pump_gui.RUN_LOG_BACKUP):
        if os.path.exists(path):
            os.remove(path)
    window.run_table.setRowCount(0)
    window.log_started_run()
    window.log_finished_run(0.0)
    window.log_started_run()
    assert window.run_table.rowCount() == 3

    monkeypatch.setattr(window, "_confirm", lambda *a: False)
    window.run_table.selectRow(0)
    window.cmd_delete_selected_logs()
    assert window.run_table.rowCount() == 3  # said no

    monkeypatch.setattr(window, "_confirm", lambda *a: True)
    window.cmd_delete_selected_logs()
    assert window.run_table.rowCount() == 2
    events = [r["Event"] for r in runlog.read(pump_gui.RUN_LOG_BACKUP)[1]]
    assert events == ["START", "END"]  # still oldest first
    assert os.path.exists(pump_gui.RUN_LOG_BACKUP + ".bak")


def test_auto_log_writes_token_columns(window, pump_gui):
    import runlog

    if os.path.exists(pump_gui.RUN_LOG):
        os.remove(pump_gui.RUN_LOG)
    window.auto_log_cb.setChecked(True)
    window.token_inputs["Material"].setText("Sample media A")
    window.log_started_run()
    header, rows = runlog.read(pump_gui.RUN_LOG)
    assert header[: len(runlog.FIXED)] == runlog.FIXED and "Material" in header
    assert rows[-1]["Material"] == "Sample media A"


def test_unreadable_settings_are_kept_and_reported(pump_gui, qapp):
    path = os.path.join(pump_gui.CONFIG_DIR, "pump_config.json")
    os.makedirs(pump_gui.CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"ip": "192.0.2.10", ')  # cut off mid-write
    w = pump_gui.MasterflexPumpGUI()
    try:
        assert "Couldn't read the settings file" in w.console_textbox.toPlainText()
        kept = [n for n in os.listdir(pump_gui.CONFIG_DIR) if n.startswith("pump_config.json.unreadable-")]
        assert kept
        w.save_all_settings()
        with open(path, encoding="utf-8") as f:
            assert f.read().startswith("{")  # replaced with a valid file
        assert not os.path.exists(path + ".tmp")
    finally:
        w.timer.stop()
        w.close()
        for name in os.listdir(pump_gui.CONFIG_DIR):
            if name.startswith("pump_config.json"):
                os.remove(os.path.join(pump_gui.CONFIG_DIR, name))


def test_import_has_no_side_effects(pump_gui):
    # main() changes into the data folder; importing (tests, tools) must not.
    assert os.path.normcase(os.getcwd()) != os.path.normcase(pump_gui.DATA_DIR)


def test_relaunch_command_runs_this_file(pump_gui):
    program, args = pump_gui.relaunch_command()
    assert program == __import__("sys").executable
    assert os.path.samefile(args[0], pump_gui.__file__)


def test_icons_ship_with_the_code(pump_gui):
    for name in ("pump.png", "pump.ico", "pump.icns"):
        assert os.path.getsize(os.path.join(pump_gui.ASSETS, name)) > 1000


def test_settings_has_update_and_icon_buttons_and_no_restart(window, pump_gui, monkeypatch):
    import updates

    top_bar = [b.text() for b in window.findChildren(pump_gui.QPushButton)]
    assert "Restart App" not in top_bar
    dialog = pump_gui.SettingsDialog(window)
    tabs = [dialog.tabview.tabText(i) for i in range(dialog.tabview.count())]
    assert "App" in tabs
    assert dialog.update_btn.text() == "Check for Updates"
    assert dialog.shortcut_btn.text().startswith("Add ")

    older = updates.Release("0.9.0", "v0.9.0", "", updates.RELEASES_URL)
    dialog.on_update_checked(older, "")
    assert "latest version" in dialog.update_status.text()

    newer = updates.Release("9.0.0", "v9.0.0", "Big release", updates.RELEASES_URL)
    monkeypatch.setattr(updates, "can_update", lambda root: "")
    window.pump_running = True
    dialog.on_update_checked(newer, "")
    assert "Stop the pump" in dialog.update_status.text()

    window.pump_running = False
    monkeypatch.setattr(dialog, "confirm", lambda *a: False)
    dialog.on_update_checked(newer, "")
    assert dialog.update_status.text() == "Version 9.0.0 is available."

    dialog.on_update_checked(None, "Couldn't reach GitHub. Check the internet connection.")
    assert "Couldn't reach GitHub" in dialog.update_status.text()
    dialog.close()


def test_version_shows_bottom_right_and_flags_an_old_version(window, pump_gui):
    import updates

    assert window.version_btn.text() == f"v{pump_gui.__version__}"
    newer = updates.Release("99.0.0", "v99.0.0", "", updates.RELEASES_URL)
    window.on_update_check(newer, "")
    assert "Update available: v99.0.0" in window.version_btn.text()
    assert pump_gui.MASTERFLEX_ORANGE in window.version_btn.styleSheet()
    assert "99.0.0 is available" in window.console_textbox.toPlainText()

    same = updates.Release(pump_gui.__version__, f"v{pump_gui.__version__}", "", updates.RELEASES_URL)
    window.on_update_check(same, "")
    assert window.version_btn.text() == f"v{pump_gui.__version__}"
    assert "Up to date" in window.version_btn.toolTip()

    window.on_update_check(None, "Couldn't reach GitHub.")
    assert "Couldn't check" in window.version_btn.toolTip()


def test_clicking_the_version_opens_settings_on_the_app_tab(window, pump_gui, monkeypatch):
    shown = []
    monkeypatch.setattr(
        pump_gui.SettingsDialog,
        "exec",
        lambda self: shown.append(self.tabview.tabText(self.tabview.currentIndex())),
    )
    window.version_btn.click()
    assert shown == ["App"]


def test_desktop_icon_is_made_on_first_launch_and_remembered(window, pump_gui, qapp, monkeypatch):
    import time

    import shortcuts

    calls = []

    def fake_ensure(root, assets, record):
        calls.append(record)
        return {"path": "/Desktop/Masterflex Pump.app", "stamp": "abc"}, "Added a desktop icon: here"

    monkeypatch.setattr(shortcuts, "ensure", fake_ensure)
    window.config_data.pop("desktop_icons", None)
    window.ensure_desktop_icon()
    deadline = time.monotonic() + 2
    while not window.config_data.get("desktop_icons") and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    assert calls == [None]
    assert list(window.config_data["desktop_icons"].values()) == [
        {"path": "/Desktop/Masterflex Pump.app", "stamp": "abc"}
    ]
    assert "Added a desktop icon" in window.console_textbox.toPlainText()


# --- App tab: log folder, diagnostics, update check at start-up ----------------------------


def test_hide_network_details(pump_gui):
    text = "Connecting to 192.0.2.10:44818... Found REGLO at pump-01.lab.example. Version 1.2.0.4.5"
    out = pump_gui.hide_network_details(text, ["pump-01.lab.example", "", None])
    assert "192.0.2.10" not in out and "pump-01.lab.example" not in out
    assert out.count("[hidden]") == 2
    assert "1.2.0.4.5" in out  # a version number isn't an address


def test_copy_diagnostics_leaves_out_the_pump_address(window, pump_gui, qapp, monkeypatch, tmp_path):
    import crash_log

    log = tmp_path / "logs" / "masterflex_pump.log"
    log.parent.mkdir()
    log.write_text(
        "INFO masterflex_pump starting\n"
        "INFO pycomm3 Discovered 1 device(s): [{'ip_address': '198.51.100.7', 'product_name': 'REGLO'}]\n"
        "ERROR Couldn't reach pump-01.lab.example\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(crash_log, "log_path", lambda: str(log))
    window.ip_entry.setText("pump-01.lab.example")
    window.config_data["ip"] = "192.0.2.10"
    window.pump_model = "REGLO ICC Digital"

    dialog = pump_gui.SettingsDialog(window)
    assert dialog.log_folder_btn.text() == "Open Log Folder"
    assert dialog.copy_diag_btn.text() == "Copy Diagnostics"
    qapp.clipboard().clear()
    dialog.copy_diag_btn.click()
    text = qapp.clipboard().text()
    assert text.startswith(f"{pump_gui.APP_NAME} {pump_gui.__version__}")
    assert "Pump: not connected" in text and "Pump model: REGLO ICC Digital" in text
    assert "Couldn't reach [hidden]" in text  # the end of the error log is included
    for private in ("198.51.100.7", "192.0.2.10", "pump-01.lab.example"):
        assert private not in text
    node = __import__("platform").node()
    if len(node) >= 3:
        assert node not in text
    assert dialog.diag_status.text().startswith("Diagnostics copied.")
    dialog.close()


def test_open_log_folder(window, pump_gui, monkeypatch, tmp_path):
    import crash_log
    import diagnostics

    opened = []
    monkeypatch.setattr(diagnostics, "open_folder", opened.append)
    monkeypatch.setattr(crash_log, "log_path", lambda: str(tmp_path / "logs" / "masterflex_pump.log"))
    dialog = pump_gui.SettingsDialog(window)
    dialog.log_folder_btn.click()
    assert opened == [str(tmp_path / "logs")]

    def broken(path):
        raise OSError("There is no folder to open yet.")

    monkeypatch.setattr(diagnostics, "open_folder", broken)
    dialog.log_folder_btn.click()
    assert "Couldn't open the log folder: There is no folder to open yet." in dialog.diag_status.text()
    dialog.close()


def test_check_for_updates_at_start_setting(window, pump_gui):
    from PyQt6.QtCore import QTimer

    assert window.check_updates_on_start()  # on by default
    dialog = pump_gui.SettingsDialog(window)
    assert dialog.check_on_start_cb.text() == "Check for updates when the app starts"
    assert dialog.check_on_start_cb.isChecked()

    window._update_timer = QTimer(window)  # the daily re-check, as start_update_check makes it
    window._update_timer.start(3_600_000)
    dialog.check_on_start_cb.setChecked(False)
    assert not window.check_updates_on_start()
    assert not window._update_timer.isActive()
    with open(window.config_file, encoding="utf-8") as f:
        assert __import__("json").load(f)["check_updates_on_start"] is False
    dialog.close()

    again = pump_gui.MasterflexPumpGUI()  # read back from the settings file
    try:
        assert not again.check_updates_on_start()
        assert not pump_gui.SettingsDialog(again).check_on_start_cb.isChecked()
    finally:
        again.timer.stop()
        again.close()
    dialog = pump_gui.SettingsDialog(window)
    dialog.check_on_start_cb.setChecked(True)
    assert window.check_updates_on_start() and window._update_timer.isActive()
    dialog.close()


# --- Restart and the single-instance lock -------------------------------------------------


def test_restart_releases_the_lock_before_starting_the_new_copy(window, pump_gui, monkeypatch):
    from PyQt6.QtCore import QProcess

    events = []
    monkeypatch.setattr(pump_gui.single_instance, "release", lambda: events.append("release"))
    monkeypatch.setattr(QProcess, "startDetached", lambda *args: events.append("start") or True)
    monkeypatch.setattr(pump_gui.QApplication, "quit", lambda: events.append("quit"))
    window.cmd_restart_app()
    assert events == ["release", "start", "quit"]

    # Update and Restart goes the same way.
    events.clear()
    monkeypatch.setattr(pump_gui.QMessageBox, "information", lambda *args: None)
    dialog = pump_gui.SettingsDialog(window)
    dialog.on_update_done(True, "Updated to v9.9.9.")
    assert events == ["release", "start", "quit"]
    dialog.close()


# --- Window layout -----------------------------------------------------------------------


def test_window_layout_is_remembered_on_this_computer_only(pump_gui, qapp, tmp_path):
    from PyQt6.QtCore import QRect

    assert os.path.dirname(pump_gui.WINDOW_STATE_FILE) == pump_gui.APP_DIR  # not the synced folder
    with open(os.path.join(os.path.dirname(pump_gui.__file__), ".gitignore"), encoding="utf-8") as f:
        assert "window_state.json" in f.read().split()

    state = tmp_path / "window_state.json"
    first = pump_gui.MasterflexPumpGUI()
    first.layout_file = str(state)
    assert not first.restore_layout()  # nothing saved yet: main() then opens it maximized
    first.setGeometry(QRect(0, 40, 800, 650))  # fits the 800 x 800 offscreen screen; default is 1000 x 750
    first.show()
    qapp.processEvents()
    first.timer.stop()
    first.close()  # saves on close
    assert state.exists()

    second = pump_gui.MasterflexPumpGUI()
    second.layout_file = str(state)
    try:
        assert second.restore_layout()
        assert (second.width(), second.height()) == (800, 650)
    finally:
        second.timer.stop()
        second.close()  # never shown, so it doesn't overwrite the saved layout

    state.write_text("not json", encoding="utf-8")
    third = pump_gui.MasterflexPumpGUI()
    third.layout_file = str(state)
    try:
        assert not third.restore_layout()  # a damaged file is ignored
    finally:
        third.timer.stop()
        third.close()


# --- Error log: pycomm3's per-message chatter stays out ----------------------------------


def test_pycomm3_chatter_stays_out_of_the_error_log(pump_gui, tmp_path):
    import inspect
    import logging

    import pycomm3

    import crash_log

    # main() quiets pycomm3 straight after setting up the log.
    source = inspect.getsource(pump_gui.main)
    assert source.index("quiet_chatty_loggers()") > source.index("crash_log.setup(")

    root, chatty = logging.getLogger(), logging.getLogger("pycomm3")
    saved = root.level, chatty.level
    crash_log._reset_for_tests()
    try:
        path = crash_log.setup("masterflex_pump", str(tmp_path), "9.9.9", qt_dialog=False)
        pump_gui.quiet_chatty_loggers()

        class Reply:  # what the pump sends back
            def __init__(self, error=None):
                self.value, self.error = b"\x00" * 56, error

            def __bool__(self):
                return self.error is None

        # pycomm3's own code, with the network left out: one message that works, one that fails.
        driver = pycomm3.CIPDriver("192.0.2.1")
        driver.send = lambda request: Reply()
        driver.generic_message(service=b"\x0e", class_code=b"\x04", instance=100, connected=False)
        driver.send = lambda request: Reply("pump said no")
        driver.generic_message(service=b"\x0e", class_code=b"\x04", instance=100, connected=False)
        logging.getLogger("pycomm3.cip_driver").info("Attempting an Extended Forward Open...")
        logging.getLogger("pycomm3.cip_driver").warning("a pycomm3 warning")
        pump_gui.log.info("the app's own info message")
        for handler in root.handlers:
            handler.flush()
        with open(path, encoding="utf-8") as f:
            text = f.read()
    finally:
        crash_log._reset_for_tests()
        root.setLevel(saved[0])
        chatty.setLevel(saved[1])

    assert "Sending generic message" not in text and "completed" not in text  # INFO: dropped
    assert "Extended Forward Open" not in text
    assert "ERROR pycomm3.cip_driver.CIPDriver" in text and "pump said no" in text  # errors kept
    assert "WARNING pycomm3.cip_driver" in text and "a pycomm3 warning" in text  # warnings kept
    assert "INFO masterflex_pump" in text and "the app's own info message" in text
    assert "masterflex_pump 9.9.9 starting" in text


# --- A busy pump: restart and update wait for it -----------------------------------------


def make_busy(window, how):
    import dispense

    if how == "running":
        window.pump_running = True
    else:  # a Time/Volume program pausing between dispenses: the pump is still, but it's busy
        window.dispense.state = dispense.PAUSING


@pytest.fixture
def restarts(pump_gui, monkeypatch):
    """Record restarts and warning boxes instead of starting a new copy or blocking on a dialog."""
    from PyQt6.QtCore import QProcess

    events = []
    monkeypatch.setattr(pump_gui.single_instance, "release", lambda: events.append("release"))
    monkeypatch.setattr(QProcess, "startDetached", lambda *args: events.append("start") or True)
    monkeypatch.setattr(pump_gui.QApplication, "quit", lambda: events.append("quit"))
    monkeypatch.setattr(pump_gui.QMessageBox, "warning", lambda parent, title, text: events.append(text))
    monkeypatch.setattr(pump_gui.QMessageBox, "information", lambda parent, title, text: events.append(text))
    return events


@pytest.mark.parametrize("how", ["running", "program"])
def test_restart_refuses_while_the_pump_is_busy(window, restarts, how):
    make_busy(window, how)
    assert window.busy_reason()
    assert window.cmd_restart_app() is False
    assert "release" not in restarts and "start" not in restarts and "quit" not in restarts
    assert "Stop the pump, then close and reopen the app" in restarts[-1]

    window.pump_running = False
    window.dispense.cancel()
    assert window.busy_reason() == ""
    restarts.clear()
    assert window.cmd_restart_app() is True
    assert restarts == ["release", "start", "quit"]


def test_settings_folder_restart_checks_the_pump_first(window, pump_gui, restarts, monkeypatch, tmp_path):
    import settings_location

    # Never touch the real settings pointer: the folder change itself is faked.
    monkeypatch.setattr(settings_location, "change", lambda *args: (str(tmp_path), [], []))
    monkeypatch.setattr(
        pump_gui.QMessageBox, "question", lambda *args: pump_gui.QMessageBox.StandardButton.Yes
    )
    dialog = pump_gui.SettingsDialog(window)
    use_default = next(b for b in dialog.findChildren(pump_gui.QPushButton) if b.text() == "Use Default")

    window.pump_running = True
    use_default.click()  # "Restart now to load settings from the new folder?" -> Yes
    assert "start" not in restarts and "quit" not in restarts
    assert "The pump is running." in restarts[-1]

    window.pump_running = False
    restarts.clear()
    use_default.click()
    assert restarts == ["release", "start", "quit"]
    dialog.close()


def test_update_that_finishes_while_the_pump_runs_doesnt_restart(window, pump_gui, restarts):
    dialog = pump_gui.SettingsDialog(window)
    window.pump_running = True
    dialog.on_update_done(True, "Updated to v9.9.9.")
    assert "start" not in restarts and "quit" not in restarts
    assert "Updated to v9.9.9." in dialog.update_status.text()
    assert "close and reopen the app" in dialog.update_status.text()
    dialog.close()


@pytest.mark.parametrize(
    "outcome",
    [
        (False, "Installing the new dependencies failed, so the app went back to the version it had."),
        OSError("git vanished"),  # update_to shouldn't raise, but if it ever does
    ],
)
def test_failed_update_gives_the_button_back_and_says_why(
    window, pump_gui, qapp, restarts, monkeypatch, outcome
):
    import time

    import updates

    def fake_update_to(root, tag, python=None):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(updates, "can_update", lambda root: "")
    monkeypatch.setattr(updates, "update_to", fake_update_to)
    dialog = pump_gui.SettingsDialog(window)
    monkeypatch.setattr(dialog, "confirm", lambda *a: True)
    dialog.on_update_checked(updates.Release("9.0.0", "v9.0.0", "", updates.RELEASES_URL), "")
    assert not dialog.update_btn.isEnabled()  # while it runs
    deadline = time.monotonic() + 10
    while not dialog.update_btn.isEnabled() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert dialog.update_btn.isEnabled()
    expected = "went back to the version it had" if isinstance(outcome, tuple) else "git vanished"
    assert expected in dialog.update_status.text()
    assert expected in restarts[-1]  # shown in a warning box too
    assert "start" not in restarts  # no restart after a failed update
    dialog.close()


# --- Safety: nothing looks sent when it isn't, and nothing stops the pump unasked ----------


def test_pump_controls_are_greyed_out_until_connected(window):
    from conftest import FakePump

    for button in (window.start_stop_btn, window.remote_btn, window.reset_vol_btn):
        assert not button.isEnabled()
    assert window.apply_params_btn.isEnabled()  # checks the values; they're sent on connect
    window.on_connect_result(FakePump(), "")
    assert window.start_stop_btn.isEnabled() and window.remote_btn.isEnabled()
    window.disconnect()
    assert not window.start_stop_btn.isEnabled()


def test_start_without_a_connection_says_so(window):
    window.flow_entry.setText("5")
    window.cmd_start()
    log = window.console_textbox.toPlainText()
    assert "connect to the pump first" in log and "Command: START" not in log
    assert not window.output_data[0] & 1


def test_apply_without_a_connection_doesnt_claim_it_was_sent(window):
    window.flow_entry.setText("5")
    assert window.cmd_apply_params() is not None
    assert "sent to the pump when you connect" in window.console_textbox.toPlainText()


def test_escape_stops_the_pump(connected):
    window, pump = connected
    window.flow_entry.setText("5")
    window.cmd_start()
    assert window.output_data[0] & 1
    window.stop_shortcut.activated.emit()
    assert not window.output_data[0] & 1
    assert pump.writes[-1][0] & 1 == 0


def running(window, pump):
    """Start the pump and let the window see it running."""
    window.flow_entry.setText("5")
    window.cmd_start()
    window._poll_once()
    window.update_dashboard()
    assert window.busy_reason()


def test_changing_mode_while_running_asks_and_can_be_cancelled(connected, monkeypatch):
    window, pump = connected
    running(window, pump)
    questions = []
    monkeypatch.setattr(window, "_confirm", lambda title, text: questions.append(text) or False)
    window.mode_radio1.click()
    assert questions and "Changing the mode stops the pump" in questions[0]
    assert window.mode_radio0.isChecked()  # put back
    assert window.output_data[0] & 1  # still running


def test_changing_mode_while_running_stops_after_yes(connected, monkeypatch):
    window, pump = connected
    running(window, pump)
    monkeypatch.setattr(window, "_confirm", lambda *a: True)
    window.mode_radio2.click()
    assert window.mode_radio2.isChecked()
    assert not window.output_data[0] & 1


def test_changing_mode_while_stopped_doesnt_ask(connected):
    window, pump = connected
    window.mode_radio1.click()  # the fixture's _confirm fails the test if it's asked
    assert window.mode_radio1.isChecked()
    assert "Mode set to: Time" in window.console_textbox.toPlainText()


def test_changing_direction_while_running_can_be_cancelled(connected, monkeypatch):
    window, pump = connected
    running(window, pump)
    monkeypatch.setattr(window, "_confirm", lambda *a: False)
    assert window.dir_ccw_radio.isChecked()
    window.dir_cw_radio.click()
    assert window.dir_ccw_radio.isChecked()  # put back
    assert window.output_data[0] & 1


def test_changing_unit_while_running_can_be_cancelled(connected, monkeypatch):
    window, pump = connected
    running(window, pump)
    monkeypatch.setattr(window, "_confirm", lambda *a: False)
    window.unit_menu.setCurrentText("L/min")
    assert window.unit_menu.currentText() == "mL/min"
    assert window.output_data[0] & 1


def test_alarm_banner_for_head_open_fault_and_lost_link(connected):
    window, pump = connected
    assert window.alarm_banner.isHidden()
    pump.input_data = fake_input(status=0b10010011)  # head open
    window._poll_once()
    window.update_dashboard()
    assert not window.alarm_banner.isHidden() and "head is open" in window.alarm_banner.text()
    window._report_comm("read failed: timed out")  # as the comms thread does
    assert "No response from the pump" in window.alarm_banner.text()
    pump.input_data = fake_input()
    window._report_comm("")
    window._poll_once()
    window.update_dashboard()
    assert window.alarm_banner.isHidden()
    pump.input_data = fake_input(status=0b10000010)  # Status OK bit off
    window._poll_once()
    window.update_dashboard()
    assert "reports a problem" in window.alarm_banner.text()
    window.disconnect()
    assert window.alarm_banner.isHidden()


def test_reset_volume_asks_and_is_refused_during_a_run(connected, monkeypatch):
    window, pump = connected
    running(window, pump)
    window.cmd_reset_vol()  # the fixture fails the test if this asks
    assert "Volume not reset" in window.console_textbox.toPlainText()
    window.cmd_stop()
    pump.input_data = fake_input(status=0b10000001)
    window._poll_once()
    window.update_dashboard()
    asked = []
    monkeypatch.setattr(window, "_confirm", lambda *a: asked.append(a) or False)
    before = len(pump.writes)
    window.cmd_reset_vol()
    assert asked and len(pump.writes) == before  # said no: nothing sent


# --- Layout: readouts all visible, works at the minimum size ------------------------------


def test_all_readouts_show_at_once(window):
    window.mode_radio2.setChecked(True)
    window.update_parameter_visibility()
    assert window.tiles.shown() == ["flow", "vol", "calc_time", "rpm", "batch"]
    window.mode_radio0.setChecked(True)
    window.update_parameter_visibility()
    assert "batch" not in window.tiles.shown()  # no batches in Continuous mode


def test_tiles_can_be_reordered_and_the_order_is_kept(window, pump_gui):
    window.tiles.move_tile("rpm", -1)
    assert window.tiles.order[:4] == ["flow", "vol", "rpm", "calc_time"]
    assert window.config_data["monitor_order"][:4] == ["flow", "vol", "rpm", "calc_time"]
    again = pump_gui.MasterflexPumpGUI()
    try:
        assert again.tiles.order[:4] == ["flow", "vol", "rpm", "calc_time"]
    finally:
        again.timer.stop()
        again.close()


def test_window_works_at_its_minimum_size(window, qapp):
    window.resize(window.minimumSize())
    window.show()
    qapp.processEvents()
    left, right = window.main_splitter.widget(0), window.main_splitter.widget(1)
    assert left.geometry().right() < right.geometry().left()  # side by side, not overlapping
    assert right.width() >= 300
    assert window.tiles.columns == 2  # narrow: two tiles across


def test_divider_positions_are_remembered(pump_gui, qapp, tmp_path):
    from PyQt6.QtCore import QRect

    state = tmp_path / "window_state.json"
    first = pump_gui.MasterflexPumpGUI()
    first.layout_file = str(state)
    first.setGeometry(QRect(0, 40, 800, 650))
    first.show()
    qapp.processEvents()
    first.main_splitter.setSizes([380, 420])
    qapp.processEvents()
    first.timer.stop()
    first.close()

    second = pump_gui.MasterflexPumpGUI()
    second.layout_file = str(state)
    try:
        assert second.restore_layout()
        second.show()
        qapp.processEvents()
        assert abs(second.main_splitter.sizes()[0] - 380) <= 2
    finally:
        second.layout_file = None
        second.timer.stop()
        second.close()


# --- Parameters: numbers only, units shown, whole-program estimate -------------------------


def test_parameter_boxes_take_numbers_only(window):
    from PyQt6.QtGui import QValidator

    for entry in (window.flow_entry, window.volume_entry, window.on_time_entry, window.off_time_entry):
        validator = entry.validator()
        assert validator.validate("abc", 0)[0] == QValidator.State.Invalid
        assert validator.validate("-1", 0)[0] == QValidator.State.Invalid
        assert validator.validate("2.5", 0)[0] == QValidator.State.Acceptable
    assert window.batch_entry.validator().validate("1.5", 0)[0] != QValidator.State.Acceptable


def test_program_estimate(pump_gui):
    estimate = pump_gui.program_estimate
    # Volume: 10 mL at 5 mL/min = 2:00 each; 3 dispenses with two 30 s pauses = 7:00
    text = estimate(2, "mL/min", flow="5", volume="10", on_time="0", off_time="30", batch="3")
    assert "2:00 per dispense" in text and "3 dispenses, 2 pauses): ≈ 7:00" in text
    # Time: 30 s at 6 mL/min pumps 3 mL each
    text = estimate(1, "mL/min", flow="6", volume="0", on_time="30", off_time="0", batch="1")
    assert text == "≈ 3 mL per dispense"
    assert "Repeats until stopped" in estimate(
        1, "mL/min", flow="6", volume="0", on_time="30", off_time="5", batch="0"
    )
    empty_flow = estimate(2, "mL/min", flow="", volume="10", on_time="0", off_time="0", batch="1")
    assert empty_flow == "Est. Time: --"
    assert "RPM" in estimate(2, "RPM", flow="50", volume="10", on_time="0", off_time="0", batch="1")
    assert estimate(0, "mL/min", flow="5", volume="1", on_time="1", off_time="0", batch="1") == ""


def test_estimate_and_units_follow_the_boxes(window):
    from PyQt6.QtWidgets import QLabel

    window.mode_radio2.setChecked(True)
    window.update_parameter_visibility()
    window.flow_entry.setText("5")
    window.volume_entry.setText("10")
    window.batch_entry.setText("2")
    window.off_time_entry.setText("60")
    assert "≈ 5:00" in window.lbl_est_time.text()  # 2 x 2:00 + 1:00
    labels = [w.text() for w in window.params_layout.parentWidget().findChildren(QLabel)]
    assert "Dispense Volume (mL):" in labels
    window.unit_menu.setCurrentText("uL/min")
    labels = [w.text() for w in window.params_layout.parentWidget().findChildren(QLabel)]
    assert "Dispense Volume (uL):" in labels


def test_direction_is_a_clear_choice_and_is_saved(window, pump_gui):
    window.dir_cw_radio.setChecked(True)
    window.save_all_settings()
    assert window.config_data["direction"] == "CW"
    again = pump_gui.MasterflexPumpGUI()
    try:
        assert again.dir_cw_radio.isChecked() and not again.dir_ccw_radio.isChecked()
    finally:
        again.timer.stop()
        again.close()


# --- Logs: times, a history table, settings that stick --------------------------------------


def test_event_log_lines_have_the_time_and_are_escaped(window):
    import re

    window.log_msg_ui("flow <5> & rising")
    window.log_error_ui("boom")
    text = window.console_textbox.toPlainText()
    assert re.search(r"\d\d:\d\d:\d\d\s+Error: boom", text)
    assert re.search(r"\d\d:\d\d:\d\d\s+flow <5> & rising", text)  # shown as typed, not as HTML


def test_history_is_a_table_and_unsaved_rows_are_marked(window, pump_gui):
    for path in (pump_gui.RUN_LOG, pump_gui.RUN_LOG_BACKUP):
        if os.path.exists(path):
            os.remove(path)
    window.run_table.setRowCount(0)
    window.auto_log_cb.setChecked(False)
    window.flow_entry.setText("5")
    window.log_started_run()
    cells = [window.run_table.item(0, c).text() for c in range(window.run_table.columnCount())]
    assert cells[1:5] == ["START", "Continuous", "5 mL/min", "No"]
    assert window.run_table.item(0, 0).font().italic()
    window.run_table.selectRow(0)
    window.cmd_save_selected_logs()
    assert window.run_table.item(0, 4).text() == "Yes (saved later)"
    assert not window.run_table.item(0, 0).font().italic()
    window.auto_log_cb.setChecked(True)
    window.log_finished_run(1.0)
    assert window.run_table.item(0, 4).text() == "Yes" and window.run_table.item(0, 1).text() == "END"


def test_auto_log_and_closed_sections_are_remembered(window, pump_gui):
    window.auto_log_cb.setChecked(True)
    notes = next(
        b for b in window.findChildren(pump_gui.CollapsibleBox) if b.title_text == "Experimental Notes"
    )
    notes.toggle_button.click()  # close it
    assert "Experimental Notes" in window.config_data["collapsed_sections"]
    again = pump_gui.MasterflexPumpGUI()
    try:
        assert again.auto_log_cb.isChecked()
        boxes = {b.title_text: b for b in again.findChildren(pump_gui.CollapsibleBox)}
        assert not boxes["Experimental Notes"].toggle_button.isChecked()
        assert boxes["Connection"].toggle_button.isChecked()
    finally:
        again.timer.stop()
        again.close()


def test_removing_a_token_asks_first(window, monkeypatch):
    window.token_inputs["Material"].setText("Sample media A")
    asked = []
    monkeypatch.setattr(window, "_confirm", lambda title, text: asked.append(text) or False)
    window.cmd_remove_token("Material")
    assert "Material" in window.token_inputs and "Sample media A" in asked[0]
    monkeypatch.setattr(window, "_confirm", lambda *a: True)
    window.cmd_remove_token("Material")
    assert "Material" not in window.token_inputs
    assert "Material" not in window.config_data["metadata_tokens"]
