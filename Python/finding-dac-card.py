import nidaqmx
from nidaqmx.errors import DaqError
import time

# =============================================================================
# ======================== USER CONFIGURATION =================================
# =============================================================================
# TODO: Change these values to match your specific setup.

# The name of your NI device (e.g., "Dev1", "cDAQ1Mod1").
DEVICE_NAME = "Dev1"

# The physical analog input channels your ATI sensor is connected to.
# An ATI Mini40 is a 6-axis sensor, so it likely uses 6 channels.
# This format "ai0:5" will read from channels ai0, ai1, ai2, ai3, ai4, and ai5.
# Adjust if your wiring is different.
ANALOG_CHANNELS = "ai0:5"

# --- Optional: Channel Labels for Display ---
# You can label each channel to make the output easier to read.
# The order must match the order in ANALOG_CHANNELS.
CHANNEL_LABELS = ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]

# =============================================================================
# ======================== SCRIPT LOGIC =======================================
# =============================================================================

# Construct the full channel path string
full_channel_path = f"{DEVICE_NAME}/{ANALOG_CHANNELS}"

print("--- NI-DAQ Live Streaming Test ---")
print(f"Attempting to stream data from: {full_channel_path}")
print("Press Ctrl+C to stop the stream.")

try:
    # A 'with' statement ensures that the task is properly closed even if errors occur.
    with nidaqmx.Task() as task:
        
        # 1. Add the analog input voltage channels to the task.
        task.ai_channels.add_ai_voltage_chan(full_channel_path)
        
        # 2. Start an infinite loop to continuously read and display data.
        while True:
            # Read a single sample from all configured channels.
            # This will return a list of values, one for each channel.
            voltage_values = task.read()
            
            # --- Format the output string ---
            # Create a list of "Label: Value" strings
            output_parts = []
            for i in range(len(voltage_values)):
                label = CHANNEL_LABELS[i] if i < len(CHANNEL_LABELS) else f"ai{i}"
                value = voltage_values[i]
                output_parts.append(f"{label}: {value: 8.4f} V")
            
            # Join the parts into a single line
            output_string = " | ".join(output_parts)
            
            # Print the line, using a carriage return '\r' to print over the previous line.
            print(f"\r{output_string}", end="")
            
            # A short delay to control the update speed and prevent overwhelming the terminal.
            time.sleep(0.05) # 20 updates per second

except KeyboardInterrupt:
    # This block runs when you press Ctrl+C.
    print("\n\nStream stopped by user.")

except DaqError as e:
    # This block catches errors specific to the NI-DAQmx library.
    print("\n\nERROR: A DAQmx error occurred.")
    print(f"Details: {e}")
    print("\n--- Troubleshooting ---")
    print(f"1. Is the device name '{DEVICE_NAME}' correct? Check NI MAX.")
    print(f"2. Is the channel range '{ANALOG_CHANNELS}' correct?")
    print("3. Is the NI-DAQmx driver installed and are its services running?")
    
except Exception as e:
    # This catches any other Python errors.
    print(f"\n\nAn unexpected Python error occurred: {e}")

finally:
    print("--- Test complete ---")
