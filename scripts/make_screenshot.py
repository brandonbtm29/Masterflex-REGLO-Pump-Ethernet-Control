"""Render the README screenshot (docs/screenshot.png) with sample data.

No pump is needed: the window is filled with a fake 56-byte input array, so the
picture shows the app as if it were connected and running. Nothing is sent over
the network, and the app's data folder is pointed at a temporary directory.

    python scripts/make_screenshot.py            # writes docs/screenshot.png
    QT_QPA_PLATFORM=offscreen python scripts/make_screenshot.py   # headless
"""

import os
import runpy
import struct
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "screenshot.png"


def fake_input(flow=5.0, cum_vol=18.75, running=True):
    """A 56-byte input assembly (instance 100) laid out as in the README byte map."""
    data = bytearray(56)
    status = 0b1 | 0b10000000  # Status OK + Remote Mode
    if running:
        status |= 0b10  # Pump Running
    struct.pack_into("<i", data, 0, status)
    data[4] = 0  # dispense mode: continuous (the app keeps the drive in continuous)
    data[5] = 18  # tube code 18 = 1.52 mm ID
    data[6] = 1  # mL/min
    struct.pack_into("<f", data, 8, cum_vol)
    struct.pack_into("<i", data, 24, 1)
    struct.pack_into("<f", data, 32, 0.02)
    struct.pack_into("<f", data, 36, flow)
    struct.pack_into("<f", data, 40, 14.69)
    return data


def main():
    tmp = tempfile.mkdtemp(prefix="reglo-screenshot-")
    os.environ["UAKRON_APP_DATA_DIR"] = tmp
    os.environ["UAKRON_SETTINGS_DIR"] = tmp  # start from defaults, never touch real settings
    sys.argv = [str(REPO / "pump_gui.py")]
    ns = runpy.run_path(str(REPO / "pump_gui.py"), run_name="screenshot")

    import qdarktheme
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
    app.setWindowIcon(QIcon(str(REPO / "assets" / "pump.png")))

    w = ns["MasterflexPumpGUI"]()
    w.resize(1280, 820)
    w.ip_entry.setText("192.0.2.10")  # documentation-only address (RFC 5737)
    w.mode_radio2.setChecked(True)
    w.update_parameter_visibility()
    w.flow_entry.setText("5")
    w.volume_entry.setText("50")
    for name, value in {
        "Column Name": "Demo column",
        "Material": "Sample media A",
        "Bed length": "10 cm",
        "Run #": "3",
    }.items():
        w.token_inputs[name].setText(value)
    w.notes_entry.setPlainText("Example run with sample values.")

    # Pretend to be connected; poll_pump_data never runs, so nothing touches the network.
    w.connected = True
    w.status_label.setText("Status: Connected (IP)")
    w.status_label.setStyleSheet("color: green; font-weight: bold;")
    w.connect_btn.setText("Disconnect")
    w.input_data = fake_input()
    w.show()
    for _ in range(5):
        w.update_dashboard()
        app.processEvents()

    OUT.parent.mkdir(exist_ok=True)
    w.grab().save(str(OUT))
    w.connected = False  # skip the disconnect path on close
    w.close()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
