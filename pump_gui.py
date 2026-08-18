import sys
import os

# Ensure the working directory is the location of the script
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != script_dir:
    os.chdir(script_dir)

import threading
import time
import struct
import json
import shutil
import webbrowser
import csv

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QComboBox, QRadioButton, QSlider, QCheckBox, 
                             QTextEdit, QGroupBox, QMessageBox, QFileDialog,
                             QTabWidget, QDialog, QGridLayout, QButtonGroup,
                             QSizePolicy, QScrollArea, QListWidget, QListWidgetItem, QAbstractItemView,
                             QFormLayout, QInputDialog, QToolButton)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QFont, QColor, QIcon

import qdarktheme

try:
    from pycomm3 import LogixDriver, CIPDriver
    from pycomm3.exceptions import PycommError
    # Minimal EtherNet/IP driver bypassing strict identity handshakes
    class PumpDriver(LogixDriver):
        def _initialize_driver(self, *args, **kwargs):
            # Bypass strict Rockwell PLC identity checks that crash on MasterFlex pumps
            pass
        def get_plc_info(self) -> dict:
            return {'product_name': 'Unknown Masterflex Pump'}
    PYCOMM3_AVAILABLE = True
except ImportError:
    PYCOMM3_AVAILABLE = False

# --- Configuration ---
INPUT_TAG = 'Input'   # 56 bytes input data
OUTPUT_TAG = 'Output' # 28 bytes output data
MASTERFLEX_ORANGE = "#F04E23"

FLOW_UNITS = {
    0: "L/S", 1: "mL/min", 2: "mL/hr", 3: "L/min", 4: "L/hr",
    5: "L/day", 6: "uL/min", 7: "uL/hr", 8: "gal/min", 9: "gal/hr",
    10: "gal/day", 11: "oz/min", 12: "oz/hr", 13: "cum/hr", 14: "RPM", 15: "%"
}

TUBE_CODES_MM = {
    1: 0.13, 2: 0.19, 3: 0.25, 4: 0.38, 5: 0.44, 6: 0.51, 7: 0.57,
    8: 0.64, 9: 0.76, 10: 0.89, 11: 0.95, 12: 1.02, 13: 1.09, 14: 1.14,
    15: 1.22, 16: 1.33, 17: 1.42, 18: 1.52, 19: 1.65, 20: 1.75, 21: 1.85,
    22: 2.06, 23: 2.29, 24: 2.54, 25: 2.79, 26: 3.17
}

