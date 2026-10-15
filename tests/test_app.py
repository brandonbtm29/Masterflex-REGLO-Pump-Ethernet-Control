"""Smoke tests for the pump GUI. They run headless and never open a network connection."""

import importlib.metadata
import os
import struct

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

    window.dir_checkbox.setChecked(True)
    window.cmd_update_direction()
    assert window.output_data[0] & 0b01000000
    window.dir_checkbox.setChecked(False)
    window.cmd_update_direction()
    assert not window.output_data[0] & 0b01000000


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
    window.run_log_list.clear()
    window.log_started_run()
    window.log_finished_run(0.0)
    window.log_started_run()
    assert window.run_log_list.count() == 3

    monkeypatch.setattr(window, "_confirm", lambda *a: False)
    window.run_log_list.item(0).setSelected(True)
    window.cmd_delete_selected_logs()
    assert window.run_log_list.count() == 3  # said no

    monkeypatch.setattr(window, "_confirm", lambda *a: True)
    window.cmd_delete_selected_logs()
    assert window.run_log_list.count() == 2
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
