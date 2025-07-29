import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import nidaqmx
import pandas as pd
import os
from datetime import datetime
import queue

# =============================================================================
# ======================== USER CONFIGURATION =================================
# =============================================================================
NI_DEVICE_NAME = "Dev1"
ATI_CHANNELS = "ai0:5"
# --- Descriptive labels for the ATI sensor channels ---
ATI_CHANNEL_LABELS = ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]
OUTPUT_FOLDER = "friction_test_data"
CALIBRATION_FOLDER = "calibration_data"
CROSS_CALIBRATION_DURATION = 30 # seconds

# =============================================================================
# ======================== UI HELPER CLASSES ==================================
# =============================================================================

class HWTestWindow(tk.Toplevel):
    """A modal window to guide the user through testing the limit switches."""
    def __init__(self, parent):
        super().__init__(parent)
        self.transient(parent)
        self.parent = parent
        self.title("Hardware Self-Test")
        self.geometry("400x280")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.switch_a_passed = False
        self.switch_b_passed = False
        self.check_job = None

        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.instruction_var = tk.StringVar(value="Please press and release Switch A (Home).")
        ttk.Label(main_frame, textvariable=self.instruction_var, font=("Helvetica", 12), wraplength=350).pack(pady=10)

        status_frame = ttk.Frame(main_frame)
        status_frame.pack(pady=10, fill=tk.X, expand=True)

        self.switch_a_status_var = tk.StringVar(value="Switch A: Untested")
        self.switch_a_label = ttk.Label(status_frame, textvariable=self.switch_a_status_var, font=("Helvetica", 11, "bold"))
        self.switch_a_label.pack()

        self.switch_b_status_var = tk.StringVar(value="Switch B: Untested")
        self.switch_b_label = ttk.Label(status_frame, textvariable=self.switch_b_status_var, font=("Helvetica", 11, "bold"))
        self.switch_b_label.pack()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)

        self.finish_button = ttk.Button(button_frame, text="Finish Test", state="disabled", command=self.finish_test)
        self.finish_button.pack(side=tk.LEFT, padx=10)

        self.override_button = ttk.Button(button_frame, text="Override Test", command=self.finish_test)
        self.override_button.pack(side=tk.LEFT, padx=10)

        self.grab_set()
        self.start_checking()

    def start_checking(self):
        self.parent.send_command('c')
        self.check_job = self.after(200, self.start_checking)

    def update_status(self, switch_a_pressed, switch_b_pressed):
        if not self.switch_a_passed and switch_a_pressed:
            self.switch_a_passed = True
            self.switch_a_status_var.set("Switch A: PASSED")
            self.switch_a_label.config(foreground="green")
            self.instruction_var.set("Great! Now please press and release Switch B.")
        elif self.switch_a_passed and not self.switch_b_passed and switch_b_pressed:
            self.switch_b_passed = True
            self.switch_b_status_var.set("Switch B: PASSED")
            self.switch_b_label.config(foreground="green")
            self.instruction_var.set("All tests passed! You can now proceed.")
            self.finish_button.config(state="normal")
            if self.check_job:
                self.after_cancel(self.check_job)

    def finish_test(self):
        if self.check_job: self.after_cancel(self.check_job)
        self.parent.send_command('e')
        self.parent.hw_test_complete()
        self.destroy()

    def on_closing(self):
        messagebox.showwarning("Test Required", "You must complete the hardware self-test before proceeding.", parent=self)

