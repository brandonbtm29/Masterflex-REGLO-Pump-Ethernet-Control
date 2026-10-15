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