class CollapsibleBox(QWidget):
    def __init__(self, title="", parent=None, expanded=True):
        super().__init__(parent)
        self.toggle_button = QToolButton(checkable=True, checked=expanded)
        self.title_text = title
        self.toggle_button.setStyleSheet("QToolButton { border: none; font-weight: bold; text-align: left; padding: 5px; background-color: #333; color: white; border-radius: 3px; margin-bottom: 2px; } QToolButton:hover { background-color: #444; }")
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
        self.save_btn.setStyleSheet(f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;")
        self.save_btn.clicked.connect(self.on_save)
        hw_layout.addWidget(self.save_btn, 1, 0, 1, 2)

        self.open_log_btn = QPushButton("Open CSV Log")
        self.open_log_btn.clicked.connect(self.on_open_log)
        hw_layout.addWidget(self.open_log_btn, 2, 0, 1, 2)
        
        self.use_icons_checkbox = QCheckBox("Use Icons for Buttons")
        self.use_icons_checkbox.setChecked(parent.config_data.get("use_icons", True))
        self.use_icons_checkbox.toggled.connect(self.on_toggle_icons)
        hw_layout.addWidget(self.use_icons_checkbox, 3, 0, 1, 2)
        
        self.restart_btn = QPushButton("Restart Application")
        self.restart_btn.clicked.connect(parent.cmd_restart_app)
        hw_layout.addWidget(self.restart_btn, 4, 0, 1, 2)
        
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
        check_btn.clicked.connect(lambda: webbrowser.open("https://www.masterflex.com/support/firmware-updates"))
        fw_layout.addWidget(check_btn)

        create_drive_btn = QPushButton("2. Create Update USB Drive")
        create_drive_btn.setStyleSheet(f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;")
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
        if os.path.exists("run_log.csv"):
            if sys.platform == "win32":
                os.startfile("run_log.csv")
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", "run_log.csv"])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", "run_log.csv"])
        else:
            self.parent().log_error("run_log.csv does not exist yet.")

    def on_create_update_drive(self):
        firmware_path, _ = QFileDialog.getOpenFileName(self, "Select Masterflex Firmware Update File")
        if not firmware_path: return
            
        usb_path = QFileDialog.getExistingDirectory(self, "Select Target USB Flash Drive")
        if not usb_path: return
            
        try:
            filename = os.path.basename(firmware_path)
            dest = os.path.join(usb_path, filename)
            shutil.copy2(firmware_path, dest)
            self.parent().log_msg(f"Firmware copied successfully to {dest}")
            
            QMessageBox.information(self, "Update Instructions",
                "USB Drive Created Successfully!\n\n"
                "Please follow these exact steps on your physical pump:\n"
                "1. Insert the USB drive into the pump drive's back USB port.\n"
                "2. Tap SETTINGS from any of the mode screens on the touchscreen.\n"
                "3. Tap DEVICE INFORMATION.\n"
                "4. Tap CHECK FOR UPDATES and follow the onscreen prompts."
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

        # Data arrays
        self.output_data = bytearray(28)
        self.input_data = bytearray(56)

        # Settings
        self.config_file = "pump_config.json"
        self.config_data = {}
        self.hardware_max_rpm = 160.0
        self.load_settings()

        self.signals = SignalManager()
        self.signals.log_msg_signal.connect(self.log_msg_ui)
        self.signals.log_error_signal.connect(self.log_error_ui)
        self.signals.discovery_found_signal.connect(self.set_ip_entry)
        self.signals.discovery_failed_signal.connect(self.reset_discover_btn)

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
                with open(self.config_file, "r") as f:
                    self.config_data = json.load(f)
            except Exception:
                pass
        self.hardware_max_rpm = self.config_data.get("max_rpm", 160.0)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # ---- LEFT PANEL ----
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(450)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        left_widget = QWidget()
        self.left_panel = QVBoxLayout(left_widget)
        scroll_area.setWidget(left_widget)
        main_layout.addWidget(scroll_area)

        # 1. Connection Frame
        conn_group = CollapsibleBox("Connection")
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
        self.connect_btn.setStyleSheet(f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn)

        self.settings_btn = QPushButton("⚙ Hardware Settings")
        self.settings_btn.clicked.connect(self.cmd_open_settings)
        conn_layout.addWidget(self.settings_btn)
        
        self.left_panel.addWidget(conn_group)

        # 2. Controls Frame
        controls_group = CollapsibleBox("Operational Controls")
        controls_layout = QGridLayout(controls_group.content_area)
        
        self.start_btn = QPushButton("Start / Run")
        self.start_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        self.start_btn.clicked.connect(self.cmd_start)
        controls_layout.addWidget(self.start_btn, 0, 0)

        self.stop_btn = QPushButton("Stop / Pause")
        self.stop_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold;")
        self.stop_btn.clicked.connect(self.cmd_stop)
        controls_layout.addWidget(self.stop_btn, 0, 1)

        self.remote_btn = QPushButton("Enable Remote")
        self.remote_btn.setStyleSheet("background-color: #007bff; color: white; font-weight: bold;")
        self.remote_btn.clicked.connect(self.cmd_remote_toggle)
        controls_layout.addWidget(self.remote_btn, 1, 0, 1, 2)

        self.dir_checkbox = QCheckBox("Direction (CCW)")
        self.dir_checkbox.setChecked(True)
        self.dir_checkbox.stateChanged.connect(self.cmd_update_direction)
        controls_layout.addWidget(self.dir_checkbox, 2, 0, 1, 2)

        self.mode_group = QButtonGroup(self)
        self.mode_radio0 = QRadioButton("Continuous")
        self.mode_radio1 = QRadioButton("Time")
        self.mode_radio2 = QRadioButton("Volume")
        
        self.mode_radio0.setChecked(True)
        self.mode_group.addButton(self.mode_radio0, 0)
        self.mode_group.addButton(self.mode_radio1, 1)
        self.mode_group.addButton(self.mode_radio2, 2)
        
        self.mode_group.idClicked.connect(self.cmd_update_mode)

        controls_layout.addWidget(QLabel("Operation Mode:"), 3, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio0, 4, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio1, 5, 0, 1, 2)
        controls_layout.addWidget(self.mode_radio2, 6, 0, 1, 2)

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

        self.apply_params_btn = QPushButton("Apply Parameters")
        self.apply_params_btn.setStyleSheet(f"background-color: {MASTERFLEX_ORANGE}; color: white; font-weight: bold;")
        self.apply_params_btn.clicked.connect(self.cmd_apply_params)

        self.left_panel.addWidget(params_group)
        self.left_panel.addStretch()

        # ---- RIGHT PANEL ----
        right_panel = QVBoxLayout()
        main_layout.addLayout(right_panel, 1)

        # 1. Real-Time Monitor
        monitor_group = CollapsibleBox("Real-Time Feedback")
        monitor_layout = QVBoxLayout(monitor_group.content_area)
        self.monitor_list = QListWidget()
        self.monitor_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.monitor_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.monitor_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.monitor_list.setStyleSheet("QListWidget::item { border-bottom: 1px solid #444; padding: 5px; } QListWidget::item:selected { background: transparent; color: inherit; border-bottom: 1px solid #444; } QListWidget { border: none; background: transparent; }")
        
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

        self.lbl_mon_calctime = QLabel("Calc. Time\n0.00 min")
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

        self.lbl_mon_rpm = QLabel("RPM\n0.0")
        self.lbl_mon_rpm.setFont(font_mon)
        self.lbl_mon_rpm.setStyleSheet(f"color: {MASTERFLEX_ORANGE};")
        self.lbl_mon_rpm.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.monitor_items = {
            "flow": self.lbl_mon_flow,
            "vol": vol_widget,
            "calc_time": self.lbl_mon_calctime,
            "rpm": self.lbl_mon_rpm,
            "batch": batch_widget
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
        self.run_log_textbox = QTextEdit()
        self.run_log_textbox.setReadOnly(True)
        logs_layout.addWidget(self.run_log_textbox, 1)

        # 4. Experimental Notes
        notes_group = CollapsibleBox("Experimental Notes", expanded=False)
        notes_layout = QGridLayout(notes_group.content_area)
        
        notes_controls = QVBoxLayout()
        self.open_log_btn = QPushButton("Open Log Folder")
        self.open_log_btn.clicked.connect(self.cmd_open_log_folder)
        notes_controls.addWidget(self.open_log_btn)
        
        self.auto_log_cb = QCheckBox("Auto-Log Runs")
        self.auto_log_cb.setChecked(True)
        notes_controls.addWidget(self.auto_log_cb)
        notes_controls.addStretch()
        
        notes_layout.addLayout(notes_controls, 0, 0, 2, 1)

        self.notes_entry = QTextEdit()
        self.notes_entry.setMaximumHeight(100)
        notes_layout.addWidget(self.notes_entry, 0, 1)

        # Metadata Tokens
        self.gb_tokens = CollapsibleBox("Metadata Tokens", expanded=False)
        self.tokens_outer_layout = QVBoxLayout(self.gb_tokens.content_area)
        
        self.tokens_list = QListWidget()
        self.tokens_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tokens_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tokens_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tokens_list.setStyleSheet("QListWidget::item { border-bottom: 1px solid #444; padding: 2px; } QListWidget::item:selected { background: transparent; color: inherit; border-bottom: 1px solid #444; } QListWidget { border: none; background: transparent; }")
        
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
            saved_tokens = {
                "Column Name": "",
                "Material": "",
                "Flow rate": "",
                "Bed length": "",
                "Run #": ""
            }

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

    def update_parameter_visibility(self):
        # Clear layout safely
        while self.params_layout.count() > 1: # keep flow limits
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
        
        if mode == 1: # Time
            self.params_layout.addWidget(QLabel("On Time (sec):"), 4, 0)
            self.params_layout.addWidget(self.on_time_entry, 5, 0)
            self.params_layout.addWidget(QLabel("Off/Interval (sec):"), 4, 1)
            self.params_layout.addWidget(self.off_time_entry, 5, 1)
            self.params_layout.addWidget(QLabel("Batch Total:"), 6, 0)
            self.params_layout.addWidget(self.batch_entry, 7, 0)
            self.params_layout.addWidget(self.apply_params_btn, 8, 0, 1, 2)
        elif mode == 2: # Volume
            self.params_layout.addWidget(QLabel("Dispense Volume:"), 4, 0)
            self.params_layout.addWidget(self.volume_entry, 5, 0)
            self.params_layout.addWidget(QLabel("Off/Interval (sec):"), 4, 1)
            self.params_layout.addWidget(self.off_time_entry, 5, 1)
            self.params_layout.addWidget(QLabel("Batch Total:"), 6, 0)
            self.params_layout.addWidget(self.batch_entry, 7, 0)
            self.params_layout.addWidget(self.apply_params_btn, 8, 0, 1, 2)
        else: # Continuous
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
            if mode_id == 0: self.mode_radio0.setChecked(True)
            elif mode_id == 1: self.mode_radio1.setChecked(True)
            elif mode_id == 2: self.mode_radio2.setChecked(True)
        if "direction" in self.config_data:
            self.dir_checkbox.setChecked(self.config_data["direction"] == "CCW")
        if "unit" in self.config_data:
            self.unit_menu.setCurrentText(self.config_data["unit"])
        
        if "flow" in self.config_data: self.flow_entry.setText(self.config_data["flow"])
        if "vol" in self.config_data: self.volume_entry.setText(self.config_data["vol"])
        if "on_time" in self.config_data: self.on_time_entry.setText(self.config_data["on_time"])
        if "off_time" in self.config_data: self.off_time_entry.setText(self.config_data["off_time"])
        if "batch" in self.config_data: self.batch_entry.setText(self.config_data["batch"])
        if "notes" in self.config_data: self.notes_entry.setPlainText(self.config_data["notes"])
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
        
        if hasattr(self, 'token_inputs') and hasattr(self, 'get_token_order'):
            self.config_data["metadata_tokens"] = {k: self.token_inputs[k].text() for k in self.get_token_order() if k in self.token_inputs}
            
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
            self.add_custom_token_ui(name, "")

    def _sync_flow_rate_token(self, text):
        if hasattr(self, 'token_inputs'):
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
        if self.connected:
            self.toggle_connection()
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
        if self.connected:
            self.toggle_connection()
        from PyQt6.QtCore import QProcess
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def update_button_styles(self):
        use_icons = self.config_data.get("use_icons", True)
        
        self.discover_btn.setText("🔍" if use_icons else "Search Network")
        self.discover_btn.setToolTip("Search the network for Masterflex pumps" if use_icons else "")
        
        self.settings_btn.setText("⚙" if use_icons else "Hardware Settings")
        self.settings_btn.setToolTip("Open Hardware Settings" if use_icons else "")
        
        self.start_btn.setText("▶" if use_icons else "Start / Run")
        self.start_btn.setToolTip("Start or Run the pump" if use_icons else "")
        
        self.stop_btn.setText("⏹" if use_icons else "Stop / Pause")
        self.stop_btn.setToolTip("Stop or Pause the pump" if use_icons else "")
        
        self.remote_btn.setToolTip("Toggle Remote Mode" if use_icons else "")
        
        self.reset_vol_btn.setText("🔄" if use_icons else "Reset Vol")
        self.reset_vol_btn.setToolTip("Reset Cumulative Volume" if use_icons else "")
        
        self.reset_batch_btn.setText("🔄" if use_icons else "Reset Batch")
        self.reset_batch_btn.setToolTip("Reset Batch Count" if use_icons else "")


    def log_msg_ui(self, msg):
        self.console_textbox.append(f"[INFO] {msg}")

    def log_error_ui(self, msg):
        self.console_textbox.append(f"<span style='color:red;'>[ERROR] {msg}</span>")

    def log_msg(self, msg):
        self.signals.log_msg_signal.emit(msg)

    def log_error(self, msg):
        self.signals.log_error_signal.emit(msg)

    def set_ip_entry(self, ip):
        self.ip_entry.setText(ip)
        self.log_msg(f"IP address set to {ip}. Click Connect when ready.")

    def reset_discover_btn(self, msg=""):
        if msg: self.log_error(msg)
        self.discover_btn.setEnabled(True)
        self.discover_btn.setText("Search Network")

    def toggle_connection(self):
        if self.connected:
            self.polling = False
            self.connected = False
            self.status_label.setText("Status: Disconnected")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.connect_btn.setText("Connect")
            if self.plc:
                try: self.plc.close()
                except: pass
            self.log_msg("Disconnected.")
        else:
            target = self.ip_entry.text().strip()
            if not target:
                self.log_error("Please enter a connection target.")
                return
            try:
                self.plc = PumpDriver(target)
                self.plc.open()
                self.connected = True
                
                self.status_label.setText("Status: Connected (IP)")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.connect_btn.setText("Disconnect")
                self.log_msg("EtherNet/IP Connected successfully.")
                
                self.polling = True
                threading.Thread(target=self.poll_pump_data, daemon=True).start()
            except Exception as e:
                self.log_error(f"EtherNet/IP Error: {e}")

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
                prod_name = dev.get('product_name', '').lower()
                if 'reglo' in prod_name or 'masterflex' in prod_name or 'pump' in prod_name:
                    found_ip = dev.get('ip_address')
                    self.signals.log_msg_signal.emit(f"Found MasterFlex ({dev.get('product_name')}) at {found_ip}")
                    break
            
            if not found_ip and devices:
                found_ip = devices[0].get('ip_address')
                self.signals.log_msg_signal.emit(f"Found ENIP device at {found_ip} - assuming it is the pump.")

            if found_ip:
                self.signals.discovery_found_signal.emit(found_ip)
                self.signals.discovery_failed_signal.emit("")
            else:
                self.signals.discovery_failed_signal.emit("No EtherNet/IP devices discovered.")
        except Exception as e:
            self.signals.discovery_failed_signal.emit(f"Discovery failed: {e}")

    def flow_slider_event(self, value):
        self.flow_entry.setText(f"{value/100:.2f}")

    def cmd_start(self):
        self.cmd_apply_params()
        self.output_data[0] |= 0b00000001
        self.write_output_data()
        self.log_msg("Command: START")

    def cmd_stop(self):
        self.output_data[0] &= ~0b00000001
        self.write_output_data()
        self.log_msg("Command: STOP")

    def _safe_stop(self):
        if not self.connected: return
        self.cmd_stop()
        for _ in range(15):
            if len(self.input_data) >= 4:
                status_int = struct.unpack_from('<i', self.input_data, 0)[0]
                if not (status_int & 2) and not (status_int & 4):
                    break
            time.sleep(0.1)

    def _trigger_falling_edge(self, bit_pos, log_msg):
        # 1-to-0 transition: Set to 1, hold for 500ms, then drop to 0 to trigger falling edge.
        self.output_data[0] |= (1 << bit_pos)
        self.write_output_data()
        
        def finish_transition():
            if self.connected:
                self.output_data[0] &= ~(1 << bit_pos)
                self.write_output_data()
                if log_msg:
                    self.log_msg(log_msg)
                    
        QTimer.singleShot(500, finish_transition)

    def cmd_remote_toggle(self):
        self._trigger_falling_edge(2, "Command: TOGGLE REMOTE CONTROL")

    def cmd_reset_cumulative(self):
        self._trigger_falling_edge(3, "Command: RESET CUMULATIVE VOL")
        
    def cmd_reset_vol(self):
        self.cmd_reset_cumulative()
        
    def cmd_reset_batch(self):
        self._trigger_falling_edge(1, "Command: RESET BATCH / DISPENSE")

    def cmd_apply_params(self):
        try:
            flow_val = float(self.flow_entry.text())
            vol_val = float(self.volume_entry.text())
            on_val = float(self.on_time_entry.text())
            off_val = float(self.off_time_entry.text())
            batch_val = int(self.batch_entry.text())

            was_running = False
            if self.connected and (self.output_data[0] & 0b00000001):
                was_running = True
                self._safe_stop()

            struct.pack_into('<f', self.output_data, 8, flow_val)
            struct.pack_into('<f', self.output_data, 12, vol_val)
            struct.pack_into('<f', self.output_data, 16, on_val)
            struct.pack_into('<f', self.output_data, 20, off_val)
            struct.pack_into('<i', self.output_data, 24, batch_val)
            # The hardware does NOT reliably handle EIP target volumes.
            # Force hardware to always remain in Continuous mode (0) and let software handle Volume mode.
            self.output_data[4] = 0

            self.write_output_data()
            
            if was_running:
                time.sleep(0.1)
                self.output_data[0] |= 0b00000001
                self.write_output_data()
                
            self.log_msg("Parameters Applied (EtherNet/IP)")
        except ValueError:
            self.log_error("Invalid parameter entered. Check your numbers.")

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

    def write_run_log(self, ui_msg, csv_row=None):
        self.run_log_textbox.append(ui_msg)
        
        if csv_row:
            try:
                file_exists = os.path.exists("run_log.csv")
                with open("run_log.csv", "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        token_keys = self.get_token_order() if hasattr(self, 'get_token_order') else []
                        writer.writerow(["Date/Time", "Event", "Mode", "Flow Rate", "Other Info"] + token_keys)
                    writer.writerow(csv_row)
            except Exception as e:
                self.log_error(f"Failed to write to CSV: {e}")

    def log_started_run(self):
        mode = self.mode_group.checkedId()
        mode_str = ["Continuous", "Time", "Volume"][mode]
        set_flow = self.flow_entry.text()
        unit_str = self.unit_menu.currentText()
        notes = self.notes_entry.toPlainText().strip().replace("\n", "; ")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        notes_str = f" | Notes: {notes}" if notes else ""
        ui_msg = f"[{timestamp}] [START] Mode: {mode_str} | Flow: {set_flow} {unit_str}{notes_str}"
        
        csv_row = None
        if self.auto_log_cb.isChecked():
            csv_row = [timestamp, "START", mode_str, f"{set_flow} {unit_str}", f"Notes: {notes}" if notes else ""]
            if hasattr(self, 'get_token_order'):
                csv_row.extend([self.token_inputs[k].text() for k in self.get_token_order() if k in self.token_inputs])
        else:
            ui_msg += " (Not Saved to CSV)"
            
        self.write_run_log(ui_msg, csv_row)

    def log_finished_run(self, final_vol):
        vol_dispensed = final_vol - getattr(self, '_run_start_vol', final_vol)
        duration_sec = time.time() - getattr(self, '_run_start_time', time.time())
        mins, secs = divmod(int(duration_sec), 60)
        
        mode = self.mode_group.checkedId()
        mode_str = ["Continuous", "Time", "Volume"][mode]
        set_flow = self.flow_entry.text()
        unit_str = self.unit_menu.currentText()
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        vol_unit = unit_str.split('/')[0] if '/' in unit_str else unit_str

        ui_msg = f"[{timestamp}] [ END ] Mode: {mode_str} | Flow: {set_flow} {unit_str} | Dispensed: {vol_dispensed:.4f} {vol_unit} | Duration: {int(mins)}m {int(secs)}s"
        
        csv_row = None
        if self.auto_log_cb.isChecked():
            csv_row = [timestamp, "END", mode_str, f"{set_flow} {unit_str}", f"Dispensed: {vol_dispensed:.4f} {vol_unit}; Duration: {int(mins)}m {int(secs)}s"]
            if hasattr(self, 'get_token_order'):
                csv_row.extend([self.token_inputs[k].text() for k in self.get_token_order() if k in self.token_inputs])
        else:
            ui_msg += " (Not Saved to CSV)"
            
        self.write_run_log(ui_msg, csv_row)

    def cmd_update_direction(self):
        if self.connected:
            self._safe_stop()
        if self.dir_checkbox.isChecked():
            self.output_data[0] |= 0b01000000
            self.log_msg("Direction set to: CCW")
        else:
            self.output_data[0] &= ~0b01000000
            self.log_msg("Direction set to: CW")
        self.write_output_data()

    def cmd_update_unit(self, choice):
        unit_code = 0
        for k, v in FLOW_UNITS.items():
            if v == choice:
                unit_code = k
                break
        self.output_data[6] = unit_code
        self.write_output_data()
        self.log_msg(f"Unit updated to: {choice}")
        self.update_parameter_visibility()

    def cmd_update_mode(self):
        mode = self.mode_group.checkedId()
        self.update_parameter_visibility()
        
        if self.connected:
            self._safe_stop()
            
        # The hardware does NOT reliably handle EIP target volumes.
        # Force hardware to always remain in Continuous mode (0) and let software handle Volume mode.
        self.output_data[4] = 0
        
        if self.connected:
            self.write_output_data()
        self.log_msg(f"Mode set to: {mode}")

    def write_output_data(self):
        if not self.connected or not self.plc: return
        try:
            with self.plc_lock:
                self.plc.generic_message(
                    service=b'\x10', class_code=b'\x04',
                    instance=112, attribute=b'\x03',
                    request_data=bytes(self.output_data)
                )
        except Exception:
            pass

    def poll_pump_data(self):
        while self.polling and self.connected and self.plc:
            try:
                with self.plc_lock:
                    result = self.plc.generic_message(
                        service=b'\x0e', class_code=b'\x04',
                        instance=100, attribute=b'\x03'
                    )
                if result and result.value:
                    self.input_data = result.value
                    
                with self.plc_lock:
                    self.plc.generic_message(
                        service=b'\x10', class_code=b'\x04',
                        instance=112, attribute=b'\x03',
                        request_data=bytes(self.output_data)
                    )
            except Exception:
                pass
            time.sleep(0.1)

    def update_dashboard(self):
        if not self.connected or len(self.input_data) < 56:
            return
        
        status_int = struct.unpack_from('<i', self.input_data, 0)[0]
        status_ok = bool(status_int & 1)
        is_running = bool(status_int & 2)
        dispense_running = bool(status_int & 4)
        local_mode = not bool(status_int & 128)
        
        tube_code = self.input_data[5]
        
        cum_vol = struct.unpack_from('<f', self.input_data, 8)[0]
        batch_current = struct.unpack_from('<i', self.input_data, 24)[0]
        min_flow = struct.unpack_from('<f', self.input_data, 32)[0]
        cur_flow = struct.unpack_from('<f', self.input_data, 36)[0]
        max_flow = struct.unpack_from('<f', self.input_data, 40)[0]
        
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
        except: pass
        
        if cur_flow > 0:
            calc_time = cum_vol / cur_flow
        else:
            calc_time = 0.0
        
        self.lbl_mon_status.setText("Status OK: YES" if status_ok else "Status OK: NO")
        self.lbl_mon_status.setStyleSheet("color: green; font-weight: bold;" if status_ok else "color: red; font-weight: bold;")
        
        if is_running or dispense_running:
            self.running_indicator.setText("● Pump Running")
            self.running_indicator.setStyleSheet("color: green; font-weight: bold;")
            if not getattr(self, 'run_log_active', False):
                self.run_log_active = True
                self._run_start_time = time.time()
                self._run_start_vol = cum_vol
                self.log_started_run()
            else:
                mode = self.mode_group.checkedId()
                if mode == 2:  # Volume
                    try:
                        target_vol = float(self.volume_entry.text())
                        if target_vol > 0 and (cum_vol - self._run_start_vol) >= target_vol:
                            self.output_data[0] &= ~0b00000001
                            self.write_output_data()
                    except: pass
        else:
            self.running_indicator.setText("● Pump Stopped")
            self.running_indicator.setStyleSheet("color: red; font-weight: bold;")
            if getattr(self, 'run_log_active', False):
                self.run_log_active = False
                self.log_finished_run(cum_vol)
                if self.connected:
                    if self.output_data[0] & 0b00000001:
                        QTimer.singleShot(50, self.cmd_stop)

        self.remote_indicator.setText("Local Mode" if local_mode else "Remote Mode")
        self.remote_indicator.setStyleSheet("color: green; font-weight: bold;" if local_mode else "color: blue; font-weight: bold;")
        self.remote_btn.setText("Enable Remote" if local_mode else "Disable Remote")
        
        mm_size = TUBE_CODES_MM.get(tube_code, 0)
        if mm_size:
            self.tube_indicator.setText(f"Tube Code: {tube_code} ({mm_size} mm ID)")
            self.tube_indicator.setText(f"Tube Code {tube_code} ({mm_size} mm ID)")
        else:
            self.tube_indicator.setText(f"Tube Code {tube_code}")
        
        flow_unit_str = self.unit_menu.currentText()
        vol_unit_str = flow_unit_str.split('/')[0] if '/' in flow_unit_str else flow_unit_str
        self.lbl_mon_flow.setText(f"Flow Rate\n{cur_flow:.4f} {flow_unit_str}")
        self.lbl_mon_vol.setText(f"Cum. Volume\n{cum_vol:.4f} {vol_unit_str}")
        self.lbl_mon_calctime.setText(f"Calc. Time\n{calc_time:.2f} min")
        
        if batch_current == 0 and getattr(self, 'last_batch_current', 0) == 1:
            pass
        else:
            self.lbl_mon_batch.setText(f"Batch\n{batch_current}")
            
        max_rpm = self.hardware_max_rpm
        try:
            max_flow = float(self.config_data.get("max_flow", max_rpm)) 
        except:
            max_flow = max_rpm
            
        if max_flow > 0:
            est_rpm = (cur_flow / max_flow) * max_rpm
        else:
            est_rpm = 0.0
            
        self.lbl_mon_rpm.setText(f"RPM\n{est_rpm:.1f}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
    
    app.setWindowIcon(QIcon("Peristaltic pump icon multichannel.ico"))
    
    window = MasterflexPumpGUI()
    window.showMaximized()
    
    sys.exit(app.exec())
