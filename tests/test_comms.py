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
