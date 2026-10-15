"""Software Time and Volume programs (dispense.py), and how the window uses them."""

import pytest
from conftest import fake_input

import dispense as d


def run(ctrl, steps):
    """Feed (now, cum_vol, running) steps; return the non-None run-bit requests as (now, bit)."""
    out = []
    for now, vol, running in steps:
        want = ctrl.tick(now, vol, running)
        if want is not None:
            out.append((now, want))
    return out


def test_time_mode_single_dispense_counts_from_actual_start():
    c = d.DispenseController()
    c.start(d.TIME, on_time=10, batch_total=1)
    # pump starts at t=2 (spin-up delay); it should stop at t>=12, not t>=10
    assert run(c, [(0, 0, False), (2, 0, True), (11.9, 0, True), (12.0, 0, True)]) == [(12.0, False)]
    assert c.state == d.DONE and c.progress() == "1/1"


def test_volume_mode_with_pauses_and_batches():
    c = d.DispenseController()
    c.start(d.VOLUME, volume=5, off_time=3, batch_total=2)
    steps = [
        (0, 100, True),  # running: count from 100
        (1, 104.9, True),
        (2, 105.0, True),  # 5 dispensed -> stop and pause
        (3, 105.2, False),
        (5, 105.2, False),  # 3 s pause over -> run again
        (6, 105.2, True),  # counting restarts at 105.2
        (7, 110.2, True),  # second dispense done -> finished
        (8, 110.3, False),
    ]
    assert run(c, steps) == [(2, False), (5, True), (7, False)]
    assert c.state == d.DONE and c.progress() == "2/2"


def test_zero_batch_repeats_until_cancelled_and_no_pause_keeps_running():
    c = d.DispenseController()
    c.start(d.TIME, on_time=1, off_time=0, batch_total=0)
    assert run(c, [(0, 0, True), (1, 0, True), (2, 0, True), (3, 0, True)]) == []
    assert c.batches_done == 3 and c.progress() == "3/∞" and c.active
    c.cancel()
    assert not c.active and run(c, [(9, 0, True)]) == []


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(mode=d.TIME, on_time=0), "On Time"),
        (dict(mode=d.VOLUME, volume=0), "Dispense Volume"),
        (dict(mode=d.TIME, on_time=1, off_time=-1), "negative"),
        (dict(mode=d.VOLUME, volume=1, batch_total=-2), "Batch Total"),
    ],
)
def test_invalid_programs_are_refused(kwargs, message):
    mode = kwargs.pop("mode")
    with pytest.raises(ValueError, match=message):
        d.DispenseController().start(mode, **kwargs)


# --- The window -----------------------------------------------------------------


def set_program(window, mode_radio, **fields):
    mode_radio.setChecked(True)
    for name, value in fields.items():
        getattr(window, f"{name}_entry").setText(str(value))


def step(window, pump, now, monkeypatch, **status):
    """One comms cycle at time ``now`` (the program runs in _poll_once), then a dashboard refresh."""
    pump.input_data = fake_input(**status)
    monkeypatch.setattr("pump_gui.time.monotonic", lambda: now)
    window._poll_once()
    window.update_dashboard()


def test_window_runs_a_time_program(connected, monkeypatch):
    window, pump = connected
    set_program(window, window.mode_radio1, flow=5, on_time=4, off_time=0, batch=1)
    window.cmd_start()
    assert window.output_data[0] & 1 and window.dispense.active

    step(window, pump, 100.0, monkeypatch, status=0b10000011, cum_vol=0.0)  # running
    step(window, pump, 103.9, monkeypatch, status=0b10000011, cum_vol=0.3)
    assert window.output_data[0] & 1
    step(window, pump, 104.0, monkeypatch, status=0b10000011, cum_vol=0.33)
    assert not window.output_data[0] & 1  # stopped after 4 s
    assert pump.writes[-1][0] & 1 == 0  # and the pump was told
    assert window.lbl_mon_batch.text() == "Batch\n1/1"
    assert "Program finished" in window.console_textbox.toPlainText()


def test_window_refuses_volume_mode_without_a_volume(connected):
    window, pump = connected
    set_program(window, window.mode_radio2, flow=5, volume=0, off_time=0, batch=1)
    window.cmd_start()
    assert not window.output_data[0] & 1
    assert "Volume mode needs a Dispense Volume" in window.console_textbox.toPlainText()


def test_stop_cancels_the_program(connected):
    window, pump = connected
    set_program(window, window.mode_radio2, flow=5, volume=10, off_time=2, batch=3)
    window.cmd_start()
    assert window.dispense.active
    window.cmd_stop()
    assert not window.dispense.active and not window.output_data[0] & 1


def test_continuous_mode_has_no_program(connected):
    window, pump = connected
    window.mode_radio0.setChecked(True)
    window.flow_entry.setText("5")
    window.cmd_start()
    assert window.output_data[0] & 1 and not window.dispense.active


def test_program_gives_up_if_pump_is_stopped_outside_the_app():
    c = d.DispenseController()
    c.start(d.TIME, on_time=60, batch_total=0)
    # running from t=0; stopped on the touchscreen at t=10 (after the 1 s settle time)
    steps = [(0, 0, True), (5, 0, True), (10, 0, False), (10.4, 0, False), (10.5, 0, False)]
    assert run(c, steps) == [(10.5, False)]
    assert c.state == d.IDLE and "stopped outside the app" in c.take_event()
    assert c.take_event() == ""  # events are handed out once


def test_brief_not_running_right_after_start_is_ignored():
    c = d.DispenseController()
    c.start(d.TIME, on_time=5)
    assert run(c, [(0, 0, True), (0.3, 0, False), (0.9, 0, False), (1.2, 0, True)]) == []
    assert c.state == d.DISPENSING


def test_program_gives_up_if_pump_never_starts():
    c = d.DispenseController()
    c.start(d.VOLUME, volume=5)
    assert run(c, [(0, 0, False), (4.9, 0, False), (5.0, 0, False)]) == [(5.0, False)]
    assert "didn't start" in c.take_event()


def test_remaining_time():
    c = d.DispenseController()
    c.start(d.TIME, on_time=30)
    assert c.remaining(0, 0) is None  # not dispensing yet
    c.tick(10, 0, True)
    assert c.remaining(25, 0) == 15
    v = d.DispenseController()
    v.start(d.VOLUME, volume=10)
    v.tick(0, 100, True)
    assert v.remaining(1, 104, flow_per_second=2) == 3
    assert v.remaining(1, 104) is None  # flow unknown


def test_window_drops_the_program_when_stopped_on_the_touchscreen(connected, monkeypatch):
    window, pump = connected
    set_program(window, window.mode_radio1, flow=5, on_time=60, off_time=5, batch=0)
    window.cmd_start()
    step(window, pump, 0.0, monkeypatch, status=0b10000011)
    step(window, pump, 5.0, monkeypatch, status=0b10000011)
    for t in (6.0, 6.3, 6.6):
        step(window, pump, t, monkeypatch, status=0b10000001)  # stopped, remote still on
    assert not window.dispense.active
    assert not window.output_data[0] & 1
    step(window, pump, 200.0, monkeypatch, status=0b10000001)
    assert not window.output_data[0] & 1  # never restarted
    assert "stopped outside the app" in window.console_textbox.toPlainText()


def test_format_seconds():
    assert d.format_seconds(0) == "0:00"
    assert d.format_seconds(75) == "1:15"
    assert d.format_seconds(3725) == "1:02:05"
    assert d.format_seconds(-3) == "0:00"
