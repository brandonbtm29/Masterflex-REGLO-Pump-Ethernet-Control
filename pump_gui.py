import customtkinter as ctk
import tkinter as tk
import threading
import time
import struct
import json
import os
import asyncio
from tkinter import filedialog, messagebox
import shutil
import webbrowser

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
# Update these tags if your pump uses different names or Generic CIP instances
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

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class MasterflexPumpGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Masterflex REGLO Pump Control")
        self.geometry("950x700")
        self.minsize(800, 600)

        # Connection State
        self.plc = None
        self.plc_lock = threading.Lock()
        self.serial_pump = None
        self.serial_loop = None
        self.serial_thread = None
        self.connection_type = ctk.StringVar(value="EtherNet/IP")
        self.connected = False
        self.polling = False

        # Data arrays
        self.output_data = bytearray(28)
        self.input_data = bytearray(56)

        # Settings
        self.config_file = "pump_config.json"
        self.hardware_max_rpm = 160.0
        self.load_settings()

        # Build UI
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        if not PYCOMM3_AVAILABLE:
            self.log_error("pycomm3 missing! Please run: pip install pycomm3")
        else:
            self.after(500, self.toggle_connection)


    def setup_ui(self):
        self.left_panel = ctk.CTkScrollableFrame(self, fg_color="transparent", width=340)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        
        self.right_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        
        self.grid_columnconfigure(0, weight=1, minsize=340)
        self.grid_columnconfigure(1, weight=3)

        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(2, weight=1) # Run log expands
        self.right_panel.grid_rowconfigure(3, weight=1) # Notes frame expands

        self.left_panel.grid_columnconfigure(0, weight=1)

        # ---- LEFT PANEL ----
        # 1. Connection Frame
        self.conn_frame = ctk.CTkFrame(self.left_panel)
        self.conn_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.conn_frame.grid_columnconfigure(0, weight=1)

        self.logo_label = ctk.CTkLabel(self.conn_frame, text="MasterFlex\nController", font=ctk.CTkFont(size=20, weight="bold"), text_color="#C03B18")
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.ip_label = ctk.CTkLabel(self.conn_frame, text="Connection Target:", text_color="grey")
        self.ip_label.grid(row=2, column=0, padx=20, pady=(10, 0), sticky="w")

        self.ip_entry = ctk.CTkEntry(self.conn_frame, placeholder_text="192.168.0.50")
        self.ip_entry.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.discover_btn = ctk.CTkButton(self.conn_frame, text="Search Network", command=self.cmd_discover, fg_color="gray", hover_color="darkgray")
        self.discover_btn.grid(row=4, column=0, padx=20, pady=(0, 10))

        self.connect_btn = ctk.CTkButton(self.conn_frame, text="Connect", command=self.toggle_connection, fg_color="#E04B18", hover_color="#C03B18")
        self.connect_btn.grid(row=5, column=0, padx=20, pady=10)

        self.settings_btn = ctk.CTkButton(self.conn_frame, text="⚙ Hardware Settings", command=self.cmd_open_settings, fg_color="gray", hover_color="darkgray")
        self.settings_btn.grid(row=6, column=0, padx=20, pady=(10, 20))

        # 2. Controls Frame
        self.controls_frame = ctk.CTkFrame(self.left_panel)
        self.controls_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.controls_frame.grid_columnconfigure((0, 1), weight=1)
        
        ctk.CTkLabel(self.controls_frame, text="Operational Controls", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10)

        self.start_btn = ctk.CTkButton(self.controls_frame, text="Start / Run", fg_color="green", hover_color="darkgreen", command=self.cmd_start)
        self.start_btn.grid(row=1, column=0, padx=10, pady=10)
        
        self.stop_btn = ctk.CTkButton(self.controls_frame, text="Stop / Pause", fg_color="red", hover_color="darkred", command=self.cmd_stop)
        self.stop_btn.grid(row=1, column=1, padx=10, pady=10)

        self.remote_btn = ctk.CTkButton(self.controls_frame, text="Enable Remote", fg_color="blue", hover_color="darkblue", command=self.cmd_remote_toggle)
        self.remote_btn.grid(row=2, column=0, columnspan=2, padx=10, pady=10)

        self.direction_var = ctk.StringVar(value="CCW")
        self.dir_switch = ctk.CTkSwitch(self.controls_frame, text="Direction (CW/CCW)", variable=self.direction_var, onvalue="CCW", offvalue="CW", command=self.cmd_update_direction, progress_color="#E04B18")
        self.dir_switch.grid(row=3, column=0, columnspan=2, padx=10, pady=10)

        self.mode_var = ctk.IntVar(value=0) # 0=CONT, 1=TIME, 2=VOL
        self.mode_label = ctk.CTkLabel(self.controls_frame, text="Operation Mode:")
        self.mode_label.grid(row=4, column=0, sticky="w", padx=10)
        
        self.mode_radio0 = ctk.CTkRadioButton(self.controls_frame, text="Continuous", variable=self.mode_var, value=0, command=self.cmd_update_mode)
        self.mode_radio0.grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.mode_radio1 = ctk.CTkRadioButton(self.controls_frame, text="Time", variable=self.mode_var, value=1, command=self.cmd_update_mode)
        self.mode_radio1.grid(row=6, column=0, padx=10, pady=5, sticky="w")
        self.mode_radio2 = ctk.CTkRadioButton(self.controls_frame, text="Volume", variable=self.mode_var, value=2, command=self.cmd_update_mode)
        self.mode_radio2.grid(row=7, column=0, padx=10, pady=5, sticky="w")

        # 3. Parameter Settings Frame
        self.params_frame = ctk.CTkFrame(self.left_panel)
        self.params_frame.grid(row=2, column=0, sticky="nsew")
        self.params_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(self.params_frame, text="Parameter Settings", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10)

        self.flow_limits_label = ctk.CTkLabel(self.params_frame, text="Calibrated Limits:\nMin: -- | Max: --", font=ctk.CTkFont(size=12), text_color="grey")
        self.flow_limits_label.grid(row=1, column=0, columnspan=2, pady=(0, 10))

        self.unit_label = ctk.CTkLabel(self.params_frame, text="Flow Units:")
        self.unit_var = ctk.StringVar(value="mL/min")
        self.unit_menu = ctk.CTkOptionMenu(self.params_frame, variable=self.unit_var, values=list(FLOW_UNITS.values()), command=self.cmd_update_unit)

        self.flow_label = ctk.CTkLabel(self.params_frame, text="Flow Rate:")
        self.flow_entry = ctk.CTkEntry(self.params_frame)
        self.flow_entry.insert(0, "0.0")
        self.flow_slider = ctk.CTkSlider(self.params_frame, from_=0, to=100, command=self.flow_slider_event, button_color="#E04B18", button_hover_color="#C03B18")
        self.flow_slider.set(0)

        self.on_time_label = ctk.CTkLabel(self.params_frame, text="On Time (sec):")
        self.on_time_entry = ctk.CTkEntry(self.params_frame)
        self.on_time_entry.insert(0, "0.0")

        self.off_time_label = ctk.CTkLabel(self.params_frame, text="Off/Interval (sec):")
        self.off_time_entry = ctk.CTkEntry(self.params_frame)
        self.off_time_entry.insert(0, "0.0")

        self.vol_label = ctk.CTkLabel(self.params_frame, text="Dispense Volume:")
        self.volume_entry = ctk.CTkEntry(self.params_frame)
        self.volume_entry.insert(0, "0.0")

        self.batch_label = ctk.CTkLabel(self.params_frame, text="Batch Total:")
        self.batch_entry = ctk.CTkEntry(self.params_frame)
        self.batch_entry.insert(0, "1")

        self.apply_params_btn = ctk.CTkButton(self.params_frame, text="Apply Parameters", command=self.cmd_apply_params, fg_color="#E04B18", hover_color="#C03B18")

        # ---- RIGHT PANEL ----
        # 1. Real-Time Monitor
        self.monitor_frame = ctk.CTkFrame(self.right_panel)
        self.monitor_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.monitor_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkLabel(self.monitor_frame, text="Real-Time Feedback", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=5, pady=10)

        self.lbl_mon_flow = ctk.CTkLabel(self.monitor_frame, text="Flow Rate:\n0.0000", font=ctk.CTkFont(size=18, weight="bold"), text_color="#E04B18")
        self.lbl_mon_flow.grid(row=1, column=0, pady=10)

        self.lbl_mon_vol = ctk.CTkLabel(self.monitor_frame, text="Cumulative Vol:\n0.0000", font=ctk.CTkFont(size=18, weight="bold"), text_color="#E04B18")
        self.lbl_mon_vol.grid(row=1, column=1, pady=10)
        
        self.reset_vol_btn = ctk.CTkButton(self.monitor_frame, text="Reset Vol", width=80, fg_color="gray", hover_color="darkgray", command=self.cmd_reset_vol)
        self.reset_vol_btn.grid(row=2, column=1, pady=(0, 10))

        self.lbl_mon_calctime = ctk.CTkLabel(self.monitor_frame, text="Calc. Time:\n0.00 min", font=ctk.CTkFont(size=18, weight="bold"), text_color="#E04B18")
        self.lbl_mon_calctime.grid(row=1, column=2, pady=10)

        self.lbl_mon_batch = ctk.CTkLabel(self.monitor_frame, text="Batch:\n0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#E04B18")

        self.reset_batch_btn = ctk.CTkButton(self.monitor_frame, text="Reset Batch", width=80, fg_color="gray", hover_color="darkgray", command=self.cmd_reset_batch)

        self.lbl_mon_rpm = ctk.CTkLabel(self.monitor_frame, text="Est. RPM:\n0.0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#E04B18")
        self.lbl_mon_rpm.grid(row=1, column=4, pady=10)

        # 2. Console Box
        self.console_textbox = ctk.CTkTextbox(self.right_panel, height=80)
        self.console_textbox.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.log_msg("Ready. Enter Target and Connect.")

        # 3. Run Logs
        self.run_log_textbox = ctk.CTkTextbox(self.right_panel)
        self.run_log_textbox.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        
        # 4. Experimental Notes
        self.notes_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.notes_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        self.notes_frame.grid_columnconfigure(1, weight=1)
        self.notes_frame.grid_rowconfigure(0, weight=1)

        self.notes_label = ctk.CTkLabel(self.notes_frame, text="Experimental Notes:")
        self.notes_label.grid(row=0, column=0, sticky="nw", padx=(0, 10))
        
        self.open_log_btn = ctk.CTkButton(self.notes_frame, text="Open Log Folder", width=120, command=self.cmd_open_log_folder)
        self.open_log_btn.grid(row=1, column=0, sticky="nw", pady=(5, 0))
        
        self.auto_log_var = ctk.BooleanVar(value=True)
        self.auto_log_switch = ctk.CTkSwitch(self.notes_frame, text="Auto-Log Runs", variable=self.auto_log_var)
        self.auto_log_switch.grid(row=2, column=0, sticky="nw", pady=(10, 0))
        
        self.notes_entry = ctk.CTkTextbox(self.notes_frame, height=120)
        self.notes_entry.grid(row=0, column=1, rowspan=3, sticky="nsew")

        self.console_textbox.bind("<Double-Button-1>", self.cmd_log_console_line)

        # 5. Status Indicators
        self.status_frame = ctk.CTkFrame(self.right_panel, height=40)
        self.status_frame.grid(row=4, column=0, sticky="ew")
        self.status_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.status_label = ctk.CTkLabel(self.status_frame, text="Status: Disconnected", text_color="red", font=ctk.CTkFont(weight="bold"))
        self.status_label.grid(row=0, column=0, pady=10)

        self.lbl_mon_status = ctk.CTkLabel(self.status_frame, text="Status OK: -", font=ctk.CTkFont(weight="bold"))
        self.lbl_mon_status.grid(row=0, column=1, pady=10)

        self.running_indicator = ctk.CTkLabel(self.status_frame, text="● Stopped", text_color="grey", font=ctk.CTkFont(weight="bold"))
        self.running_indicator.grid(row=0, column=2, pady=10)

        self.remote_indicator = ctk.CTkLabel(self.status_frame, text="Local Mode", text_color="grey", font=ctk.CTkFont(weight="bold"))
        self.remote_indicator.grid(row=0, column=3, pady=10)

        self.tube_indicator = ctk.CTkLabel(self.status_frame, text="Tube: --", text_color="grey", font=ctk.CTkFont(weight="bold"))
        self.tube_indicator.grid(row=0, column=4, pady=10)

        self.apply_loaded_settings()
        self.update_parameter_visibility()

    def toggle_connection(self):
        if self.connected:
            self.polling = False
            self.connected = False
            self.status_label.configure(text="Status: Disconnected", text_color="red")
            self.connect_btn.configure(text="Connect")
            if getattr(self, 'plc', None):
                try:
                    self.plc.close()
                except:
                    pass
            self.log_msg("Disconnected.")
        else:
            target = self.ip_entry.get().strip()
            if not target:
                self.log_error("Please enter a connection target.")
                return
            try:
                self.plc = PumpDriver(target)
                self.plc.open()
                self.connected = True
                self.status_label.configure(text="Status: Connected (IP)", text_color="green")
                self.connect_btn.configure(text="Disconnect")
                self.log_msg("EtherNet/IP Connected successfully.")
                
                self.polling = True
                threading.Thread(target=self.poll_pump_data, daemon=True).start()
            except Exception as e:
                self.log_error(f"EtherNet/IP Error: {e}")

    def load_settings(self):
        self.config_data = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    self.config_data = json.load(f)
            except Exception:
                pass
        self.hardware_max_rpm = self.config_data.get("max_rpm", 160.0)

    def update_parameter_visibility(self):
        mode = self.mode_var.get()
        
        self.on_time_label.grid_remove()
        self.on_time_entry.grid_remove()
        self.off_time_label.grid_remove()
        self.off_time_entry.grid_remove()
        self.vol_label.grid_remove()
        self.volume_entry.grid_remove()
        self.batch_label.grid_remove()
        self.batch_entry.grid_remove()
        self.apply_params_btn.grid_remove()
        
        # Base parameters always visible
        self.unit_label.grid(row=2, column=0, sticky="w", padx=10, pady=(10,0))
        self.unit_menu.grid(row=2, column=1, padx=10, pady=(10,0), sticky="ew")
        
        self.flow_label.grid(row=3, column=0, sticky="w", padx=10, pady=(10,0))
        self.flow_entry.grid(row=3, column=1, padx=10, pady=(10,0), sticky="ew")
        
        self.flow_slider.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        if mode == 1:
            self.on_time_label.grid(row=5, column=0, sticky="w", padx=10, pady=(10,0))
            self.on_time_entry.grid(row=6, column=0, padx=10, pady=(0,5))
            self.off_time_label.grid(row=5, column=1, sticky="w", padx=10, pady=(10,0))
            self.off_time_entry.grid(row=6, column=1, padx=10, pady=(0,5))
            self.batch_label.grid(row=7, column=0, sticky="w", padx=10, pady=(5,0))
            self.batch_entry.grid(row=8, column=0, padx=10, pady=(0,5))
            self.apply_params_btn.grid(row=9, column=0, columnspan=2, pady=10)
        elif mode == 2:
            self.vol_label.grid(row=5, column=0, sticky="w", padx=10, pady=(10,0))
            self.volume_entry.grid(row=6, column=0, padx=10, pady=(0,5))
            self.off_time_label.grid(row=5, column=1, sticky="w", padx=10, pady=(10,0))
            self.off_time_entry.grid(row=6, column=1, padx=10, pady=(0,5))
            self.batch_label.grid(row=7, column=0, sticky="w", padx=10, pady=(5,0))
            self.batch_entry.grid(row=8, column=0, padx=10, pady=(0,5))
            self.apply_params_btn.grid(row=9, column=0, columnspan=2, pady=10)
        else:
            self.apply_params_btn.grid(row=5, column=0, columnspan=2, pady=10)

    def apply_loaded_settings(self):
        # Applies UI state from config_data if present. Call this AT THE END of setup_main_area!
        if "ip" in self.config_data:
            self.ip_entry.delete(0, 'end')
            self.ip_entry.insert(0, self.config_data["ip"])
        if "conn_type" in self.config_data:
            self.connection_type.set(self.config_data["conn_type"])
        if "mode" in self.config_data:
            self.mode_var.set(self.config_data["mode"])
        if "direction" in self.config_data:
            self.direction_var.set(self.config_data["direction"])
        if "unit" in self.config_data:
            self.unit_var.set(self.config_data["unit"])
        
        if "flow" in self.config_data:
            self.flow_entry.delete(0, 'end')
            self.flow_entry.insert(0, self.config_data["flow"])
        if "vol" in self.config_data:
            self.volume_entry.delete(0, 'end')
            self.volume_entry.insert(0, self.config_data["vol"])
        if "on_time" in self.config_data:
            self.on_time_entry.delete(0, 'end')
            self.on_time_entry.insert(0, self.config_data["on_time"])
        if "off_time" in self.config_data:
            self.off_time_entry.delete(0, 'end')
            self.off_time_entry.insert(0, self.config_data["off_time"])
        if "batch" in self.config_data:
            self.batch_entry.delete(0, 'end')
            self.batch_entry.insert(0, self.config_data["batch"])
        if "notes" in self.config_data:
            self.notes_entry.delete("1.0", "end")
            self.notes_entry.insert("1.0", self.config_data["notes"])

    def save_all_settings(self):
        self.config_data["max_rpm"] = getattr(self, "hardware_max_rpm", 160.0)
        self.config_data["ip"] = self.ip_entry.get()
        self.config_data["conn_type"] = self.connection_type.get()
        self.config_data["mode"] = self.mode_var.get()
        self.config_data["direction"] = self.direction_var.get()
        self.config_data["unit"] = self.unit_var.get()
        self.config_data["flow"] = self.flow_entry.get()
        self.config_data["vol"] = self.volume_entry.get()
        self.config_data["on_time"] = self.on_time_entry.get()
        self.config_data["off_time"] = self.off_time_entry.get()
        self.config_data["batch"] = self.batch_entry.get()
        self.config_data["notes"] = self.notes_entry.get("1.0", "end-1c")
        
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config_data, f)
        except Exception as e:
            print("Failed to save config:", e)

    def on_closing(self):
        try:
            self.save_all_settings()
        except:
            pass
            
        if getattr(self, 'connected', False):
            try:
                self.toggle_connection()
            except:
                pass
        self.destroy()

    def save_settings(self, max_rpm):
        try:
            self.hardware_max_rpm = float(max_rpm)
            self.save_all_settings()
            self.log_msg(f"Hardware Settings saved! Max RPM: {self.hardware_max_rpm}")
        except ValueError:
            self.log_error("Invalid Max RPM value.")

    def cmd_open_settings(self):
        settings_win = ctk.CTkToplevel(self)
        settings_win.title("Settings & Documentation")
        settings_win.geometry("500x400")
        settings_win.attributes('-topmost', True)
        
        tabview = ctk.CTkTabview(settings_win)
        tabview.pack(padx=10, pady=10, fill="both", expand=True)
        
        tabview.add("Hardware")
        tabview.add("Firmware")
        tabview.add("Documentation")
        
        # --- Hardware Tab ---
        hw_tab = tabview.tab("Hardware")
        ctk.CTkLabel(hw_tab, text="Max Drive RPM:").grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        rpm_entry = ctk.CTkEntry(hw_tab, width=100)
        rpm_entry.grid(row=0, column=1, padx=20, pady=(20, 5))
        rpm_entry.insert(0, str(self.hardware_max_rpm))
        
        def on_save():
            self.save_settings(rpm_entry.get())
            settings_win.destroy()
            
        save_btn = ctk.CTkButton(hw_tab, text="Save Settings", command=on_save, fg_color=MASTERFLEX_ORANGE, hover_color="#C03B18")
        save_btn.grid(row=1, column=0, columnspan=2, pady=(20, 10))

        def on_open_log():
            if os.path.exists("run_log.csv"):
                os.startfile("run_log.csv")
            else:
                self.log_error("run_log.csv does not exist yet.")

        open_log_btn = ctk.CTkButton(hw_tab, text="Open CSV Log", command=on_open_log, fg_color="gray", hover_color="darkgray")
        open_log_btn.grid(row=2, column=0, columnspan=2, pady=(0, 20))
        
        # --- Firmware Tab ---
        fw_tab = tabview.tab("Firmware")
        fw_tab.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(fw_tab, text="Masterflex Firmware Update Utility", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, pady=(10,5))
        ctk.CTkLabel(fw_tab, text="Format a USB drive with the latest firmware to update your REGLO.", text_color="grey").grid(row=1, column=0, pady=(0,15))
        
        def check_for_updates():
            webbrowser.open("https://www.masterflex.com/support/firmware-updates")
            
        check_btn = ctk.CTkButton(fw_tab, text="1. Check for Latest Firmware", command=check_for_updates, fg_color="gray", hover_color="darkgray")
        check_btn.grid(row=2, column=0, pady=5)
        
        create_drive_btn = ctk.CTkButton(fw_tab, text="2. Create Update USB Drive", command=self.cmd_create_update_drive, fg_color=MASTERFLEX_ORANGE, hover_color="#C03B18")
        create_drive_btn.grid(row=3, column=0, pady=15)
        
        # --- Documentation Tab ---
        doc_tab = tabview.tab("Documentation")
        doc_tab.grid_columnconfigure(0, weight=1)
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
        doc_lbl = ctk.CTkLabel(doc_tab, text=doc_text, justify="left", wraplength=400)
        doc_lbl.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

    def cmd_create_update_drive(self):
        firmware_path = filedialog.askopenfilename(title="Select Masterflex Firmware Update File")
        if not firmware_path:
            return
            
        usb_path = filedialog.askdirectory(title="Select Target USB Flash Drive")
        if not usb_path:
            return
            
        try:
            filename = os.path.basename(firmware_path)
            dest = os.path.join(usb_path, filename)
            shutil.copy2(firmware_path, dest)
            self.log_msg(f"Firmware copied successfully to {dest}")
            
            # Show instructional popup
            popup = ctk.CTkToplevel(self)
            popup.title("Update Instructions")
            popup.geometry("450x250")
            popup.attributes('-topmost', True)
            
            instructions = (
                "USB Drive Created Successfully!\n\n"
                "Please follow these exact steps on your physical pump:\n"
                "1. Insert the USB drive into the pump drive's back USB port.\n"
                "2. Tap SETTINGS from any of the mode screens on the touchscreen.\n"
                "3. Tap DEVICE INFORMATION.\n"
                "4. Tap CHECK FOR UPDATES and follow the onscreen prompts."
            )
            
            lbl = ctk.CTkLabel(popup, text=instructions, justify="left", font=ctk.CTkFont(size=14))
            lbl.pack(padx=20, pady=20)
            
            ok_btn = ctk.CTkButton(popup, text="OK", command=popup.destroy)
            ok_btn.pack(pady=10)
            
        except Exception as e:
            self.log_error(f"Failed to copy firmware: {e}")
            messagebox.showerror("Error", f"Failed to create update drive: {e}")


    # --- UI Actions ---
    def cmd_discover(self):
        if not PYCOMM3_AVAILABLE:
            self.log_error("pycomm3 missing! Cannot discover.")
            return

        self.log_msg("Searching network for MasterFlex Pump... (Please wait)")
        self.discover_btn.configure(state="disabled", text="Searching...")
        threading.Thread(target=self._run_discovery, daemon=True).start()

    def _run_discovery(self):
        try:
            devices = CIPDriver.discover()
            found_ip = None
            for dev in devices:
                prod_name = dev.get('product_name', '').lower()
                if 'reglo' in prod_name or 'masterflex' in prod_name or 'pump' in prod_name:
                    found_ip = dev.get('ip_address')
                    self.after(0, self.log_msg, f"Found MasterFlex ({dev.get('product_name')}) at {found_ip}")
                    break
            
            if not found_ip and devices:
                found_ip = devices[0].get('ip_address')
                self.after(0, self.log_msg, f"Found ENIP device at {found_ip} - assuming it is the pump.")

            if found_ip:
                self.after(0, self.set_ip_entry, found_ip)
            else:
                self.after(0, self.log_error, "No EtherNet/IP devices discovered.")
        except Exception as e:
            self.after(0, self.log_error, f"Discovery failed: {e}")
        finally:
            self.after(0, self.reset_discover_btn)

    def set_ip_entry(self, ip):
        self.ip_entry.delete(0, 'end')
        self.ip_entry.insert(0, ip)
        self.log_msg(f"IP address set to {ip}. Click Connect when ready.")

    def reset_discover_btn(self):
        self.discover_btn.configure(state="normal", text="Search Network")

    def flow_slider_event(self, value):
        self.flow_entry.delete(0, 'end')
        self.flow_entry.insert(0, f"{value:.2f}")

    def log_msg(self, msg):
        self.console_textbox.insert(tk.END, f"[INFO] {msg}\n")
        self.console_textbox.see(tk.END)

    def log_error(self, msg):
        self.console_textbox.insert(tk.END, f"[ERROR] {msg}\n")
        self.console_textbox.see(tk.END)

    # --- Pump Control Logics ---
    def cmd_start(self):
        self.cmd_apply_params()
        self.output_data[0] |= 0b00000001
        self.write_output_data()
        self.log_msg("Command: START")

    def cmd_stop(self):
        self.output_data[0] &= ~0b00000001
        self.write_output_data()
        self.log_msg("Command: STOP")

    def cmd_remote_toggle(self):
        self.output_data[0] |= 0b00000100
        self.write_output_data()
        import time
        time.sleep(0.1)
        self.output_data[0] &= ~0b00000100
        self.write_output_data()
        self.log_msg("Command: TOGGLE REMOTE CONTROL")

    def cmd_reset_cumulative(self):
        self.output_data[0] |= 0b00001000
        self.write_output_data()
        import time
        time.sleep(0.1)
        self.output_data[0] &= ~0b00001000
        self.write_output_data()
        self.log_msg("Command: RESET CUMULATIVE VOL")
        
    def cmd_reset_vol(self):
        self.cmd_reset_cumulative()
        
    def cmd_reset_batch(self):
        self.output_data[0] |= 0b00010000
        self.write_output_data()
        import time
        time.sleep(0.1)
        self.output_data[0] &= ~0b00010000
        self.write_output_data()
        self.log_msg("Command: RESET BATCH")

    def cmd_apply_params(self):
        try:
            flow_val = float(self.flow_entry.get())
            vol_val = float(self.volume_entry.get())
            on_val = float(self.on_time_entry.get())
            off_val = float(self.off_time_entry.get())
            batch_val = int(self.batch_entry.get())

            import struct
            struct.pack_into('<f', self.output_data, 8, flow_val)
            struct.pack_into('<f', self.output_data, 12, vol_val)
            struct.pack_into('<f', self.output_data, 16, on_val)
            struct.pack_into('<f', self.output_data, 20, off_val)
            struct.pack_into('<i', self.output_data, 24, batch_val)

            self.write_output_data()
            self.log_msg("Parameters Applied (EtherNet/IP)")
        except ValueError:
            self.log_error("Invalid parameter entered. Check your numbers.")

    def cmd_open_log_folder(self):
        try:
            import os, subprocess, sys
            if os.name == 'nt':
                os.startfile(os.getcwd())
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', os.getcwd()])
            else:
                subprocess.Popen(['xdg-open', os.getcwd()])
        except Exception as e:
            self.log_error(f"Failed to open folder: {e}")

    def cmd_log_console_line(self, event):
        try:
            index = self.console_textbox.index(f"@{event.x},{event.y}")
            line = self.console_textbox.get(f"{index} linestart", f"{index} lineend")
            if line.strip():
                self.write_run_log(f"> {line.strip()}")
        except Exception as e:
            pass

    def write_run_log(self, ui_msg, csv_row=None):
        self.run_log_textbox.insert("end", ui_msg + "\n")
        self.run_log_textbox.see("end")
        
        if csv_row:
            try:
                import os, csv
                file_exists = os.path.exists("run_log.csv")
                with open("run_log.csv", "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(["Date/Time", "Event", "Mode", "Flow Rate", "Other Info"])
                    writer.writerow(csv_row)
            except Exception as e:
                self.log_error(f"Failed to write to CSV: {e}")

    def log_started_run(self):
        mode_str = ["Continuous", "Time", "Volume"][self.mode_var.get()]
        set_flow = self.flow_entry.get()
        unit_str = self.unit_var.get()
        notes = self.notes_entry.get("1.0", "end-1c").strip().replace("\n", "; ")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        notes_str = f" | Notes: {notes}" if notes else ""
        ui_msg = f"[{timestamp}] [START] Mode: {mode_str} | Flow: {set_flow} {unit_str}{notes_str}"
        
        csv_row = None
        if self.auto_log_var.get():
            csv_row = [timestamp, "START", mode_str, f"{set_flow} {unit_str}", f"Notes: {notes}" if notes else ""]
        else:
            ui_msg += " (Not Saved to CSV)"
            
        self.write_run_log(ui_msg, csv_row)

    def log_finished_run(self, final_vol):
        vol_dispensed = final_vol - getattr(self, '_run_start_vol', final_vol)
        duration_sec = time.time() - getattr(self, '_run_start_time', time.time())
        mins, secs = divmod(int(duration_sec), 60)
        
        mode = self.mode_var.get()
        mode_str = ["Continuous", "Time", "Volume"][mode]
        set_flow = self.flow_entry.get()
        unit_str = self.unit_var.get()
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        vol_unit = unit_str.split('/')[0] if '/' in unit_str else unit_str

        ui_msg = f"[{timestamp}] [ END ] Mode: {mode_str} | Flow: {set_flow} {unit_str} | Dispensed: {vol_dispensed:.4f} {vol_unit} | Duration: {int(mins)}m {int(secs)}s"
        
        csv_row = None
        if self.auto_log_var.get():
            csv_row = [timestamp, "END", mode_str, f"{set_flow} {unit_str}", f"Dispensed: {vol_dispensed:.4f} {vol_unit}; Duration: {int(mins)}m {int(secs)}s"]
        else:
            ui_msg += " (Not Saved to CSV)"
            
        self.write_run_log(ui_msg, csv_row)

    def cmd_update_direction(self):
        d = self.direction_var.get()
        if d.lower() == 'ccw':
            self.output_data[0] |= 0b01000000
        else:
            self.output_data[0] &= ~0b01000000
        self.write_output_data()
        self.log_msg(f"Direction set to: {self.direction_var.get()}")

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
        mode = self.mode_var.get()
        self.update_parameter_visibility()
        self.output_data[4] = mode
        self.write_output_data()
        self.log_msg(f"Mode set to: {mode}")

    def write_output_data(self):
        if not getattr(self, 'connected', False) or not getattr(self, 'plc', None):
            return
        try:
            with self.plc_lock:
                self.plc.generic_message(
                    service=b'\x10',
                    class_code=b'\x04',
                    instance=112,
                    attribute=b'\x03',
                    request_data=bytes(self.output_data)
                )
        except Exception as e:
            pass

    def poll_pump_data(self):
        import time
        while getattr(self, 'polling', False) and getattr(self, 'connected', False) and getattr(self, 'plc', None):
            try:
                with self.plc_lock:
                    result = self.plc.generic_message(
                        service=b'\x0e',
                        class_code=b'\x04',
                        instance=100,
                        attribute=b'\x03'
                    )
                if result and result.value:
                    self.input_data = result.value
                    self.after(0, self.update_dashboard)
                    
                with self.plc_lock:
                    self.plc.generic_message(
                        service=b'\x10',
                        class_code=b'\x04',
                        instance=112,
                        attribute=b'\x03',
                        request_data=bytes(self.output_data)
                    )
            except Exception as e:
                pass
            time.sleep(0.1)

    def poll_serial_data(self):
        import time, struct, asyncio
        while getattr(self, 'polling', False) and getattr(self, 'connected', False) and getattr(self, 'serial_pump', None) and getattr(self.serial_pump, 'connected', False):
            try:
                future_status = asyncio.run_coroutine_threadsafe(self.serial_pump.status(), self.serial_loop)
                future_vol = asyncio.run_coroutine_threadsafe(self.serial_pump.volume(), self.serial_loop)
                
                status_res = future_status.result(timeout=1.0)
                vol_res = future_vol.result(timeout=1.0)
                
                arr = bytearray(56)
                if status_res and "running" in status_res.lower():
                    arr[0] |= 0b00000010
                struct.pack_into('<f', arr, 4, float(self.flow_entry.get()) if self.flow_entry.get() else 0.0)
                try:
                    v = float(vol_res)
                except:
                    v = 0.0
                struct.pack_into('<f', arr, 8, v)
                self.input_data = arr
                self.after(0, self.update_dashboard)
            except Exception as e:
                pass
            time.sleep(0.5)

    def update_dashboard(self):
        import time, struct
        if len(self.input_data) < 56:
            return
        
        status_int = struct.unpack_from('<i', self.input_data, 0)[0]
        status_ok = bool(status_int & 1)
        is_running = bool(status_int & 2)
        dispense_running = bool(status_int & 4)
        local_mode = bool(status_int & 16)
        
        tube_code = self.input_data[5]
        
        cum_vol = struct.unpack_from('<f', self.input_data, 8)[0]
        batch_current = struct.unpack_from('<i', self.input_data, 24)[0]
        min_flow = struct.unpack_from('<f', self.input_data, 32)[0]
        cur_flow = struct.unpack_from('<f', self.input_data, 36)[0]
        max_flow = struct.unpack_from('<f', self.input_data, 40)[0]
        
        try:
            self.flow_limits_label.configure(text=f"Calibrated Limits:\nMin: {min_flow:.2f} | Max: {max_flow:.2f}")
        except: pass
        
        if cur_flow > 0:
            calc_time = cum_vol / cur_flow
        else:
            calc_time = 0.0
        
        self.lbl_mon_status.configure(text="Status OK: YES" if status_ok else "Status OK: NO", text_color="green" if status_ok else "red")
        
        if is_running or dispense_running:
            self.running_indicator.configure(text="● Pump Running", text_color="green")
            if not getattr(self, 'run_log_active', False):
                self.run_log_active = True
                self._run_start_time = time.time()
                self._run_start_vol = cum_vol
                self.log_started_run()
            else:
                mode = self.mode_var.get()
                if mode == 2:
                    try:
                        target_vol = float(self.volume_entry.get())
                        if target_vol > 0 and (cum_vol - self._run_start_vol) >= target_vol:
                            self.output_data[0] &= ~0b00000001
                            self.write_output_data()
                    except: pass
                elif mode == 1:
                    try:
                        target_time = float(self.on_time_entry.get())
                        if target_time > 0 and (time.time() - self._run_start_time) >= target_time:
                            self.output_data[0] &= ~0b00000001
                            self.write_output_data()
                    except: pass
        else:
            self.running_indicator.configure(text="● Pump Stopped", text_color="red")
            if getattr(self, 'run_log_active', False):
                self.run_log_active = False
                self.log_finished_run(cum_vol)
                if self.connection_type.get() != "Serial COM" and self.connected:
                    if self.output_data[0] & 0b00000001:
                        self.after(50, self.cmd_stop)

        self.remote_indicator.configure(text="Local Mode" if local_mode else "Remote Mode", text_color="green" if local_mode else "blue")
        try:
            self.remote_btn.configure(text="Enable Remote" if local_mode else "Disable Remote")
        except:
            pass
        mm_size = TUBE_CODES_MM.get(tube_code, 0)
        if mm_size:
            self.tube_indicator.configure(text=f"Tube Code: {tube_code} ({mm_size} mm ID)")
        else:
            self.tube_indicator.configure(text=f"Tube Code: {tube_code}")
        
        flow_unit_str = self.unit_var.get()
        vol_unit_str = flow_unit_str.split('/')[0] if '/' in flow_unit_str else flow_unit_str
        self.lbl_mon_flow.configure(text=f"Flow Rate:\n{cur_flow:.4f} {flow_unit_str}")
        self.lbl_mon_vol.configure(text=f"Cumulative Vol:\n{cum_vol:.4f} {vol_unit_str}")
        self.lbl_mon_calctime.configure(text=f"Calc. Time:\n{calc_time:.2f} min")
        
        mode = self.mode_var.get()
        if mode in [1, 2]:
            self.lbl_mon_batch.grid(row=1, column=3, pady=10)
            self.reset_batch_btn.grid(row=2, column=3, pady=(0, 10))
            self.lbl_mon_batch.configure(text=f"Batch:\n{batch_current}")
        else:
            try:
                self.lbl_mon_batch.grid_remove()
                self.reset_batch_btn.grid_remove()
            except:
                pass
            
        max_rpm = getattr(self, "hardware_max_rpm", 160.0)
        try:
            max_flow = float(self.config_data.get("max_flow", max_rpm)) 
        except:
            max_flow = max_rpm
            
        if max_flow > 0:
            est_rpm = (cur_flow / max_flow) * max_rpm
        else:
            est_rpm = 0.0
            
        self.lbl_mon_rpm.configure(text=f"Est. RPM:\n{est_rpm:.1f}")

if __name__ == "__main__":
    app = MasterflexPumpGUI()
    app.mainloop()
