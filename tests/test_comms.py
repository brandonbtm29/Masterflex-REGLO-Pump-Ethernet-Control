"""Communication errors with the pump are reported instead of swallowed."""

from conftest import FakePump, fake_input
from pycomm3.exceptions import CommError

import protocol as proto


def console(window):
    return window.console_textbox.toPlainText()


def test_poll_reads_status_and_resends_output(connected):
    window, pump = connected
    window.output_data[0] = 0b1
    window._poll_once()
    assert window.link_ok
    assert bytes(window.input_data) == bytes(pump.input_data)
    assert pump.writes[-1] == bytes(window.output_data)


def test_lost_and_restored_are_logged_once(connected):
    window, pump = connected
    pump.fail_with = CommError("timed out")
    for _ in range(5):
        window._poll_once()
    assert not window.link_ok
    assert window.status_label.text() == "Status: No response from pump"
    assert console(window).count("Lost communication") == 1
    assert "timed out" in console(window)

    pump.fail_with = None
    window._poll_once()
    assert window.link_ok
    assert window.status_label.text() == "Status: Connected (IP)"
    assert console(window).count("Communication with the pump restored") == 1


def test_rejected_write_is_reported(connected):
    window, pump = connected
    pump.write_error = "Attribute not settable"
    window.write_output_data()
    assert not window.link_ok
    assert "write rejected: Attribute not settable" in console(window)


def test_short_read_is_an_error(connected):
    window, pump = connected
    pump.input_data = bytes(10)
    window._poll_once()
    assert not window.link_ok
    assert "expected 56" in console(window)


def test_dashboard_ignores_stale_data_while_link_is_down(connected):
    window, pump = connected
    window._poll_once()
    window.update_dashboard()
    assert window.running_indicator.text() == "● Pump Running"

    pump.fail_with = CommError("unplugged")
    window._poll_once()
    window.running_indicator.setText("sentinel")
    window.update_dashboard()
    assert window.running_indicator.text() == "sentinel"


def test_connect_runs_the_real_poll_thread(window, qapp, monkeypatch):
    """End to end: Connect starts the background thread, which talks to the (fake) pump and
    reports a dropped link to the window through a Qt signal."""
    import time

    from conftest import FakePump

    pump = FakePump()
    pump.open = lambda: None
    monkeypatch.setattr("pump_gui.PumpDriver", lambda target: pump)
    window.ip_entry.setText("192.0.2.10")
    window.toggle_connection()
    try:
        deadline = time.monotonic() + 2
        while len(pump.writes) < 3 and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        assert len(pump.writes) >= 3  # watchdog block re-sent every ~100 ms

        pump.fail_with = CommError("cable unplugged")
        deadline = time.monotonic() + 2
        while window.link_ok and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        qapp.processEvents()
        assert window.status_label.text() == "Status: No response from pump"
    finally:
        window.toggle_connection()  # disconnect; the thread exits on its next cycle
        time.sleep(0.25)


def test_disconnect_while_running_stops_the_pump_and_logs_the_end(connected):
    window, pump = connected
    window.flow_entry.setText("5")
    window.cmd_start()
    window._poll_once()
    window.update_dashboard()  # sees the pump running: START logged
    assert window.run_log_active
    pump.writes.clear()

    window.disconnect()
    assert pump.writes and pump.writes[0][0] & 1 == 0  # Stop sent before closing
    assert not window.connected and not window.run_log_active
    newest = window.history_rows()[0]
    assert newest["Event"] == "END" and "app disconnected during the run" in newest["Other Info"]
    assert "app disconnected during the run" in window.run_table.item(0, 5).text()
    assert "Stopped the pump before disconnecting" in console(window)


