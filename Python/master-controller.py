import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import struct
import nidaqmx
import numpy as np
import pandas as pd
import os
from datetime import datetime

# =============================================================================
# ======================== USER CONFIGURATION =================================
# =============================================================================
# --- NI-DAQ Configuration ---
NI_DEVICE_NAME = "Dev1"
ATI_CHANNELS = "ai0:5"
NUM_ATI_CHANNELS = 6

# --- File Output ---
OUTPUT_FOLDER = "friction_test_data"
CALIBRATION_FOLDER = "calibration_data"

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
        self.geometry("400x250")
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

        self.finish_button = ttk.Button(main_frame, text="Finish Test", state="disabled", command=self.finish_test)
        self.finish_button.pack(pady=20)

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
        if self.check_job:
            self.after_cancel(self.check_job)
        self.parent.send_command('e')
        self.parent.hw_test_complete()
        self.destroy()

    def on_closing(self):
        messagebox.showwarning("Test Required", "You must complete the hardware self-test before proceeding.", parent=self)

class SensorCalibrationManager:
    """Handles the multi-point calibration process for both sensors."""
    def __init__(self, parent_app):
        self.app = parent_app
        self.weights_grams = [0, 20, 50, 100, 200, 500]

    def get_next_cal_filename(self, prefix):
        """Generates a unique filename for a calibration file."""
        if not os.path.exists(CALIBRATION_FOLDER):
            os.makedirs(CALIBRATION_FOLDER)
        
        today_str = datetime.now().strftime("%m-%d")
        filename_base = f"{prefix}-Calibrate-{today_str}"
        
        max_trial = -1
        for f in os.listdir(CALIBRATION_FOLDER):
            if f.startswith(filename_base) and f.endswith(".csv"):
                try:
                    num = int(f.split('[')[-1].split(']')[0])
                    if num > max_trial:
                        max_trial = num
                except (ValueError, IndexError):
                    continue
        
        new_filename = f"{filename_base}-[{max_trial + 1:02d}].csv"
        return os.path.join(CALIBRATION_FOLDER, new_filename)

    def run_ati_calibration(self):
        """Guides user through ATI sensor calibration and saves the raw voltage data."""
        if not messagebox.askyesno("Start ATI Calibration", 
                                   "This will guide you through a multi-step calibration for the ATI sensor.\n\n"
                                   "The process will record raw voltages at different loads. Do you want to continue?",
                                   parent=self.app):
            return

        calibration_data = []
        try:
            with nidaqmx.Task() as task:
                task.ai_channels.add_ai_voltage_chan(f"{NI_DEVICE_NAME}/{ATI_CHANNELS}")
                
                for weight in self.weights_grams:
                    messagebox.showinfo("Next Step", f"Please apply {weight}g load to the ATI sensor, then click OK.", parent=self.app)
                    
                    # Read an averaged value for stability
                    readings = task.read(number_of_samples_per_channel=100)
                    avg_volts = np.mean(readings, axis=1)
                    
                    self.app.log_message(f"ATI Cal ({weight}g): {np.round(avg_volts, 4)}\n")
                    calibration_data.append([weight] + avg_volts.tolist())

            # Save the data
            filepath = self.get_next_cal_filename("ATI")
            headers = ['Weight_g'] + [f'ATI_V{i}' for i in range(NUM_ATI_CHANNELS)]
            df = pd.DataFrame(calibration_data, columns=headers)
            df.to_csv(filepath, index=False)
            
            self.app.log_message(f"ATI calibration data saved to {filepath}\n")
            messagebox.showinfo("Success", f"ATI calibration complete. Data saved to:\n{filepath}", parent=self.app)

        except Exception as e:
            self.app.log_message(f"ERROR during ATI calibration: {e}\n")
            messagebox.showerror("Error", f"An error occurred during ATI calibration: {e}", parent=self.app)

    def run_sml_calibration(self):
        """Guides user through SML sensor calibration by communicating with Arduino."""
        if not self.app.is_connected:
            messagebox.showerror("Error", "Must be connected to Arduino to calibrate.", parent=self.app)
            return
        if not messagebox.askyesno("Start SML Calibration", 
                                   "This will guide you through a multi-step calibration for the SML sensor.\n\n"
                                   "The process will record raw ADC values at different loads. Do you want to continue?",
                                   parent=self.app):
            return

        calibration_data = []
        for weight in self.weights_grams:
            messagebox.showinfo("Next Step", f"Please apply {weight}g load to the SML sensor, then click OK.", parent=self.app)
            
            self.app.sml_cal_value.set("") # Reset the variable to an empty string
            self.app.send_command('R')
            
            # Set a timer that will trigger a timeout
            timeout_job = self.app.after(5000, lambda: self.app.sml_cal_value.set("TIMEOUT"))
            
            # Wait for the variable to be changed by the response OR the timer
            self.app.wait_variable(self.app.sml_cal_value)
            
            # A response was received, so cancel the timeout timer
            self.app.after_cancel(timeout_job)

            value_str = self.app.sml_cal_value.get()
            
            if value_str == "TIMEOUT":
                messagebox.showerror("Error", "Did not receive a response from the Arduino. Please try again.", parent=self.app)
                return
            elif value_str == "ERROR":
                messagebox.showerror("Error", "Failed to parse value from Arduino.", parent=self.app)
                return
            else:
                try:
                    value = int(value_str)
                    self.app.log_message(f"SML Cal ({weight}g): {value}\n")
                    calibration_data.append([weight, value])
                except ValueError:
                    messagebox.showerror("Error", f"Received non-integer value from Arduino: '{value_str}'", parent=self.app)
                    return

        # Save the data
        filepath = self.get_next_cal_filename("SML")
        headers = ['Weight_g', 'SML_ADC_Raw']
        df = pd.DataFrame(calibration_data, columns=headers)
        df.to_csv(filepath, index=False)
        
        self.app.log_message(f"SML calibration data saved to {filepath}\n")
        messagebox.showinfo("Success", f"SML calibration complete. Data saved to:\n{filepath}", parent=self.app)

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
        self.trial_active = False
        self.data_file = None
        self.start_time = 0
        self.hw_test_window = None

        # Threading tools for SML calibration
        self.sml_cal_value = tk.StringVar()

        self.packet_format = '<Lll' # timestamp(L), encoder(l), sml_raw_adc(l)
        self.packet_size = struct.calcsize(self.packet_format)
        
        self.sensor_manager = SensorCalibrationManager(self)

        self.create_widgets()
        self.set_control_widgets_state(False)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

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
        cal_frame.pack(side=tk.LEFT, padx=(5, 0))
        
        self.cal_ati_button = ttk.Button(cal_frame, text="Calibrate ATI Sensor", command=self.sensor_manager.run_ati_calibration)
        self.cal_ati_button.pack(side=tk.LEFT, padx=5)
        self.cal_sml_button = ttk.Button(cal_frame, text="Calibrate SML Sensor", command=self.sensor_manager.run_sml_calibration)
        self.cal_sml_button.pack(side=tk.LEFT, padx=5)

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
        self.auto_trial_button = ttk.Button(control_frame, text="Start Automated Trial", command=self.start_auto_trial)
        self.auto_trial_button.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)
        self.stop_button = tk.Button(control_frame, text="EMERGENCY STOP", bg="#c0392b", fg="white", font=("Helvetica", 10, "bold"), command=self.stop_trial)
        self.stop_button.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5)

        output_frame = ttk.LabelFrame(main_frame, text="System Log", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, state="disabled", height=15)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def set_control_widgets_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in [self.cal_ati_button, self.cal_sml_button, self.rpm_entry,
                       self.set_rpm_button, self.auto_trial_button, self.stop_button]:
            widget.config(state=state)

    def update_ports_list(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combobox['values'] = ports
        if ports:
            self.port_var.set(ports[0])

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
                self.log_message(f"ERROR connecting: {e}\n")
        else:
            self.disconnect()

    def disconnect(self):
        if self.hw_test_window: self.hw_test_window.destroy()
        if self.is_connected:
            self.is_connected = False
            if self.reading_thread: self.reading_thread.join()
            if self.serial_port and self.serial_port.is_open: self.serial_port.close()
        self.connect_button.config(text="Connect")
        self.status_label.config(text="Status: Disconnected", foreground="#c0392b")
        self.port_combobox.config(state="readonly")
        self.set_control_widgets_state(False)
        self.serial_port = None

    def read_serial_data(self):
        buffer = b''
        while self.is_connected:
            try:
                buffer += self.serial_port.read(self.serial_port.in_waiting or 1)
                
                while b'>' in buffer and b'<' in buffer:
                    start, end = buffer.find(b'>'), buffer.find(b'<')
                    if start < end:
                        packet = buffer[start+1:end]
                        if len(packet) == self.packet_size: self.process_binary_packet(packet)
                        buffer = buffer[end+1:]
                    else: break
                
                while b'\n' in buffer:
                    line_end = buffer.find(b'\n')
                    line = buffer[:line_end].decode('utf-8', errors='ignore').strip()
                    buffer = buffer[line_end+1:]
                    if line: self.after(0, self.process_text_line, line)
            except (serial.SerialException, TypeError):
                self.after(0, self.disconnect)
                break

    def process_text_line(self, line):
        self.log_message(f"ARDUINO: {line}\n")
        if line == "HW_TEST_REQUIRED":
            self.hw_test_window = HWTestWindow(self)
        elif line.startswith("S:"):
            if self.hw_test_window:
                try: self.hw_test_window.update_status(line[2] == '1', line[3] == '1')
                except IndexError: pass
        elif line.startswith("ADC_VAL:"):
            try:
                # Set the StringVar, which will unblock the waiting function
                self.sml_cal_value.set(line.split(':')[1].strip())
            except IndexError:
                self.log_message(f"ERROR: Could not parse ADC value: {line}\n")
                self.sml_cal_value.set("ERROR") # Signal an error

    def hw_test_complete(self):
        self.log_message("Hardware self-test passed. Controls enabled.\n")
        self.set_control_widgets_state(True)
        self.hw_test_window = None

    def process_binary_packet(self, packet_data):
        if not self.trial_active or not self.data_file: return
        
        arduino_time, encoder_val, sml_raw_adc = struct.unpack(self.packet_format, packet_data)
        
        try:
            ati_raw_volts = self.daq_task.read()
            pc_time = time.time() - self.start_time
            
            data_row = [pc_time, arduino_time] + ati_raw_volts + [encoder_val, sml_raw_adc]
            self.data_file.write(','.join(map(str, data_row)) + '\n')
        except Exception as e:
            self.log_message(f"ERROR during data read: {e}\n")

    def send_command(self, command):
        if self.is_connected: self.serial_port.write(command.encode('utf-8'))
        else: self.log_message("ERROR: Not connected.\n")

    def send_rpm_command(self):
        try:
            rpm = float(self.rpm_var.get())
            self.send_command(f"t{rpm}\n")
            self.log_message(f"Set RPM command sent: {rpm}\n")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number for RPM.")

    def start_auto_trial(self):
        if self.trial_active:
            messagebox.showwarning("Warning", "A trial is already active.")
            return

        if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join(OUTPUT_FOLDER, f"trial_{timestamp}.csv")
        
        try:
            self.data_file = open(filepath, 'w')
            headers = ['PC_Time_s', 'Arduino_Time_ms'] + [f'ATI_V{i}' for i in range(NUM_ATI_CHANNELS)] + ['Encoder', 'SML_ADC_Raw']
            self.data_file.write(','.join(headers) + '\n')
            self.log_message(f"Data file created: {filepath}\n")
        except Exception as e:
            self.log_message(f"ERROR creating file: {e}\n")
            return

        try:
            self.daq_task = nidaqmx.Task()
            self.daq_task.ai_channels.add_ai_voltage_chan(f"{NI_DEVICE_NAME}/{ATI_CHANNELS}")
        except Exception as e:
            self.log_message(f"ERROR setting up DAQ task: {e}\n")
            self.data_file.close()
            return
            
        self.trial_active = True
        self.start_time = time.time()
        self.send_command('a')
        self.log_message("Automated trial started.\n")

    def stop_trial(self):
        self.send_command('x')
        if self.trial_active:
            self.trial_active = False
            self.log_message("Trial stopped by user.\n")
            if self.data_file:
                self.data_file.close()
                self.data_file = None
            if hasattr(self, 'daq_task'):
                self.daq_task.close()

    def log_message(self, message):
        self.output_text.config(state="normal")
        self.output_text.insert(tk.END, message)
        self.output_text.see(tk.END)
        self.output_text.config(state="disabled")

    def on_closing(self):
        if self.trial_active: self.stop_trial()
        if self.is_connected: self.disconnect()
        self.destroy()

if __name__ == "__main__":
    app = FrictionControllerApp()
    app.mainloop()