class CrossCalibrationManager:
    """Handles the cross-calibration process using the ATI sensor as ground truth."""
    def __init__(self, parent_app):
        self.app = parent_app
        self.is_calibrating = False
        self.calibration_thread = None
        self.calibration_file = None
        self.countdown_window = None

    def get_next_cal_filename(self):
        if not os.path.exists(CALIBRATION_FOLDER):
            os.makedirs(CALIBRATION_FOLDER)
        today_str = datetime.now().strftime("%Y-%m-%d")
        filename_base = f"cross-calibration-{today_str}"
        max_trial = -1
        for f in os.listdir(CALIBRATION_FOLDER):
            if f.startswith(filename_base) and f.endswith(".csv"):
                try:
                    num = int(f.split('_')[-1].split('.')[0])
                    if num > max_trial: max_trial = num
                except (ValueError, IndexError): continue
        new_filename = f"{filename_base}_{max_trial + 1:02d}.csv"
        return os.path.join(CALIBRATION_FOLDER, new_filename)

    def start_calibration(self):
        if self.is_calibrating or self.app.trial_active:
            messagebox.showwarning("In Progress", "A trial or calibration is already running.", parent=self.app)
            return
        if not self.app.is_connected:
            messagebox.showerror("Error", "Must be connected to the Arduino.", parent=self.app)
            return
        
        msg = "This will start a 30-second recording to calibrate the SML sensor against the ATI sensor.\n\n" \
              "Ensure both sensors are connected directly to each other.\n\n" \
              "Click OK to begin."
        if not messagebox.askyesno("Start Cross-Calibration", msg, parent=self.app):
            return

        filepath = self.get_next_cal_filename()
        try:
            self.calibration_file = open(filepath, 'w', newline='')
            headers = ['PC_Time_s', 'SML_ADC_Raw'] + ATI_CHANNEL_LABELS
            self.calibration_file.write(','.join(headers) + '\n')
            self.app.log_message(f"Cross-calibration file created: {filepath}\n")
        except Exception as e:
            messagebox.showerror("File Error", f"Could not create calibration file: {e}", parent=self.app)
            return

        self.is_calibrating = True
        self.calibration_thread = threading.Thread(target=self.run_calibration_loop, daemon=True)
        self.calibration_thread.start()
        
        self.countdown_window = CountdownWindow(self.app, self, CROSS_CALIBRATION_DURATION)

    def run_calibration_loop(self):
        start_time = time.time()
        try:
            with nidaqmx.Task() as ati_task:
                ati_task.ai_channels.add_ai_voltage_chan(f"{NI_DEVICE_NAME}/{ATI_CHANNELS}")
                while self.is_calibrating:
                    elapsed_time = time.time() - start_time
                    if elapsed_time > CROSS_CALIBRATION_DURATION: break

                    while not self.app.sml_data_queue.empty(): self.app.sml_data_queue.get()
                    
                    self.app.send_command('R') 

                    try:
                        sml_adc_str = self.app.sml_data_queue.get(timeout=1.0)
                        ati_readings = ati_task.read()
                        pc_time = time.time() - start_time
                        
                        sml_adc_raw = int(sml_adc_str)
                        data_row = [pc_time, sml_adc_raw] + ati_readings
                        self.calibration_file.write(','.join(map(str, data_row)) + '\n')
                    except queue.Empty:
                        self.app.log_message("WARNING: SML sensor poll timed out during calibration.\n")
                    except (ValueError) as e:
                        self.app.log_message(f"ERROR: Could not parse SML data '{sml_adc_str}': {e}\n")
                    
                    time.sleep(0.02) # approx 50Hz
        except Exception as e:
            self.app.log_message(f"ERROR during calibration: {e}\n")
        finally:
            self.app.after(0, self.stop_calibration)

    def stop_calibration(self):
        if not self.is_calibrating: return
        self.is_calibrating = False
        
        if self.countdown_window:
            self.countdown_window.destroy()
            self.countdown_window = None

        if self.calibration_thread and self.calibration_thread.is_alive():
            self.calibration_thread.join(timeout=1)
        
        if self.calibration_file:
            self.calibration_file.close()
            self.calibration_file = None
        
        self.app.log_message("Cross-calibration finished.\n")

