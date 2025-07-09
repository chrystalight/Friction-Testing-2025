import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import struct # Required for handling binary data

class ArduinoController(tk.Tk):
    """
    A tkinter-based GUI to control the Arduino friction experiment setup.
    This version uses a binary protocol for efficient data transfer.
    """
    def __init__(self):
        super().__init__()
        self.title("Arduino Experiment Controller")
        self.geometry("600x800")

        # --- Class Attributes ---
        self.serial_port = None
        self.is_connected = False
        self.reading_thread = None
        self.current_angle = 90
        self.arduino_ready = False

        # --- Attributes for data display and timer ---
        self.trial_active = False
        self.elapsed_time = 0.0
        self.time_var = tk.StringVar(value="Time: 0.0s")
        self.encoder_var = tk.StringVar(value="Encoder: 0")
        self.current_var = tk.StringVar(value="Current: 0.0 A")
        self.voltage_var = tk.StringVar(value="Voltage: 0.0 V")

        # --- Define the binary packet structure ---
        self.packet_format = '<LlBB'
        self.packet_size = struct.calcsize(self.packet_format)

        # --- UI Setup ---
        self.create_widgets()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """Creates and arranges all the GUI widgets."""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Connection Frame ---
        conn_frame = ttk.LabelFrame(main_frame, text="Connection", padding="10")
        conn_frame.pack(fill=tk.X, pady=5)
        self.port_label = ttk.Label(conn_frame, text="COM Port:")
        self.port_label.pack(side=tk.LEFT, padx=5)
        self.port_var = tk.StringVar()
        self.port_combobox = ttk.Combobox(conn_frame, textvariable=self.port_var, state="readonly")
        self.port_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.update_ports_list()
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(conn_frame, text="Status: Disconnected", foreground="red")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # --- Live Data Frame ---
        data_frame = ttk.LabelFrame(main_frame, text="Live Data", padding="10")
        data_frame.pack(fill=tk.X, pady=5)
        data_font = ("Helvetica", 14)
        ttk.Label(data_frame, textvariable=self.time_var, font=data_font).pack(side=tk.LEFT, expand=True)
        ttk.Label(data_frame, textvariable=self.encoder_var, font=data_font).pack(side=tk.LEFT, expand=True)
        ttk.Label(data_frame, textvariable=self.current_var, font=data_font).pack(side=tk.LEFT, expand=True)
        ttk.Label(data_frame, textvariable=self.voltage_var, font=data_font).pack(side=tk.LEFT, expand=True)

        # --- NEW: RPM Control Frame ---
        rpm_frame = ttk.LabelFrame(main_frame, text="RPM Control", padding="10")
        rpm_frame.pack(fill=tk.X, pady=5)
        ttk.Label(rpm_frame, text="Set Trial RPM:").pack(side=tk.LEFT, padx=5)
        self.rpm_var = tk.StringVar(value="100")
        self.rpm_entry = ttk.Entry(rpm_frame, textvariable=self.rpm_var, width=10)
        self.rpm_entry.pack(side=tk.LEFT, padx=5)
        self.set_rpm_button = ttk.Button(rpm_frame, text="Set RPM", command=self.send_rpm_command)
        self.set_rpm_button.pack(side=tk.LEFT, padx=5)

        # --- Control Frame ---
        control_frame = ttk.LabelFrame(main_frame, text="Experiment Control", padding="10")
        control_frame.pack(fill=tk.X, pady=5)
        self.auto_trial_button = ttk.Button(control_frame, text="Start Automated Trial", command=self.start_auto_trial)
        self.auto_trial_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.manual_trial_button = ttk.Button(control_frame, text="Start Manual Trial", command=self.start_manual_trial)
        self.manual_trial_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.stop_button = tk.Button(control_frame, text="EMERGENCY STOP", bg="red", fg="white", command=self.stop_trial)
        self.stop_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, ipady=5)

        # --- Servo & Misc Frame ---
        servo_misc_frame = ttk.Frame(main_frame)
        servo_misc_frame.pack(fill=tk.X, pady=5)
        servo_frame = ttk.LabelFrame(servo_misc_frame, text="Servo Control", padding="10")
        servo_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.angle_label_var = tk.StringVar(value=f"Angle: {self.current_angle}°")
        self.angle_label = ttk.Label(servo_frame, textvariable=self.angle_label_var, font=("Helvetica", 12))
        self.angle_label.pack(pady=5)
        servo_button_frame = ttk.Frame(servo_frame)
        servo_button_frame.pack()
        self.angle_plus_button = ttk.Button(servo_button_frame, text="Angle +10°", command=self.increase_angle)
        self.angle_plus_button.pack(side=tk.LEFT, padx=5)
        self.angle_minus_button = ttk.Button(servo_button_frame, text="Angle -10°", command=self.decrease_angle)
        self.angle_minus_button.pack(side=tk.LEFT, padx=5)
        misc_frame = ttk.LabelFrame(servo_misc_frame, text="Utilities", padding="10")
        misc_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.reset_button = ttk.Button(misc_frame, text="Reset Encoders", command=lambda: self.send_command('r'))
        self.reset_button.pack(pady=5, fill=tk.X)

        # --- Serial Output Frame ---
        output_frame = ttk.LabelFrame(main_frame, text="Serial Output", padding="10")
        output_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, state="disabled")
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.set_widget_states(False)

    def update_ports_list(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combobox['values'] = ports
        if ports:
            self.port_var.set(ports[0])

    def toggle_connection(self):
        if not self.is_connected:
            port = self.port_var.get()
            if not port:
                self.log_message("Error: No port selected.\n")
                return
            try:
                self.serial_port = serial.Serial(port, 9600, timeout=1)
                self.is_connected = True
                self.reading_thread = threading.Thread(target=self.read_serial_data, daemon=True)
                self.reading_thread.start()
                self.connect_button.config(text="Disconnect")
                self.status_label.config(text=f"Status: Connected to {port}", foreground="green")
                self.log_message(f"Successfully connected to {port}.\n")
                self.set_widget_states(True)
                self.port_combobox.config(state="disabled")
            except serial.SerialException as e:
                self.log_message(f"Error connecting: {e}\n")
                self.is_connected = False
        else:
            self.disconnect()

    def disconnect(self):
        if self.is_connected:
            self.is_connected = False
            self.trial_active = False
            self.arduino_ready = False
            if self.reading_thread:
                self.reading_thread.join()
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                self.log_message("Serial port closed.\n")
        self.connect_button.config(text="Connect")
        self.status_label.config(text="Status: Disconnected", foreground="red")
        self.log_message("Disconnected.\n")
        self.set_widget_states(False)
        self.port_combobox.config(state="readonly")
        self.serial_port = None
        self.reset_data_display()

    def read_serial_data(self):
        while self.is_connected:
            try:
                if self.serial_port.in_waiting > 0:
                    first_byte = self.serial_port.read(1)
                    if first_byte == b'>':
                        packet_data = self.serial_port.read(self.packet_size)
                        end_byte = self.serial_port.read(1)
                        if len(packet_data) == self.packet_size and end_byte == b'<':
                            unpacked_data = struct.unpack(self.packet_format, packet_data)
                            self.after(0, self.update_data_display, unpacked_data)
                        else:
                            self.serial_port.reset_input_buffer()
                            self.log_message("Warning: Malformed binary packet received.\n")
                    else:
                        rest_of_line = self.serial_port.readline()
                        full_line_bytes = first_byte + rest_of_line
                        line = full_line_bytes.decode('utf-8', errors='ignore').strip()
                        if line:
                            self.after(0, self.process_ascii_line, line)
            except (serial.SerialException, TypeError):
                self.log_message("Error: Device disconnected or port error.\n")
                self.is_connected = False
                self.after(0, self.disconnect)
                break

    def process_ascii_line(self, line):
        self.log_message(line + '\n')
        if "INIT_COMPLETE" in line and not self.arduino_ready:
            self.log_message("Arduino initialized. Starting polling.\n")
            self.arduino_ready = True
            self.send_poll_command()
        if "Trial complete" in line or "stopped by user" in line or "ERROR:" in line:
            if self.trial_active:
                self.trial_active = False

    def update_data_display(self, data):
        _arduino_time, encoder, current, voltage = data
        self.encoder_var.set(f"Encoder: {encoder}")
        self.current_var.set(f"Current: {float(current)/10.0:.1f} A")
        self.voltage_var.set(f"Voltage: {float(voltage):.1f} V")
        if self.is_connected:
            self.after(250, self.send_poll_command)

    def send_poll_command(self):
        if self.is_connected and self.arduino_ready:
            self.send_command('p')

    def update_timer(self):
        if self.trial_active:
            self.elapsed_time += 0.1
            self.time_var.set(f"Time: {self.elapsed_time:.1f}s")
            self.after(100, self.update_timer)
    
    # --- NEW: Send RPM Command ---
    def send_rpm_command(self):
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to Arduino.")
            return
        
        try:
            rpm = float(self.rpm_var.get())
            # Basic validation, Arduino does the final check
            if rpm < 0:
                raise ValueError
            
            # Send command as 't' followed by the number and a newline
            command_string = f"t{rpm}\n"
            self.send_command(command_string)

        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid, non-negative number for RPM.")

    def start_auto_trial(self):
        if self.is_connected and not self.trial_active:
            self.trial_active = True
            self.elapsed_time = 0.0
            self.update_timer()
            self.send_command('a')

    def start_manual_trial(self):
        if self.is_connected and not self.trial_active:
            self.trial_active = True
            self.elapsed_time = 0.0
            self.update_timer()
            self.send_command('s')
            
    def stop_trial(self):
        if self.is_connected:
            self.trial_active = False
            self.send_command('x')
            self.reset_data_display()

    def reset_data_display(self):
        self.elapsed_time = 0.0
        self.time_var.set("Time: 0.0s")
        
    def log_message(self, message):
        self.output_text.config(state="normal")
        self.output_text.insert(tk.END, message)
        self.output_text.see(tk.END)
        self.output_text.config(state="disabled")

    def send_command(self, command):
        if self.is_connected and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(command.encode('utf-8'))
            except serial.SerialException as e:
                self.log_message(f"Error writing to port: {e}\n")
                self.after(0, self.disconnect)
        else:
            self.log_message("Error: Not connected. Cannot send command.\n")

    def increase_angle(self):
        self.current_angle = min(180, self.current_angle + 10)
        self.angle_label_var.set(f"Angle: {self.current_angle}°")
        self.send_command('+')

    def decrease_angle(self):
        self.current_angle = max(0, self.current_angle - 10)
        self.angle_label_var.set(f"Angle: {self.current_angle}°")
        self.send_command('-')

    def set_widget_states(self, is_enabled):
        state = "normal" if is_enabled else "disabled"
        # Also enable/disable the new RPM controls
        for widget in [self.auto_trial_button, self.manual_trial_button, self.stop_button,
                       self.angle_plus_button, self.angle_minus_button, 
                       self.reset_button, self.set_rpm_button, self.rpm_entry]:
            widget.config(state=state)

    def on_closing(self):
        if self.is_connected:
            self.disconnect()
        self.destroy()

if __name__ == "__main__":
    app = ArduinoController()
    app.mainloop()
