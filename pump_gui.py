"""Masterflex REGLO pump controller: a PyQt6 GUI that drives the pump over EtherNet/IP."""

__version__ = "1.0.0"

import os
import sys

# --- Code vs data -----------------------------------------------------------
# Code lives in GitHub Projects/UAkron/<repo>; data (exports, backups, logs) lives
# in SyncThing. The app runs with the data folder as
# its working directory, so relative paths like "Data/" land there.
# Override with UAKRON_APP_DATA_DIR (this app) or UAKRON_DATA_DIR (data root).
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.argv[0] = os.path.abspath(sys.argv[0])  # keeps "Restart" working after chdir
DATA_DIR = os.environ.get("UAKRON_APP_DATA_DIR") or os.path.join(
    os.environ.get("UAKRON_DATA_DIR")
    or os.path.join(os.path.expanduser("~"), "SyncThing", "UAkron Playground"),
    "MasterFlex Pump",
)
os.makedirs(DATA_DIR, exist_ok=True)
os.chdir(DATA_DIR)
# Settings (config, secrets, ROIs) live in the app folder by default, gitignored.
# The "Settings Folder" option (settings_location.py) can point them at a synced
# folder instead, e.g. "Settings" inside the data folder.
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
import dispense
import protocol as proto
import runlog
import settings_location

APP_DIR = settings_location.app_folder(script_dir)
CONFIG_DIR = settings_location.resolve(APP_DIR, DATA_DIR)
SETTINGS_FILES = ["pump_config.json"]
# Run logs are data: kept in Data/ inside the pump's data folder.
os.makedirs(os.path.join(DATA_DIR, "Data"), exist_ok=True)
RUN_LOG = os.path.join(DATA_DIR, "Data", "run_log.csv")
RUN_LOG_BACKUP = os.path.join(DATA_DIR, "Data", "run_log_backup.csv")

import json
import shutil
import threading
import time
import webbrowser

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# isort: split
# Import qdarktheme after PyQt6 so it picks up the same Qt binding.
import qdarktheme

try:
    from pycomm3 import CIPDriver, LogixDriver

    # Minimal EtherNet/IP driver bypassing strict identity handshakes
    class PumpDriver(LogixDriver):
        def _initialize_driver(self, *args, **kwargs):
            # Bypass strict Rockwell PLC identity checks that crash on MasterFlex pumps
            pass

        def get_plc_info(self) -> dict:
            return {"product_name": "Unknown Masterflex Pump"}

    PYCOMM3_AVAILABLE = True
except ImportError:
    PYCOMM3_AVAILABLE = False

MASTERFLEX_ORANGE = "#F04E23"
FLOW_UNITS = proto.FLOW_UNITS
TUBE_CODES_MM = proto.TUBE_CODES_MM


class CollapsibleBox(QWidget):
    def __init__(self, title="", parent=None, expanded=True):
        super().__init__(parent)
        self.toggle_button = QToolButton(checkable=True, checked=expanded)
        self.title_text = title
        self.toggle_button.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; text-align: left; padding: 5px; background-color: #333; color: white; border-radius: 3px; margin-bottom: 2px; } QToolButton:hover { background-color: #444; }"
        )
        self.toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_button.clicked.connect(self.on_toggle)

        self.content_area = QWidget()
        self.content_area.setVisible(expanded)
        self.on_toggle(expanded)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

    def on_toggle(self, checked):
        self.toggle_button.setText(f"▼ {self.title_text}" if checked else f"▶ {self.title_text}")
        self.content_area.setVisible(checked)


class SignalManager(QObject):
    log_msg_signal = pyqtSignal(str)
    log_error_signal = pyqtSignal(str)
    discovery_found_signal = pyqtSignal(str)
    discovery_failed_signal = pyqtSignal(str)
    link_state_signal = pyqtSignal(bool, str)  # (ok, error) when pump communication fails or recovers
    connect_result_signal = pyqtSignal(object, str)  # (driver or None, error) from the connect thread


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Documentation")
        self.resize(500, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)

        self.tabview = QTabWidget()
        layout.addWidget(self.tabview)

        # Hardware Tab
        hw_tab = QWidget()
        hw_layout = QGridLayout(hw_tab)

        hw_layout.addWidget(QLabel("Max Drive RPM:"), 0, 0)
        self.rpm_entry = QLineEdit()
        self.rpm_entry.setText(str(parent.hardware_max_rpm))
        hw_layout.addWidget(self.rpm_entry, 0, 1)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet(
            f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;"
        )
        self.save_btn.clicked.connect(self.on_save)
        hw_layout.addWidget(self.save_btn, 1, 0, 1, 2)

        self.open_log_btn = QPushButton("Open CSV Log")
        self.open_log_btn.clicked.connect(self.on_open_log)
        hw_layout.addWidget(self.open_log_btn, 2, 0, 1, 2)

        self.use_icons_checkbox = QCheckBox("Use Icons for Buttons")
        self.use_icons_checkbox.setChecked(parent.config_data.get("use_icons", True))
        self.use_icons_checkbox.toggled.connect(self.on_toggle_icons)
        hw_layout.addWidget(self.use_icons_checkbox, 3, 0, 1, 2)

        hw_layout.addWidget(
            settings_location.settings_folder_box(
                APP_DIR,
                DATA_DIR,
                SETTINGS_FILES,
                save_cb=parent.save_all_settings,
                restart_cb=parent.cmd_restart_app,
            ),
            4,
            0,
            1,
            2,
        )
        self.restart_btn = QPushButton("Restart Application")
        self.restart_btn.clicked.connect(parent.cmd_restart_app)
        hw_layout.addWidget(self.restart_btn, 5, 0, 1, 2)

        self.tabview.addTab(hw_tab, "Hardware")

        # Firmware Tab
        fw_tab = QWidget()
        fw_layout = QVBoxLayout(fw_tab)

        lbl_title = QLabel("<b>Masterflex Firmware Update Utility</b>")
        lbl_desc = QLabel("Format a USB drive with the latest firmware to update your REGLO.")
        lbl_desc.setStyleSheet("color: grey;")

        fw_layout.addWidget(lbl_title)
        fw_layout.addWidget(lbl_desc)

        check_btn = QPushButton("1. Check for Latest Firmware")
        check_btn.clicked.connect(
            lambda: webbrowser.open("https://www.masterflex.com/support/firmware-updates")
        )
        fw_layout.addWidget(check_btn)

        create_drive_btn = QPushButton("2. Create Update USB Drive")
        create_drive_btn.setStyleSheet(
            f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;"
        )
        create_drive_btn.clicked.connect(self.on_create_update_drive)
        fw_layout.addWidget(create_drive_btn)

        fw_layout.addStretch()
        self.tabview.addTab(fw_tab, "Firmware")

        # Documentation Tab
        doc_tab = QWidget()
        doc_layout = QVBoxLayout(doc_tab)
        doc_text = (
            "Supported Models:\n"
            "• Masterflex REGLO Digital Pump Drive with Advanced Connectivity\n"
            "  (Models 78018-10, 78018-12, 78018-40, etc.)\n\n"
            "Connection Protocol: EtherNet/IP\n\n"
            "Unsupported Interfaces:\n"
            "• The REGLO USB Type-A port is exclusively for Firmware Updates.\n"
            "• It does NOT support RS-232 serial control over USB.\n"
            "• The generic masterflex-serial library for older L/S and I/P pumps "
            "is incompatible with the REGLO Advanced Connectivity series."
        )
        doc_lbl = QLabel(doc_text)
        doc_lbl.setWordWrap(True)
        doc_layout.addWidget(doc_lbl)
        doc_layout.addStretch()
        self.tabview.addTab(doc_tab, "Documentation")

    def on_toggle_icons(self, checked):
        self.parent().config_data["use_icons"] = checked
        self.parent().save_all_settings()
        self.parent().update_button_styles()

    def on_save(self):
        try:
            val = float(self.rpm_entry.text())
            self.parent().save_settings(val)
            self.accept()
        except ValueError:
            self.parent().log_error("Invalid Max RPM value.")

    def on_open_log(self):
        if os.path.exists(RUN_LOG):
            if sys.platform == "win32":
                os.startfile(RUN_LOG)
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", RUN_LOG])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", RUN_LOG])
        else:
            self.parent().log_error("run_log.csv does not exist yet.")

    def on_create_update_drive(self):
        firmware_path, _ = QFileDialog.getOpenFileName(self, "Select Masterflex Firmware Update File")
        if not firmware_path:
            return

        usb_path = QFileDialog.getExistingDirectory(self, "Select Target USB Flash Drive")
        if not usb_path:
            return

        try:
            filename = os.path.basename(firmware_path)
            dest = os.path.join(usb_path, filename)
            shutil.copy2(firmware_path, dest)
            self.parent().log_msg(f"Firmware copied successfully to {dest}")

            QMessageBox.information(
                self,
                "Update Instructions",
                "USB Drive Created Successfully!\n\n"
                "Please follow these exact steps on your physical pump:\n"
                "1. Insert the USB drive into the pump drive's back USB port.\n"
                "2. Tap SETTINGS from any of the mode screens on the touchscreen.\n"
                "3. Tap DEVICE INFORMATION.\n"
                "4. Tap CHECK FOR UPDATES and follow the onscreen prompts.",
            )
        except Exception as e:
            self.parent().log_error(f"Failed to copy firmware: {e}")
            QMessageBox.critical(self, "Error", f"Failed to create update drive: {e}")


class MasterflexPumpGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Masterflex REGLO Pump Control")
        self.resize(1000, 750)
        self.setMinimumSize(800, 600)

        # Connection State
        self.plc = None
        self.plc_lock = threading.Lock()
        self.connected = False
        self.polling = False
        self.link_ok = True  # False while the pump isn't answering (see _report_comm)
        self._comm_lock = threading.Lock()
        self._connecting = False
        # Guards output_data and the dispense program, which the UI and the comms thread share.
        self.ctrl_lock = threading.RLock()

        # Run tracking (updated by the dashboard)
        self.pump_running = False
        self.run_log_active = False
        self._last_cum_vol = 0.0
        self._run_start_time = self._run_start_vol = 0.0
        self._last_run_seconds = 0.0
        self._flow_limits = None  # (min, max) the pump reports for the current unit

        # Data arrays
        self.output_data = bytearray(proto.OUTPUT_SIZE)
        self.input_data = bytearray(proto.INPUT_SIZE)

        # Time/Volume programs run in software; the drive itself stays in continuous mode.
        self.dispense = dispense.DispenseController()

        # Settings
        self.config_file = os.path.join(CONFIG_DIR, "pump_config.json")
        self.config_data = {}
        self.hardware_max_rpm = 160.0
        self.load_settings()

        self.signals = SignalManager()
        self.signals.log_msg_signal.connect(self.log_msg_ui)
        self.signals.log_error_signal.connect(self.log_error_ui)
        self.signals.discovery_found_signal.connect(self.set_ip_entry)
        self.signals.discovery_failed_signal.connect(self.reset_discover_btn)
        self.signals.link_state_signal.connect(self.on_link_state)
        self.signals.connect_result_signal.connect(self.on_connect_result)

        self.setup_ui()

        # Update timer for UI
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_dashboard)
        self.timer.start(100)  # 100 ms

        if not PYCOMM3_AVAILABLE:
            self.log_error("pycomm3 missing! Please run: pip install pycomm3")

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file) as f:
                    self.config_data = json.load(f)
            except Exception:
                pass
        self.hardware_max_rpm = self.config_data.get("max_rpm", 160.0)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        # ---- TOP BAR ----
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addLayout(top_bar_layout)

        self.remote_btn = QPushButton("Enable Remote")
        self.remote_btn.setStyleSheet("background-color: #007bff; color: white; font-weight: bold;")
        self.remote_btn.clicked.connect(self.cmd_remote_toggle)
        top_bar_layout.addWidget(self.remote_btn)

        self.start_stop_btn = QPushButton("Start / Run")
        self.start_stop_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        self.start_stop_btn.clicked.connect(self.cmd_toggle_start_stop)
        top_bar_layout.addWidget(self.start_stop_btn)

        top_bar_layout.addStretch()

        self.settings_btn = QPushButton("⚙ Hardware Settings")
        self.settings_btn.clicked.connect(self.cmd_open_settings)
        top_bar_layout.addWidget(self.settings_btn)

        self.restart_btn = QPushButton("Restart App")
        self.restart_btn.setStyleSheet("background-color: #6c757d; color: white; font-weight: bold;")
        self.restart_btn.clicked.connect(self.cmd_restart_app)
        top_bar_layout.addWidget(self.restart_btn)

        # ---- SPLIT LAYOUT ----
        split_layout = QHBoxLayout()
        main_layout.addLayout(split_layout, 1)

        # ---- LEFT PANEL ----
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(450)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        left_widget = QWidget()
        self.left_panel = QVBoxLayout(left_widget)
        scroll_area.setWidget(left_widget)
        split_layout.addWidget(scroll_area)

        # 1. System & Hardware Frame
        conn_group = CollapsibleBox("System & Hardware")
        conn_layout = QVBoxLayout(conn_group.content_area)

        self.logo_label = QLabel("MasterFlex\nController")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self.logo_label.setFont(font)
        self.logo_label.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        conn_layout.addWidget(self.logo_label)

        conn_layout.addWidget(QLabel("Connection Target:"))
        self.ip_entry = QLineEdit()
        self.ip_entry.setPlaceholderText("192.168.0.50")
        conn_layout.addWidget(self.ip_entry)

        self.discover_btn = QPushButton("Search Network")
        self.discover_btn.clicked.connect(self.cmd_discover)
        conn_layout.addWidget(self.discover_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet(
            f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;"
        )
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn)

        self.left_panel.addWidget(conn_group)

        # 2. Controls Frame
        controls_group = CollapsibleBox("Operational Controls")
        controls_layout = QGridLayout(controls_group.content_area)

        self.dir_checkbox = QCheckBox("Direction (CCW)")
        self.dir_checkbox.setChecked(True)
        self.dir_checkbox.stateChanged.connect(self.cmd_update_direction)
        controls_layout.addWidget(self.dir_checkbox, 0, 0, 1, 2)

        self.mode_group = QButtonGroup(self)
        self.mode_radio0 = QRadioButton("Continuous")
        self.mode_radio1 = QRadioButton("Time")
        self.mode_radio2 = QRadioButton("Volume")

        self.mode_radio0.setChecked(True)
        self.mode_group.addButton(self.mode_radio0, 0)
        self.mode_group.addButton(self.mode_radio1, 1)
        self.mode_group.addButton(self.mode_radio2, 2)

        self.mode_group.idClicked.connect(self.cmd_update_mode)

        controls_layout.addWidget(QLabel("Operation Mode:"), 1, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio0, 2, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio1, 3, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio2, 4, 0, 1, 2)

        self.left_panel.addWidget(controls_group)

        # 3. Parameter Settings Frame
        params_group = CollapsibleBox("Parameter Settings")
        self.params_layout = QGridLayout(params_group.content_area)

        self.flow_limits_label = QLabel("Calibrated Limits:\nMin: -- | Max: --")
        self.flow_limits_label.setStyleSheet("color: grey;")
        self.params_layout.addWidget(self.flow_limits_label, 0, 0, 1, 2)

        self.unit_menu = QComboBox()
        self.unit_menu.addItems(list(FLOW_UNITS.values()))
        self.unit_menu.setCurrentText("mL/min")
        self.unit_menu.currentTextChanged.connect(self.cmd_update_unit)
        self.flow_entry = QLineEdit("0.0")
        self.flow_entry.textChanged.connect(self._sync_flow_rate_token)
        self.flow_slider = QSlider(Qt.Orientation.Horizontal)
        self.flow_slider.setRange(0, 100)
        self.flow_slider.valueChanged.connect(self.flow_slider_event)

        self.on_time_entry = QLineEdit("0.0")
        self.off_time_entry = QLineEdit("0.0")
        self.volume_entry = QLineEdit("0.0")
        self.batch_entry = QLineEdit("1")

        self.lbl_est_time = QLabel("Est. Time: --")
        self.lbl_est_time.setStyleSheet("color: grey; font-weight: bold;")
        self.volume_entry.textChanged.connect(self.update_est_time)
        self.flow_entry.textChanged.connect(self.update_est_time)
        self.unit_menu.currentTextChanged.connect(self.update_est_time)

        self.apply_params_btn = QPushButton("Apply Parameters")
        self.apply_params_btn.setStyleSheet(
            f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;"
        )
        self.apply_params_btn.clicked.connect(self.cmd_apply_params)

        self.left_panel.addWidget(params_group)
        self.left_panel.addStretch()

        # ---- RIGHT PANEL ----
        right_panel = QVBoxLayout()
        split_layout.addLayout(right_panel, 1)

        # 1. Real-Time Monitor
        monitor_group = CollapsibleBox("Real-Time Feedback")
        monitor_layout = QVBoxLayout(monitor_group.content_area)
        self.monitor_list = QListWidget()
        self.monitor_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.monitor_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.monitor_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.monitor_list.setStyleSheet(
            "QListWidget::item { border-bottom: 1px solid #444; padding: 5px; } QListWidget::item:selected { background: transparent; color: inherit; border-bottom: 1px solid #444; } QListWidget { border: none; background: transparent; }"
        )

        # Connect drop event to save configuration
        self.monitor_list.model().rowsMoved.connect(self.save_monitor_order)

        font_mon = QFont()
        font_mon.setPointSize(16)
        font_mon.setBold(True)

        self.lbl_mon_flow = QLabel("Flow Rate\n0.0000")
        self.lbl_mon_flow.setFont(font_mon)
        self.lbl_mon_flow.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_flow.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_mon_vol = QLabel("Cum. Volume\n0.0000")
        self.lbl_mon_vol.setFont(font_mon)
        self.lbl_mon_vol.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_vol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reset_vol_btn = QPushButton("Reset Vol")
        self.reset_vol_btn.setMaximumWidth(120)
        self.reset_vol_btn.clicked.connect(self.cmd_reset_vol)
        vol_widget = QWidget()
        vol_layout = QVBoxLayout(vol_widget)
        vol_layout.setContentsMargins(0, 0, 0, 0)
        vol_layout.addWidget(self.lbl_mon_vol)
        vol_layout.addWidget(self.reset_vol_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_mon_calctime = QLabel("Run Time\n0:00")
        self.lbl_mon_calctime.setFont(font_mon)
        self.lbl_mon_calctime.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_calctime.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_mon_batch = QLabel("Batch\n0")
        self.lbl_mon_batch.setFont(font_mon)
        self.lbl_mon_batch.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_batch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reset_batch_btn = QPushButton("Reset Batch")
        self.reset_batch_btn.setMaximumWidth(120)
        self.reset_batch_btn.clicked.connect(self.cmd_reset_batch)
        batch_widget = QWidget()
        batch_layout = QVBoxLayout(batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.addWidget(self.lbl_mon_batch)
        batch_layout.addWidget(self.reset_batch_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_mon_rpm = QLabel("RPM (est.)\n0.0")
        self.lbl_mon_rpm.setFont(font_mon)
        self.lbl_mon_rpm.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_rpm.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.monitor_items = {
            "flow": self.lbl_mon_flow,
            "vol": vol_widget,
            "calc_time": self.lbl_mon_calctime,
            "rpm": self.lbl_mon_rpm,
            "batch": batch_widget,
        }

        default_order = ["flow", "vol", "calc_time", "rpm", "batch"]
        self.monitor_order = self.config_data.get("monitor_order", default_order)

        for key in default_order:
            if key not in self.monitor_order:
                self.monitor_order.append(key)

        for key in self.monitor_order:
            if key in self.monitor_items:
                widget = self.monitor_items[key]
                item = QListWidgetItem(self.monitor_list)
                item.setSizeHint(QSize(0, 90 if key in ["vol", "batch"] else 60))
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.monitor_list.addItem(item)
                self.monitor_list.setItemWidget(item, widget)

        monitor_layout.addWidget(self.monitor_list)

        top_right_layout = QHBoxLayout()
        right_panel.addLayout(top_right_layout, 1)

        top_right_layout.addWidget(monitor_group)

        logs_layout = QVBoxLayout()
        top_right_layout.addLayout(logs_layout, 1)

        # 2. Console Box
        lbl_console = QLabel("<b>System Event Log</b>")
        logs_layout.addWidget(lbl_console)
        self.console_textbox = QTextEdit()
        self.console_textbox.setReadOnly(True)
        self.console_textbox.setMaximumHeight(100)
        logs_layout.addWidget(self.console_textbox)
        self.log_msg_ui("Ready. Enter Target and Connect.")

        # 3. Run Logs
        lbl_run_log = QLabel("<b>Dispense Run History</b>")
        logs_layout.addWidget(lbl_run_log)

        self.run_log_list = QListWidget()
        self.run_log_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.run_log_list.setStyleSheet("QListWidget::item { padding: 4px; }")
        logs_layout.addWidget(self.run_log_list, 1)

        logs_btn_layout = QHBoxLayout()
        logs_layout.addLayout(logs_btn_layout)

        self.btn_save_selected_logs = QPushButton("Save Selected Logs")
        self.btn_save_selected_logs.clicked.connect(self.cmd_save_selected_logs)
        logs_btn_layout.addWidget(self.btn_save_selected_logs)

        self.btn_delete_selected_logs = QPushButton("Delete Selected")
        self.btn_delete_selected_logs.clicked.connect(self.cmd_delete_selected_logs)
        logs_btn_layout.addWidget(self.btn_delete_selected_logs)

        # 4. Experimental Notes
        notes_group = CollapsibleBox("Experimental Notes", expanded=True)
        notes_layout = QGridLayout(notes_group.content_area)

        notes_controls = QVBoxLayout()
        self.open_log_btn = QPushButton("Open Log Folder")
        self.open_log_btn.clicked.connect(self.cmd_open_log_folder)
        notes_controls.addWidget(self.open_log_btn)

        self.open_log_file_btn = QPushButton("Open Log File")
        self.open_log_file_btn.clicked.connect(self.cmd_open_log_file)
        notes_controls.addWidget(self.open_log_file_btn)

        self.auto_log_cb = QCheckBox("Auto-Log Runs")
        self.auto_log_cb.setChecked(False)
        notes_controls.addWidget(self.auto_log_cb)
        notes_controls.addStretch()

        notes_layout.addLayout(notes_controls, 0, 0, 2, 1)

        self.notes_entry = QTextEdit()
        self.notes_entry.setMaximumHeight(100)
        notes_layout.addWidget(self.notes_entry, 0, 1)

        # Metadata Tokens
        self.gb_tokens = CollapsibleBox("Metadata Tokens", expanded=True)
        self.tokens_outer_layout = QVBoxLayout(self.gb_tokens.content_area)

        self.tokens_list = QListWidget()
        self.tokens_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tokens_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tokens_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tokens_list.setStyleSheet(
            "QListWidget::item { border-bottom: 1px solid #444; padding: 2px; } QListWidget::item:selected { background: transparent; color: inherit; border-bottom: 1px solid #444; } QListWidget { border: none; background: transparent; }"
        )

        self.tokens_outer_layout.addWidget(self.tokens_list)

        self.btn_add_tab_token = QPushButton("+ Add Token")
        self.btn_add_tab_token.clicked.connect(self.request_add_custom_token)
        self.tokens_outer_layout.addWidget(self.btn_add_tab_token)

        self.token_inputs = {}
        notes_layout.addWidget(self.gb_tokens, 1, 1)
        notes_layout.setColumnStretch(1, 1)

        # Load tokens from config or inject defaults
        saved_tokens = self.config_data.get("metadata_tokens", {})
        if not saved_tokens:
            saved_tokens = {"Column Name": "", "Material": "", "Flow rate": "", "Bed length": "", "Run #": ""}

        for name, val in saved_tokens.items():
            self.add_custom_token_ui(name, val)

        right_panel.addWidget(notes_group)

        # 5. Status Indicators
        status_frame = QWidget()
        status_layout = QHBoxLayout(status_frame)

        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        status_layout.addWidget(self.status_label)

        self.lbl_mon_status = QLabel("Status OK: -")
        self.lbl_mon_status.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.lbl_mon_status)

        self.running_indicator = QLabel("● Stopped")
        self.running_indicator.setStyleSheet("color: grey; font-weight: bold;")
        status_layout.addWidget(self.running_indicator)

        self.remote_indicator = QLabel("Local Mode")
        self.remote_indicator.setStyleSheet("color: grey; font-weight: bold;")
        status_layout.addWidget(self.remote_indicator)

        self.tube_indicator = QLabel("Tube: --")
        self.tube_indicator.setStyleSheet("color: grey; font-weight: bold;")
        status_layout.addWidget(self.tube_indicator)

        right_panel.addWidget(status_frame)

        self.apply_loaded_settings()
        self.log_msg("Application started. Ready to connect.")

        # Auto-connect after 2 seconds if IP exists
        if self.ip_entry.text():
            QTimer.singleShot(2000, self.toggle_connection)
        self.update_parameter_visibility()
        self.load_run_logs()

    def update_parameter_visibility(self):
        # Clear layout safely
        while self.params_layout.count() > 1:  # keep flow limits
            item = self.params_layout.takeAt(1)
            if item.widget():
                item.widget().setParent(None)

        mode = self.mode_group.checkedId()

        # Base parameters always visible
        self.params_layout.addWidget(QLabel("Flow Units:"), 1, 0)
        self.params_layout.addWidget(self.unit_menu, 1, 1)
        self.params_layout.addWidget(QLabel("Flow Rate:"), 2, 0)
        self.params_layout.addWidget(self.flow_entry, 2, 1)
        self.params_layout.addWidget(self.flow_slider, 3, 0, 1, 2)

        if mode == 1:  # Time
            self.params_layout.addWidget(QLabel("On Time (sec):"), 4, 0)
            self.params_layout.addWidget(self.on_time_entry, 5, 0)
            self.params_layout.addWidget(QLabel("Off/Interval (sec):"), 4, 1)
            self.params_layout.addWidget(self.off_time_entry, 5, 1)
            self.params_layout.addWidget(QLabel("Batch Total:"), 6, 0)
            self.params_layout.addWidget(self.batch_entry, 7, 0)
            self.params_layout.addWidget(self.apply_params_btn, 8, 0, 1, 2)
        elif mode == 2:  # Volume
            self.params_layout.addWidget(QLabel("Dispense Volume:"), 4, 0)
            self.params_layout.addWidget(self.volume_entry, 5, 0)
            self.params_layout.addWidget(QLabel("Off/Interval (sec):"), 4, 1)
            self.params_layout.addWidget(self.off_time_entry, 5, 1)
            self.params_layout.addWidget(QLabel("Batch Total:"), 6, 0)
            self.params_layout.addWidget(self.batch_entry, 7, 0)
            self.params_layout.addWidget(self.lbl_est_time, 7, 1)
            self.params_layout.addWidget(self.apply_params_btn, 8, 0, 1, 2)
            self.update_est_time()
        else:  # Continuous
            self.params_layout.addWidget(self.apply_params_btn, 4, 0, 1, 2)

        if mode in [1, 2]:
            self.lbl_mon_batch.show()
            self.reset_batch_btn.show()
        else:
            self.lbl_mon_batch.hide()
            self.reset_batch_btn.hide()

    def apply_loaded_settings(self):
        if "ip" in self.config_data:
            self.ip_entry.setText(self.config_data["ip"])
        if "mode" in self.config_data:
            mode_id = self.config_data["mode"]
            if mode_id == 0:
                self.mode_radio0.setChecked(True)
            elif mode_id == 1:
                self.mode_radio1.setChecked(True)
            elif mode_id == 2:
                self.mode_radio2.setChecked(True)
        if "direction" in self.config_data:
            self.dir_checkbox.setChecked(self.config_data["direction"] == "CCW")
        if "unit" in self.config_data:
            self.unit_menu.setCurrentText(self.config_data["unit"])

        if "flow" in self.config_data:
            self.flow_entry.setText(self.config_data["flow"])
        if "vol" in self.config_data:
            self.volume_entry.setText(self.config_data["vol"])
        if "on_time" in self.config_data:
            self.on_time_entry.setText(self.config_data["on_time"])
        if "off_time" in self.config_data:
            self.off_time_entry.setText(self.config_data["off_time"])
        if "batch" in self.config_data:
            self.batch_entry.setText(self.config_data["batch"])
        if "notes" in self.config_data:
            self.notes_entry.setPlainText(self.config_data["notes"])
        self.update_button_styles()

    def save_all_settings(self):
        self.config_data["max_rpm"] = self.hardware_max_rpm
        self.config_data["ip"] = self.ip_entry.text()
        self.config_data["mode"] = self.mode_group.checkedId()
        self.config_data["direction"] = "CCW" if self.dir_checkbox.isChecked() else "CW"
        self.config_data["unit"] = self.unit_menu.currentText()
        self.config_data["flow"] = self.flow_entry.text()
        self.config_data["vol"] = self.volume_entry.text()
        self.config_data["on_time"] = self.on_time_entry.text()
        self.config_data["off_time"] = self.off_time_entry.text()
        self.config_data["batch"] = self.batch_entry.text()
        self.config_data["notes"] = self.notes_entry.toPlainText()

        if hasattr(self, "token_inputs") and hasattr(self, "get_token_order"):
            self.config_data["metadata_tokens"] = {
                k: self.token_inputs[k].text() for k in self.get_token_order() if k in self.token_inputs
            }

        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config_data, f)
        except Exception as e:
            print("Failed to save config:", e)

    def save_monitor_order(self):
        new_order = []
        for i in range(self.monitor_list.count()):
            item = self.monitor_list.item(i)
            new_order.append(item.data(Qt.ItemDataRole.UserRole))
        self.config_data["monitor_order"] = new_order
        self.save_all_settings()

    def request_add_custom_token(self):
        name, ok = QInputDialog.getText(self, "Add Custom Token", "Token Name:")
        if ok and name.strip():
            name = name.strip()
            if name in self.token_inputs:
                QMessageBox.warning(self, "Warning", "Token already exists!")
                return
            if name.casefold() in {col.casefold() for col in runlog.FIXED}:
                QMessageBox.warning(
                    self, "Warning", f"'{name}' is already a run log column. Pick another name."
                )
                return
            self.add_custom_token_ui(name, "")

    def _sync_flow_rate_token(self, text):
        if hasattr(self, "token_inputs"):
            for name, ent in self.token_inputs.items():
                if name.lower() == "flow rate":
                    ent.setText(text)

    def add_custom_token_ui(self, name, value):
        ent = QLineEdit(value)
        if name.lower() == "flow rate":
            ent.setEnabled(False)
            if not value:
                ent.setText(self.flow_entry.text())

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(name + ":")
        lbl.setMinimumWidth(80)
        row_layout.addWidget(lbl)
        row_layout.addWidget(ent)

        btn_del = QPushButton("-")
        btn_del.setFixedWidth(20)
        btn_del.clicked.connect(lambda _, n=name: self.remove_custom_token(n))
        row_layout.addWidget(btn_del)

        item = QListWidgetItem(self.tokens_list)
        item.setSizeHint(QSize(0, 40))
        item.setData(Qt.ItemDataRole.UserRole, name)

        self.tokens_list.addItem(item)
        self.tokens_list.setItemWidget(item, row_widget)
        self.token_inputs[name] = ent

    def remove_custom_token(self, name):
        if name in self.token_inputs:
            for i in range(self.tokens_list.count()):
                item = self.tokens_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == name:
                    self.tokens_list.takeItem(i)
                    break
            self.token_inputs.pop(name)

    def get_token_order(self):
        order = []
        for i in range(self.tokens_list.count()):
            item = self.tokens_list.item(i)
            order.append(item.data(Qt.ItemDataRole.UserRole))
        return order

    def closeEvent(self, event):
        self.save_all_settings()
        self.disconnect(reason="closed")
        event.accept()

    def save_settings(self, max_rpm):
        try:
            self.hardware_max_rpm = float(max_rpm)
            self.save_all_settings()
            self.log_msg(f"Hardware Settings saved! Max RPM: {self.hardware_max_rpm}")
        except ValueError:
            self.log_error("Invalid Max RPM value.")

    def cmd_open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def cmd_restart_app(self):
        self.save_all_settings()
        self.disconnect(reason="restarted")
        from PyQt6.QtCore import QProcess

        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def update_button_styles(self):
        use_icons = self.config_data.get("use_icons", True)

        self.discover_btn.setText("🔍" if use_icons else "Search Network")
        self.discover_btn.setToolTip("Search the network for Masterflex pumps" if use_icons else "")

        self.settings_btn.setText("⚙" if use_icons else "Hardware Settings")
        self.settings_btn.setToolTip("Open Hardware Settings" if use_icons else "")

        self.reset_vol_btn.setText("🔄" if use_icons else "Reset Vol")
        self.reset_vol_btn.setToolTip("Reset Cumulative Volume" if use_icons else "")

        self.reset_batch_btn.setText("🔄" if use_icons else "Reset Batch")
        self.reset_batch_btn.setToolTip("Reset Batch Count" if use_icons else "")

    def log_msg_ui(self, msg):
        cursor = self.console_textbox.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.console_textbox.setTextCursor(cursor)
        self.console_textbox.insertHtml(f"[INFO] {msg}<br>")
        self.console_textbox.moveCursor(QTextCursor.MoveOperation.Start)

    def log_error_ui(self, msg):
        cursor = self.console_textbox.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.console_textbox.setTextCursor(cursor)
        self.console_textbox.insertHtml(f"<span style='color:red;'>[ERROR] {msg}</span><br>")
        self.console_textbox.moveCursor(QTextCursor.MoveOperation.Start)

    def log_msg(self, msg):
        self.signals.log_msg_signal.emit(msg)

    def log_error(self, msg):
        self.signals.log_error_signal.emit(msg)

    def set_ip_entry(self, ip):
        self.ip_entry.setText(ip)
        self.log_msg(f"IP address set to {ip}. Click Connect when ready.")

    def reset_discover_btn(self, msg=""):
        if msg:
            self.log_error(msg)
        self.discover_btn.setEnabled(True)
        self.discover_btn.setText("Search Network")

    # --- Connecting -------------------------------------------------------------------

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        """Open the connection in a background thread so the window never freezes."""
        if self._connecting or self.connected:
            return
        target = self.ip_entry.text().strip()
        if not target:
            self.log_error("Please enter a connection target.")
            return
        if not PYCOMM3_AVAILABLE:
            self.log_error("pycomm3 missing! Please run: pip install pycomm3")
            return
        self._connecting = True
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")
        self.log_msg(f"Connecting to {target}...")
        threading.Thread(target=self._connect_worker, args=(target,), daemon=True).start()

    def _connect_worker(self, target):
        try:
            plc = PumpDriver(target)
            plc.open()
        except Exception as e:
            self.signals.connect_result_signal.emit(None, str(e) or type(e).__name__)
            return
        self.signals.connect_result_signal.emit(plc, "")

    def on_connect_result(self, plc, error):
        self._connecting = False
        self.connect_btn.setEnabled(True)
        if plc is None:
            self.connect_btn.setText("Connect")
            self.log_error(f"EtherNet/IP Error: {error}")
            return
        self.plc = plc
        self.link_ok = True
        self.connected = True
        self.status_label.setText("Status: Connected (IP)")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self.connect_btn.setText("Disconnect")
        self.log_msg("EtherNet/IP Connected successfully.")
        self.polling = True
        threading.Thread(target=self.poll_pump_data, daemon=True).start()

    def disconnect(self, reason="disconnected"):
        """Stop the pump if it's running, log the end of the run, then close the connection."""
        if not self.connected:
            return
        with self.ctrl_lock:
            was_on = proto.get_bit(self.output_data, proto.RUN)
            self.dispense.cancel()
            proto.set_bit(self.output_data, proto.RUN, False)
        if was_on or self.pump_running:
            error = self._send_output()  # tell the pump now, while the link is still open
            if error:
                self.log_error(
                    f"Couldn't send Stop before disconnecting ({error}). "
                    "In remote mode the pump stops by itself."
                )
            else:
                self.log_msg("Stopped the pump before disconnecting.")
        self.polling = False
        self.connected = False
        if self.run_log_active:
            self.run_log_active = False
            self.log_finished_run(self._last_cum_vol, note=f"app {reason} during the run")
        self.pump_running = False
        self.status_label.setText("Status: Disconnected")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.connect_btn.setText("Connect")
        if self.plc:
            try:
                with self.plc_lock:
                    self.plc.close()
            except Exception:
                pass
        self.log_msg("Disconnected.")

    def cmd_discover(self):
        if not PYCOMM3_AVAILABLE:
            self.log_error("pycomm3 missing! Cannot discover.")
            return

        self.log_msg("Searching network for MasterFlex Pump... (Please wait)")
        self.discover_btn.setEnabled(False)
        self.discover_btn.setText("Searching...")
        threading.Thread(target=self._run_discovery, daemon=True).start()

    def _run_discovery(self):
        try:
            devices = CIPDriver.discover()
            found_ip = None
            for dev in devices:
                prod_name = dev.get("product_name", "").lower()
                if "reglo" in prod_name or "masterflex" in prod_name or "pump" in prod_name:
                    found_ip = dev.get("ip_address")
                    self.signals.log_msg_signal.emit(
                        f"Found MasterFlex ({dev.get('product_name')}) at {found_ip}"
                    )
                    break

            if not found_ip and devices:
                found_ip = devices[0].get("ip_address")
                self.signals.log_msg_signal.emit(
                    f"Found ENIP device at {found_ip} - assuming it is the pump."
                )

            if found_ip:
                self.signals.discovery_found_signal.emit(found_ip)
                self.signals.discovery_failed_signal.emit("")
            else:
                self.signals.discovery_failed_signal.emit("No EtherNet/IP devices discovered.")
        except Exception as e:
            self.signals.discovery_failed_signal.emit(f"Discovery failed: {e}")

    def flow_slider_event(self, value):
        self.flow_entry.setText(f"{value / 100:.2f}")

    def cmd_toggle_start_stop(self):
        if self.pump_running or self.dispense.active:
            self.cmd_stop()
        else:
            self.cmd_start()

    def cmd_start(self):
        params = self.cmd_apply_params()
        if params is None or not self._arm_dispense(params):
            return
        with self.ctrl_lock:
            proto.set_bit(self.output_data, proto.RUN, True)
        self.write_output_data()
        self.log_msg("Command: START")

    def _arm_dispense(self, params):
        """Set up the software Time/Volume program for the selected mode. False if it can't run."""
        mode = self.mode_group.checkedId()
        with self.ctrl_lock:
            self.dispense.cancel()
            if mode not in (dispense.TIME, dispense.VOLUME):
                return True
            try:
                self.dispense.start(
                    mode,
                    on_time=params["on_time"],
                    volume=params["volume"],
                    off_time=params["off_time"],
                    batch_total=params["batch"],
                )
            except ValueError as e:
                self.log_error(f"Not started: {e}")
                return False
        what = f"{params['on_time']:g} s" if mode == dispense.TIME else f"{params['volume']:g} per dispense"
        repeats = params["batch"] or "unlimited"
        self.log_msg(f"Program: {what}, {params['off_time']:g} s pause, {repeats} dispense(s).")
        return True

    def cmd_stop(self):
        with self.ctrl_lock:
            self.dispense.cancel()
            proto.set_bit(self.output_data, proto.RUN, False)
        self.write_output_data()
        self.log_msg("Command: STOP")

    def _safe_stop(self):
        if not self.connected:
            return
        self.cmd_stop()
        for _ in range(15):
            if len(self.input_data) >= proto.INPUT_SIZE and not proto.decode_status(self.input_data).moving:
                break
            time.sleep(0.1)

    def _trigger_falling_edge(self, bit_pos, log_msg):
        # 1-to-0 transition: Set to 1, hold for 500ms, then drop to 0 to trigger falling edge.
        with self.ctrl_lock:
            proto.set_bit(self.output_data, bit_pos, True)
        self.write_output_data()

        def finish_transition():
            if self.connected:
                with self.ctrl_lock:
                    proto.set_bit(self.output_data, bit_pos, False)
                self.write_output_data()
                if log_msg:
                    self.log_msg(log_msg)

        QTimer.singleShot(500, finish_transition)

    def cmd_remote_toggle(self):
        self._trigger_falling_edge(proto.TOGGLE_REMOTE, "Command: TOGGLE REMOTE CONTROL")

    def cmd_reset_cumulative(self):
        self._trigger_falling_edge(proto.CLEAR_VOLUME, "Command: RESET CUMULATIVE VOL")

    def cmd_reset_vol(self):
        self.cmd_reset_cumulative()

    def cmd_reset_batch(self):
        with self.ctrl_lock:
            if not self.dispense.active:
                self.dispense.cancel()  # show the drive's own count again
        self._trigger_falling_edge(proto.RESET_DISPENSE, "Command: RESET BATCH / DISPENSE")

    def _read_parameters(self):
        """Parse and check the parameter boxes. Returns a dict, or None after logging why not."""
        try:
            params = dict(
                flow=float(self.flow_entry.text()),
                volume=float(self.volume_entry.text()),
                on_time=float(self.on_time_entry.text()),
                off_time=float(self.off_time_entry.text()),
                batch=int(self.batch_entry.text()),
            )
        except ValueError:
            self.log_error("Invalid parameter entered. Check your numbers.")
            return None
        problems = []
        flow = params["flow"]
        if flow <= 0:
            problems.append("Flow rate must be above 0.")
        elif self._flow_limits:
            lo, hi = self._flow_limits
            if not lo - 0.005 <= flow <= hi + 0.005:
                unit = self.unit_menu.currentText()
                problems.append(
                    f"Flow rate {flow:g} is outside the pump's calibrated range ({lo:.2f} to {hi:.2f} {unit})."
                )
        for key, label in (
            ("volume", "Dispense Volume"),
            ("on_time", "On Time"),
            ("off_time", "Off/Interval"),
        ):
            if params[key] < 0:
                problems.append(f"{label} can't be negative.")
        if params["batch"] < 0:
            problems.append("Batch Total can't be negative (0 means repeat until stopped).")
        if problems:
            self.log_error("Parameters not applied. " + " ".join(problems))
            return None
        return params

    def cmd_apply_params(self):
        """Send the parameters to the pump. Returns them as a dict, or None if they're invalid."""
        params = self._read_parameters()
        if params is None:
            return None

        was_running = self.connected and proto.get_bit(self.output_data, proto.RUN)
        if was_running:
            self._safe_stop()

        # The drive stays in continuous mode; Time and Volume run in software (dispense.py).
        with self.ctrl_lock:
            proto.pack_parameters(
                self.output_data,
                flow=params["flow"],
                volume=params["volume"],
                on_time=params["on_time"],
                off_time=params["off_time"],
                batch=params["batch"],
            )
        self.write_output_data()

        if was_running and self._arm_dispense(params):
            time.sleep(0.1)
            with self.ctrl_lock:
                proto.set_bit(self.output_data, proto.RUN, True)
            self.write_output_data()

        self.log_msg("Parameters Applied (EtherNet/IP)")
        return params

    def cmd_open_log_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(os.getcwd())
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", os.getcwd()])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", os.getcwd()])
        except Exception as e:
            self.log_error(f"Failed to open folder: {e}")

    def cmd_open_log_file(self):
        log_file = RUN_LOG
        if not os.path.exists(log_file):
            self.log_msg_ui("No run_log.csv found yet.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(log_file)
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", log_file])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", log_file])
        except Exception as e:
            self.log_error(f"Failed to open log file: {e}")

    # --- Run log ----------------------------------------------------------------------
    # Every START/END goes into the history list and run_log_backup.csv; it also goes into
    # run_log.csv when Auto-Log is on, or later with "Save Selected Logs". Rows are dicts
    # (runlog.FIXED columns + one per metadata token), so columns stay aligned in the files.

    def _token_values(self):
        values = {}
        for name in self.get_token_order():
            if name in self.token_inputs:
                column = f"{name} (token)" if name in runlog.FIXED else name
                values[column] = self.token_inputs[name].text()
        return values

    @staticmethod
    def _history_text(row):
        event = row.get("Event", "")
        event_str = event if len(event) >= 5 else event.center(5)
        text = f"[{row.get('Date/Time', '')}] [{event_str}] Mode: {row.get('Mode', '')} | Flow: {row.get('Flow Rate', '')}"
        if row.get("Other Info"):
            text += " | " + row["Other Info"].replace("; ", " | ")
        return text

    def _add_history_item(self, row, saved):
        item = QListWidgetItem(self._history_text(row) + ("" if saved else " (Not Saved to CSV)"))
        item.setData(Qt.ItemDataRole.UserRole, row)
        item.setForeground(QColor("white") if saved else QColor("red"))
        self.run_log_list.insertItem(0, item)

    def write_run_log(self, row):
        save = self.auto_log_cb.isChecked()
        self._add_history_item(row, save)
        self.run_log_list.scrollToTop()
        try:
            runlog.append(RUN_LOG_BACKUP, row)
        except Exception as e:
            self.log_error(f"Failed to write backup CSV: {e}")
        if save:
            try:
                runlog.append(RUN_LOG, row)
            except Exception as e:
                self.log_error(f"Failed to write to CSV: {e}")

    def cmd_save_selected_logs(self):
        selected = self.run_log_list.selectedItems()
        if not selected:
            self.log_msg_ui("No logs selected to save.")
            return
        # oldest first, so the file stays in time order
        selected.sort(key=lambda item: self.run_log_list.row(item), reverse=True)
        rows = [item.data(Qt.ItemDataRole.UserRole) for item in selected]
        rows = [row for row in rows if row]
        try:
            runlog.append(RUN_LOG, rows)
        except Exception as e:
            self.log_error(f"Failed to write selected logs to CSV: {e}")
            return
        for item in selected:
            if item.text().endswith(" (Not Saved to CSV)"):
                item.setText(item.text().replace(" (Not Saved to CSV)", " (Saved manually)"))
                item.setForeground(QColor("white"))
        self.log_msg_ui(f"Saved {len(rows)} selected logs to CSV.")
        self.run_log_list.clearSelection()

    def _confirm(self, title, text):
        """Ask a yes/no question (tests replace this)."""
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def cmd_delete_selected_logs(self):
        selected = self.run_log_list.selectedItems()
        if not selected:
            self.log_msg_ui("No logs selected to delete.")
            return
        if not self._confirm(
            "Delete runs",
            f"Remove {len(selected)} run(s) from the history and from run_log_backup.csv?\n\n"
            "Rows already saved in run_log.csv are kept. The previous backup file is kept as "
            "run_log_backup.csv.bak.",
        ):
            return
        for item in selected:
            self.run_log_list.takeItem(self.run_log_list.row(item))
        self.rewrite_backup_log()
        self.log_msg_ui(f"Deleted {len(selected)} selected logs.")

    def rewrite_backup_log(self):
        # The list shows newest first; the file is kept oldest first.
        rows = [
            self.run_log_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.run_log_list.count())
        ]
        try:
            runlog.rewrite(RUN_LOG_BACKUP, [row for row in reversed(rows) if row])
        except Exception as e:
            self.log_error(f"Failed to rewrite backup CSV: {e}")

    def load_run_logs(self):
        saved = set()
        try:
            saved = {runlog.key(row) for row in runlog.read(RUN_LOG)[1]}
        except Exception as e:
            self.log_error(f"Failed to read run_log.csv: {e}")
        try:
            rows = runlog.read(RUN_LOG_BACKUP)[1]
        except Exception as e:
            self.log_error(f"Failed to load backup logs: {e}")
            return
        for row in rows:
            self._add_history_item(row, runlog.key(row) in saved)
        self.run_log_list.scrollToTop()

    def _run_row(self, event, info):
        mode = self.mode_group.checkedId()
        row = {
            "Date/Time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "Event": event,
            "Mode": ["Continuous", "Time", "Volume"][mode],
            "Flow Rate": f"{self.flow_entry.text()} {self.unit_menu.currentText()}",
            "Other Info": info,
        }
        row.update(self._token_values())
        return row

    def log_started_run(self):
        notes = self.notes_entry.toPlainText().strip().replace("\n", "; ")
        self.write_run_log(self._run_row("START", f"Notes: {notes}" if notes else ""))

    def log_finished_run(self, final_vol, note=""):
        vol_dispensed = final_vol - self._run_start_vol
        duration_sec = time.time() - (self._run_start_time or time.time())
        self._last_run_seconds = duration_sec
        mins, secs = divmod(int(duration_sec), 60)
        vol_unit = proto.volume_unit(self.unit_menu.currentText())
        info = f"Dispensed: {vol_dispensed:.4f} {vol_unit}; Duration: {mins}m {secs}s"
        if note:
            info += f"; {note}"
        self.write_run_log(self._run_row("END", info))

    def cmd_update_direction(self):
        if self.connected:
            self._safe_stop()
        ccw = self.dir_checkbox.isChecked()
        with self.ctrl_lock:
            proto.set_bit(self.output_data, proto.DIRECTION_CCW, ccw)
        self.log_msg(f"Direction set to: {'CCW' if ccw else 'CW'}")
        self.write_output_data()

    def cmd_update_unit(self, choice):
        with self.ctrl_lock:
            self.output_data[6] = proto.unit_code(choice)
        self._flow_limits = None  # the pump reports new limits for the new unit
        self.write_output_data()
        self.log_msg(f"Unit updated to: {choice}")
        self.update_parameter_visibility()
        self.update_est_time()

    def update_est_time(self, *args):
        try:
            vol = float(self.volume_entry.text())
            flow = float(self.flow_entry.text())
            unit = self.unit_menu.currentText()

            if flow <= 0:
                self.lbl_est_time.setText("Est. Time: --")
                return

            if "/S" in unit or "/sec" in unit:
                time_in_sec = vol / flow
            elif "/min" in unit:
                time_in_sec = (vol / flow) * 60
            elif "/hr" in unit:
                time_in_sec = (vol / flow) * 3600
            elif "/day" in unit:
                time_in_sec = (vol / flow) * 86400
            elif unit == "RPM":
                time_in_sec = (vol / flow) * 60
            else:
                self.lbl_est_time.setText("Est. Time: --")
                return

            if time_in_sec < 60:
                self.lbl_est_time.setText(f"Est. Time: {time_in_sec:.1f} sec")
            elif time_in_sec < 3600:
                self.lbl_est_time.setText(f"Est. Time: {time_in_sec / 60:.2f} min")
            else:
                self.lbl_est_time.setText(f"Est. Time: {time_in_sec / 3600:.2f} hr")
        except:
            self.lbl_est_time.setText("Est. Time: --")

    def cmd_update_mode(self):
        mode = self.mode_group.checkedId()
        self.update_parameter_visibility()

        if self.connected:
            self._safe_stop()

        # The drive stays in continuous mode; Time and Volume run in software (dispense.py).
        with self.ctrl_lock:
            self.output_data[4] = proto.CONTINUOUS

        if self.connected:
            self.write_output_data()
        self.log_msg(f"Mode set to: {mode}")

    # --- Pump communication -------------------------------------------------------
    # pycomm3 raises on socket problems but only *reports* CIP errors in the returned
    # Tag, so both are checked. Problems are logged once when they start and once when
    # they clear (see _report_comm), not on every 100 ms cycle.

    def _send_output(self):
        """Write the 28-byte output assembly (instance 112). Returns "" or an error message."""
        with self.ctrl_lock:
            payload = bytes(self.output_data)
        try:
            with self.plc_lock:
                tag = self.plc.generic_message(
                    service=b"\x10",
                    class_code=b"\x04",
                    instance=proto.OUTPUT_INSTANCE,
                    attribute=b"\x03",
                    request_data=payload,
                )
        except Exception as e:
            return f"write failed: {e}"
        error = getattr(tag, "error", None)
        return f"write rejected: {error}" if error else ""

    def _read_input(self):
        """Read the 56-byte input assembly (instance 100). Returns "" or an error message."""
        try:
            with self.plc_lock:
                result = self.plc.generic_message(
                    service=b"\x0e", class_code=b"\x04", instance=proto.INPUT_INSTANCE, attribute=b"\x03"
                )
        except Exception as e:
            return f"read failed: {e}"
        if not result or not result.value:
            return f"read failed: {getattr(result, 'error', None) or 'no data'}"
        if len(result.value) < proto.INPUT_SIZE:
            return f"read returned {len(result.value)} bytes, expected 56"
        self.input_data = result.value
        return ""

    def _report_comm(self, error):
        """Track whether the pump is answering; signal the UI only when that changes."""
        ok = not error
        with self._comm_lock:
            if ok == self.link_ok:
                return
            self.link_ok = ok
        self.signals.link_state_signal.emit(ok, error)

    def on_link_state(self, ok, error):
        if not self.connected:
            return
        if ok:
            self.status_label.setText("Status: Connected (IP)")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.log_msg("Communication with the pump restored.")
        else:
            self.status_label.setText("Status: No response from pump")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.log_error(
                f"Lost communication with the pump ({error}). Retrying. "
                "In remote mode the pump stops by itself when it stops hearing from the app."
            )

    def write_output_data(self):
        if not self.connected or not self.plc:
            return
        error = self._send_output()
        if error:
            self._report_comm(error)

    def _run_program(self):
        """Advance a Time/Volume program from the latest status. Runs in the comms thread,
        so starts and stops don't depend on the window being responsive."""
        with self.ctrl_lock:
            if not self.dispense.active:
                return
            st = proto.decode_status(self.input_data)
            want = self.dispense.tick(time.monotonic(), st.cum_volume, st.moving)
            if want is not None:
                proto.set_bit(self.output_data, proto.RUN, want)
            event = self.dispense.take_event()
        if event:
            (self.log_msg if event.startswith("Program finished") else self.log_error)(event)

    def _poll_once(self):
        """One watchdog cycle: read the status, run the program, re-send the full output block."""
        read_error = self._read_input()
        if not read_error:
            self._run_program()
        write_error = self._send_output()
        self._report_comm(read_error or write_error)

    def poll_pump_data(self):
        while self.polling and self.connected and self.plc:
            self._poll_once()
            time.sleep(0.1)

    def update_dashboard(self):
        # While the pump isn't answering, input_data is stale: don't act on it.
        if not self.connected or not self.link_ok or len(self.input_data) < proto.INPUT_SIZE:
            return

        st = proto.decode_status(self.input_data)
        status_ok = st.ok
        is_running = st.running
        dispense_running = st.dispensing
        local_mode = not st.remote
        tube_code = st.tube_code
        cum_vol = st.cum_volume
        batch_current = st.batch
        min_flow = st.min_flow
        cur_flow = st.flow
        max_flow = st.max_flow

        try:
            self.flow_limits_label.setText(f"Calibrated Limits:\nMin: {min_flow:.2f} | Max: {max_flow:.2f}")
            if max_flow > min_flow:
                min_val = int(min_flow * 100)
                max_val = int(max_flow * 100)
                if self.flow_slider.minimum() != min_val or self.flow_slider.maximum() != max_val:
                    try:
                        intended_val = float(self.flow_entry.text()) * 100
                    except:
                        intended_val = self.flow_slider.value()
                    self.flow_slider.blockSignals(True)
                    self.flow_slider.setRange(min_val, max_val)
                    self.flow_slider.setValue(int(intended_val))
                    self.flow_slider.blockSignals(False)
        except:
            pass

        status_text = "Status OK: YES" if status_ok else "Status OK: NO"
        if st.head_open:
            status_text += " (head open)"
        self.lbl_mon_status.setText(status_text)
        self.lbl_mon_status.setStyleSheet(
            "color: green; font-weight: bold;" if status_ok else "color: red; font-weight: bold;"
        )

        self._last_cum_vol = cum_vol
        if max_flow > min_flow:
            self._flow_limits = (min_flow, max_flow)

        if is_running or dispense_running or self.dispense.active:
            self.start_stop_btn.setText("Stop / Pause")
            self.start_stop_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold;")
        else:
            self.start_stop_btn.setText("Start / Run")
            self.start_stop_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")

        if is_running or dispense_running:
            self.pump_running = True
            self.running_indicator.setText("● Pump Running")
            self.running_indicator.setStyleSheet("color: green; font-weight: bold;")
            if not self.run_log_active:
                self.run_log_active = True
                self._run_start_time = time.time()
                self._run_start_vol = cum_vol
                self.log_started_run()
        else:
            self.pump_running = False
            self.running_indicator.setText("● Pump Stopped")
            self.running_indicator.setStyleSheet("color: red; font-weight: bold;")
            if self.run_log_active:
                self.run_log_active = False
                self.log_finished_run(cum_vol)
                # Stopped from the touchscreen while the app still asks it to run: match it.
                # (A running program notices this itself, in _run_program.)
                if self.connected and not self.dispense.active:
                    if proto.get_bit(self.output_data, proto.RUN):
                        QTimer.singleShot(50, self.cmd_stop)

        self.remote_indicator.setText("Local Mode" if local_mode else "Remote Mode")
        self.remote_indicator.setStyleSheet(
            "color: green; font-weight: bold;" if local_mode else "color: #4da3ff; font-weight: bold;"
        )
        self.remote_btn.setText("Enable Remote" if local_mode else "Disable Remote")

        mm_size = TUBE_CODES_MM.get(tube_code, 0)
        if mm_size:
            self.tube_indicator.setText(f"Tube Code {tube_code} ({mm_size} mm ID)")
        else:
            self.tube_indicator.setText(f"Tube Code {tube_code}")

        flow_unit_str = self.unit_menu.currentText()
        vol_unit_str = proto.volume_unit(flow_unit_str)
        self.lbl_mon_flow.setText(f"Flow Rate\n{cur_flow:.4f} {flow_unit_str}")
        self.lbl_mon_vol.setText(f"Cum. Volume\n{cum_vol:.4f} {vol_unit_str}")
        self.lbl_mon_calctime.setText(self._run_time_text(cum_vol, cur_flow, flow_unit_str))

        if self.dispense.state != dispense.IDLE:
            self.lbl_mon_batch.setText(f"Batch\n{self.dispense.progress()}")
        else:
            self.lbl_mon_batch.setText(f"Batch\n{batch_current}")

        est_rpm = proto.estimate_rpm(cur_flow, flow_unit_str, max_flow, self.hardware_max_rpm)
        self.lbl_mon_rpm.setText(f"RPM (est.)\n{est_rpm:.1f}")

    def _run_time_text(self, cum_vol, cur_flow, unit):
        """'Run Time' tile: how long the current run has gone (or the last one went), and how
        long is left of the current Time/Volume dispense when that's known."""
        if self.run_log_active:
            text = "Run Time\n" + dispense.format_seconds(time.time() - self._run_start_time)
        else:
            text = "Last Run\n" + dispense.format_seconds(self._last_run_seconds)
        per = proto.unit_seconds(unit)
        with self.ctrl_lock:
            left = self.dispense.remaining(time.monotonic(), cum_vol, cur_flow / per if per else None)
        if left is not None:
            text += f" ({dispense.format_seconds(left)} left)"
        return text


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarktheme.load_stylesheet("dark"))

    app.setWindowIcon(QIcon(os.path.join(script_dir, "Peristaltic pump icon multichannel.ico")))

    window = MasterflexPumpGUI()
    window.showMaximized()

    sys.exit(app.exec())
