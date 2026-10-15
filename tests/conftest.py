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