class CountdownWindow(tk.Toplevel):
    """A pop-up window showing a countdown timer for the calibration process."""
    def __init__(self, parent, manager, duration):
        super().__init__(parent)
        self.manager = manager
        self.end_time = time.time() + duration
        self.transient(parent)
        self.title("Calibration in Progress")
        self.geometry("450x250")
        
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Please apply varying force to the sensors.", font=("Helvetica", 12)).pack(pady=10)
        
        self.time_var = tk.StringVar()
        ttk.Label(main_frame, textvariable=self.time_var, font=("Helvetica", 48, "bold"), foreground="navy").pack(pady=15, expand=True)
        
        ttk.Button(main_frame, text="Cancel", command=self.manager.stop_calibration).pack(pady=10)
        
        self.protocol("WM_DELETE_WINDOW", self.manager.stop_calibration)
        self.grab_set()
        self.update_timer()

    def update_timer(self):
        remaining = self.end_time - time.time()
        if remaining <= 0:
            self.time_var.set("0.0")
        else:
            self.time_var.set(f"{remaining:.1f}")
            self.after(100, self.update_timer)

# =============================================================================
# ======================== MAIN APPLICATION ===================================
# =============================================================================

class FrictionControllerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Friction & Force Controller")
        self.geometry("750x700")

        self.serial_port = None
        self.is_connected = False
        self.reading_thread = None
        self.trial_thread = None
        self.trial_active = False
        self.data_file = None
        self.start_time = 0
        self.hw_test_window = None
        
        self.cross_cal_manager = CrossCalibrationManager(self)
        
        self.line_queue = queue.Queue()
        self.sml_data_queue = queue.Queue(maxsize=1)
        self.homing_event = threading.Event()
        
        self.create_widgets()
        self.set_control_widgets_state(False)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.process_line_queue()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=5)
        
        conn_frame = ttk.LabelFrame(top_frame, text="Connection", padding="10")
        conn_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.port_var = tk.StringVar()
        self.port_combobox = ttk.Combobox(conn_frame, textvariable=self.port_var, state="readonly")
        self.port_combobox.pack(side=tk.LEFT, padx=5)
        self.update_ports_list()
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(conn_frame, text="Status: Disconnected", foreground="#c0392b")
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        cal_frame = ttk.LabelFrame(top_frame, text="Sensor Calibration", padding="10")
        cal_frame.pack(side=tk.LEFT, padx=(5, 0), fill=tk.Y)
        self.cal_button = ttk.Button(cal_frame, text="Run Cross-Calibration", command=self.cross_cal_manager.start_calibration)
        self.cal_button.pack(padx=5, pady=5, expand=True, fill=tk.BOTH)

        mid_frame = ttk.Frame(main_frame)
        mid_frame.pack(fill=tk.X, pady=5)
        
        rpm_frame = ttk.LabelFrame(mid_frame, text="RPM Control", padding="10")
        rpm_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Label(rpm_frame, text="Set Trial RPM:").pack()
        self.rpm_var = tk.StringVar(value="119")
        self.rpm_entry = ttk.Entry(rpm_frame, textvariable=self.rpm_var, width=10)
        self.rpm_entry.pack()
        self.set_rpm_button = ttk.Button(rpm_frame, text="Set RPM", command=self.send_rpm_command)
        self.set_rpm_button.pack(pady=5)
        
        control_frame = ttk.LabelFrame(mid_frame, text="Experiment Control", padding="10")
        control_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # --- ADDED: Frame for filename input ---
        filename_frame = ttk.Frame(control_frame)
        filename_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Label(filename_frame, text="Trial Filename:").pack(side=tk.LEFT)
        self.filename_var = tk.StringVar()
        self.filename_entry = ttk.Entry(filename_frame, textvariable=self.filename_var)
        self.filename_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Label(filename_frame, text=".csv").pack(side=tk.LEFT)

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 0))
        self.auto_trial_button = ttk.Button(button_frame, text="Start Automated Trial", command=self.start_auto_trial)
        self.auto_trial_button.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        self.stop_button = tk.Button(button_frame, text="EMERGENCY STOP", bg="#c0392b", fg="white", font=("Helvetica", 10, "bold"), command=self.stop_trial)
        self.stop_button.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        
        output_frame = ttk.LabelFrame(main_frame, text="System Log", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, state="disabled", height=15)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def set_control_widgets_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in [self.rpm_entry, self.set_rpm_button, self.auto_trial_button, self.stop_button, self.cal_button, self.filename_entry]:
            widget.config(state=state)

    def update_ports_list(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combobox['values'] = ports
        if ports: self.port_var.set(ports[0])

    def toggle_connection(self):
        if not self.is_connected:
            port = self.port_var.get()
            if not port: return
            try:
                self.serial_port = serial.Serial(port, 9600, timeout=1)
                self.is_connected = True
                self.reading_thread = threading.Thread(target=self.read_serial_data, daemon=True)
                self.reading_thread.start()
                self.connect_button.config(text="Disconnect")
                self.status_label.config(text=f"Connected to {port}", foreground="#27ae60")
                self.log_message(f"Successfully connected to {port}.\n")
                self.port_combobox.config(state="disabled")
            except serial.SerialException as e:
                messagebox.showerror("Connection Error", f"Could not connect to {port}: {e}")
        else:
            self.disconnect()

    def disconnect(self):
        if self.hw_test_window: self.hw_test_window.destroy()
        if self.is_connected:
            self.is_connected = False
            if self.reading_thread and self.reading_thread.is_alive():
                self.reading_thread.join(timeout=1)
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
        self.connect_button.config(text="Connect")
        self.status_label.config(text="Status: Disconnected", foreground="#c0392b")
        self.port_combobox.config(state="readonly")
        self.set_control_widgets_state(False)

    def read_serial_data(self):
        buffer = b''
        while self.is_connected:
            try:
                if self.serial_port.in_waiting > 0:
                    buffer += self.serial_port.read(self.serial_port.in_waiting)
                while b'\n' in buffer:
                    line_end = buffer.find(b'\n')
                    line = buffer[:line_end].decode('utf-8', errors='ignore').strip()
                    buffer = buffer[line_end + 1:]
                    if line: self.line_queue.put(line)
                time.sleep(0.01) # Prevent CPU hogging
            except Exception:
                break

    def process_line_queue(self):
        try:
            while True:
                line = self.line_queue.get_nowait()
                self.log_message(f"ARDUINO: {line}\n")

                if line == "HW_TEST_REQUIRED":
                    if not self.hw_test_window: self.hw_test_window = HWTestWindow(self)
                elif line == "HOMING_COMPLETE": self.homing_event.set()
                elif line.startswith("S:"):
                    if self.hw_test_window:
                        try: self.hw_test_window.update_status(line[2] == '1', line[3] == '1')
                        except IndexError: pass
                elif line.startswith("ADC_VAL:"):
                    value_str = line.split(':')[1].strip()
                    try: self.sml_data_queue.put_nowait(value_str)
                    except queue.Full: pass
                elif line == "Arduino Initialized. Ready for commands.":
                    self.set_control_widgets_state(True)
                elif line == "TRIAL_COMPLETE":
                    if self.trial_active:
                        self.log_message("Trial complete signal received from Arduino.\n")
                        self.stop_trial()
                else:
                    try:
                        int(line) 
                        if self.trial_active:
                            try:
                                self.sml_data_queue.put_nowait(line)
                            except queue.Full:
                                pass
                    except ValueError:
                        pass
        except queue.Empty: pass
        finally: self.after(100, self.process_line_queue)

    def hw_test_complete(self):
        self.log_message("Hardware self-test passed. Controls enabled.\n")
        self.set_control_widgets_state(True)
        self.hw_test_window = None

    def send_command(self, command):
        if self.is_connected and self.serial_port.is_open:
            self.serial_port.write(command.encode('utf-8'))

    def send_rpm_command(self):
        self.send_command(f"t{self.rpm_var.get()}\n")

    def start_auto_trial(self):
        if self.trial_active or self.cross_cal_manager.is_calibrating: return
        if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
        
        # --- MODIFIED: Use the filename from the entry box ---
        base_filename = self.filename_var.get().strip()
        if not base_filename:
            # Fallback to timestamp if the entry is empty
            base_filename = f"trial_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        
        # Ensure the filename ends with .csv
        if not base_filename.lower().endswith('.csv'):
            filename = f"{base_filename}.csv"
        else:
            filename = base_filename

        filepath = os.path.join(OUTPUT_FOLDER, filename)
        
        # Check if file already exists
        if os.path.exists(filepath):
            if not messagebox.askyesno("File Exists", f"The file '{filename}' already exists.\nDo you want to overwrite it?", parent=self):
                return

        try:
            self.data_file = open(filepath, 'w', newline='')
            headers = ['PC_Time_s', 'SML_ADC_Raw'] + ATI_CHANNEL_LABELS
            self.data_file.write(','.join(headers) + '\n')
            self.log_message(f"Data file created: {filepath}\n")
        except Exception as e:
            messagebox.showerror("File Error", f"Could not create data file: {e}")
            return

        self.trial_active = True
        self.homing_event.clear()
        self.trial_thread = threading.Thread(target=self.run_trial_sequence, daemon=True)
        self.trial_thread.start()

    def run_trial_sequence(self):
        try:
            self.send_command('a')
            self.log_message("Homing... Waiting for completion signal from Arduino.\n")
            if not self.homing_event.wait(timeout=30):
                self.log_message("ERROR: Homing timed out.\n")
                self.after(0, self.stop_trial)
                return
            if not self.trial_active: return
            
            self.log_message("Homing complete. Starting synchronized polling.\n")
            self.start_time = time.time()
            with nidaqmx.Task() as ati_task:
                ati_task.ai_channels.add_ai_voltage_chan(f"{NI_DEVICE_NAME}/{ATI_CHANNELS}")
                while self.trial_active:
                    while not self.sml_data_queue.empty(): self.sml_data_queue.get()
                    self.send_command('d')
                    try:
                        sml_adc_str = self.sml_data_queue.get(timeout=1.0)
                        ati_volts = ati_task.read()
                        pc_time = time.time() - self.start_time
                        
                        sml_adc_raw = int(sml_adc_str)
                        data_row = [pc_time, sml_adc_raw] + ati_volts
                        self.data_file.write(','.join(map(str, data_row)) + '\n')
                    except queue.Empty:
                        if self.trial_active: self.log_message("WARNING: SML sensor poll timed out.\n")
                    except (ValueError) as e:
                        self.log_message(f"ERROR: Could not parse SML data '{sml_adc_str}': {e}\n")
        except Exception as e:
            self.log_message(f"ERROR during trial: {e}\n")
        finally:
            if self.trial_active: self.after(0, self.stop_trial)

    def stop_trial(self):
        if self.trial_active:
            self.trial_active = False
            self.homing_event.set()
            self.send_command('x')
            self.log_message("Trial stopped by user.\n")
            if self.trial_thread and self.trial_thread.is_alive():
                self.trial_thread.join(timeout=1)
            if self.data_file:
                self.data_file.close()
                self.data_file = None

    def on_closing(self):
        self.stop_trial()
        self.cross_cal_manager.stop_calibration()
        self.disconnect()
        self.destroy()

    def log_message(self, message):
        self.output_text.config(state="normal")
        self.output_text.insert(tk.END, message)
        self.output_text.see(tk.END)
        self.output_text.config(state="disabled")

if __name__ == "__main__":
    app = FrictionControllerApp()
    app.mainloop()
