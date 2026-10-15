"""Shared test setup.

pump_gui.py changes into its data folder and creates folders there as soon as it
is imported, so both the data folder and the settings folder are pointed at a
temporary directory *before* the import. Qt runs headless. No pump is needed.
"""

import importlib
import os
import struct
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_TMP = tempfile.mkdtemp(prefix="reglo-tests-")
os.environ["UAKRON_APP_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["UAKRON_SETTINGS_DIR"] = os.path.join(_TMP, "settings")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(scope="session")
def pump_gui():
    return importlib.import_module("pump_gui")


@pytest.fixture(scope="session")
def qapp(pump_gui):
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(pump_gui, qapp):
    w = pump_gui.MasterflexPumpGUI()
    yield w
    w.connected = False  # never run the real disconnect path
    w.timer.stop()
    w.close()


def fake_input(*, status=0b10000011, tube=18, unit=1, cum_vol=18.75, batch=1, lo=0.02, flow=5.0, hi=14.69):
    """A 56-byte input assembly (instance 100) laid out as in the README byte map.

    Default status: OK + running + remote mode.
    """
    data = bytearray(56)
    struct.pack_into("<i", data, 0, status)
    data[5] = tube
    data[6] = unit
    struct.pack_into("<f", data, 8, cum_vol)
    struct.pack_into("<i", data, 24, batch)
    struct.pack_into("<f", data, 32, lo)
    struct.pack_into("<f", data, 36, flow)
    struct.pack_into("<f", data, 40, hi)
    return data


class FakePump:
    """Stands in for PumpDriver: answers generic_message like the REGLO, or fails on demand."""

    def __init__(self, input_data=None):
        from pycomm3 import Tag

        self._tag = Tag
        self.input_data = input_data if input_data is not None else fake_input()
        self.fail_with = None  # an exception to raise on every call
        self.write_error = None  # a CIP error string for writes
        self.writes = []

    def generic_message(self, service, class_code, instance, attribute=b"", request_data=b"", **kw):
        if self.fail_with:
            raise self.fail_with
        if service == b"\x0e":
            return self._tag("generic", bytes(self.input_data), None, None)
        self.writes.append(bytes(request_data))
        if self.write_error:
            return self._tag("generic", None, None, self.write_error)
        return self._tag("generic", b"", None, None)

    def close(self):
        pass


@pytest.fixture
def connected(window):
    """The window, 'connected' to a FakePump (no thread, no network)."""
    pump = FakePump()
    window.plc = pump
    window.connected = True
    window.link_ok = True
    window.status_label.setText("Status: Connected (IP)")
    return window, pump


class SimPump(FakePump):
    """A pump that actually 'runs': it pumps 0.1 mL/s (6 mL/min) while the run bit is set."""

    def __init__(self):
        super().__init__()
        import threading
        import time

        self._time = time.monotonic
        self._lock = threading.Lock()
        self.run = False
        self.volume = 0.0
        self._t = self._time()
        self.open = lambda: None

    def generic_message(self, service, class_code, instance, attribute=b"", request_data=b"", **kw):
        with self._lock:
            now = self._time()
            if self.run:
                self.volume += 0.1 * (now - self._t)
            self._t = now
            if service == b"\x10":
                self.run = bool(request_data[0] & 1)
            else:
                status = 0b10000011 if self.run else 0b10000001
                self.input_data = fake_input(
                    status=status, cum_vol=self.volume, flow=6.0 if self.run else 0.0
                )
        return super().generic_message(service, class_code, instance, attribute, request_data, **kw)
