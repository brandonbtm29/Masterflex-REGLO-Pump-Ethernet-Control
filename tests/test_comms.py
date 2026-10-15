"""Communication errors with the pump are reported instead of swallowed."""

from pycomm3.exceptions import CommError


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
    history = [window.run_log_list.item(i).text() for i in range(window.run_log_list.count())]
    assert "[ END ]" in history[0] and "app disconnected during the run" in history[0]
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