def test_failed_connect_does_not_freeze_or_connect(window, qapp, monkeypatch):
    import time

    def refuse(target):
        raise OSError("No route to host")

    monkeypatch.setattr("pump_gui.PumpDriver", refuse)
    window.ip_entry.setText("192.0.2.10")
    start = time.monotonic()
    window.connect()
    assert time.monotonic() - start < 0.5  # returns at once; the attempt runs in a thread
    assert window.connect_btn.text() == "Connecting..." and not window.connect_btn.isEnabled()
    deadline = time.monotonic() + 2
    while window._connecting and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    assert not window.connected and window.connect_btn.isEnabled()
    assert window.connect_btn.text() == "Connect"
    assert "No route to host" in console(window)


def test_auto_connect_never_disconnects(pump_gui, qapp, monkeypatch):
    """A saved address makes the app connect 2 s after it opens. If you clicked Connect
    yourself in those 2 s, that timer must not disconnect you (it used to toggle)."""
    import json
    import os

    scheduled = []
    monkeypatch.setattr(pump_gui.QTimer, "singleShot", lambda ms, fn: scheduled.append(fn))
    with open(os.path.join(pump_gui.CONFIG_DIR, "pump_config.json"), "w", encoding="utf-8") as f:
        json.dump({"ip": "192.0.2.10"}, f)
    window = pump_gui.MasterflexPumpGUI()
    try:
        assert window.connect in scheduled and window.toggle_connection not in scheduled
        window.connected = True  # e.g. you clicked Connect first
        window.connect()  # the timer fires
        assert window.connected and not window._connecting
    finally:
        window.connected = False
        window.timer.stop()
        window.close()


# --- Flow unit and direction are sent once connected -------------------------------------


def connect_without_thread(window, pump, monkeypatch):
    """on_connect_result as after a real connect, but the test runs the comms cycles itself."""
    monkeypatch.setattr(window, "poll_pump_data", lambda: None)
    window.on_connect_result(pump, "")


def test_unit_and_direction_on_screen_are_sent_after_connecting(window, monkeypatch):
    # The defaults (mL/min, counter-clockwise): before the fix they were never sent unless changed.
    assert window.unit_menu.currentText() == "mL/min" and window.dir_ccw_radio.isChecked()
    pump = FakePump(fake_input(status=0b10000001))  # connected, not running
    connect_without_thread(window, pump, monkeypatch)
    window._poll_once()
    sent = pump.writes[-1]
    assert sent[6] == proto.unit_code("mL/min")
    assert sent[0] >> proto.DIRECTION_CCW & 1
    assert "Sent the flow unit (mL/min) and direction (counter-clockwise)" in console(window)


def test_saved_unit_and_direction_are_sent_after_connecting(window, monkeypatch):
    window.unit_menu.setCurrentText("uL/min")
    window.dir_cw_radio.setChecked(True)
    pump = FakePump(fake_input(status=0b10000001))
    connect_without_thread(window, pump, monkeypatch)
    window._poll_once()
    assert pump.writes[-1][6] == proto.unit_code("uL/min")
    assert not pump.writes[-1][0] >> proto.DIRECTION_CCW & 1


def test_a_pump_running_at_connect_is_not_reversed_until_it_stops(window, monkeypatch):
    pump = FakePump(fake_input(status=0b00000011))  # running from its touchscreen (local mode)
    connect_without_thread(window, pump, monkeypatch)
    window._poll_once()
    window._poll_once()
    assert pump.writes[-1][6] == 0 and not pump.writes[-1][0] >> proto.DIRECTION_CCW & 1
    assert console(window).count("sends its flow unit and direction when it stops") == 1  # said once
    pump.input_data = fake_input(status=0b00000001)  # stopped
    window._poll_once()
    assert pump.writes[-1][6] == proto.unit_code("mL/min")
    assert pump.writes[-1][0] >> proto.DIRECTION_CCW & 1


def test_reconnecting_sends_them_again(window, monkeypatch):
    pump = FakePump(fake_input(status=0b10000001))
    connect_without_thread(window, pump, monkeypatch)
    window._poll_once()
    window.disconnect()
    window.output_data[6] = 0  # e.g. the pump was power-cycled meanwhile
    connect_without_thread(window, pump, monkeypatch)
    window._poll_once()
    assert pump.writes[-1][6] == proto.unit_code("mL/min")
