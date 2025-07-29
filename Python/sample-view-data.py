
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Import the function from your updated calibration script
try:
    # Ensure your calibration script is named 'calibrate.py'
    from calibrate import create_calibration_model
except ImportError:
    print("Error: Could not import 'create_calibration_model'.")
    print("Please make sure the 'calibrate.py' script is in the same folder.")
    exit()

# --- Configuration ---
TRIAL_DATA_FILE = 'trial_2025-07-28_14-10-19.csv'
ATI_CAL_FILE = 'ATI-Calibrate-07-28-[00].csv'
SML_CAL_FILE = 'SML-Calibrate-07-28-[01].csv'

# --- Step 1: Generate the calibration models ---
ati_force_converter, _ = create_calibration_model(ATI_CAL_FILE, raw_column_name='Fy')
sml_force_converter, _ = create_calibration_model(SML_CAL_FILE, raw_column_name='SML_ADC_Raw')

if not callable(ati_force_converter) or not callable(sml_force_converter):
    print("\nFATAL ERROR: A calibration model was not created correctly.")
    exit()

print("Successfully created calibration models.")

# --- Step 2: Load and Process the Trial Data ---
try:
    trial_df = pd.read_csv(TRIAL_DATA_FILE)
    print(f"Loaded trial data from '{TRIAL_DATA_FILE}'.")
except FileNotFoundError:
    print(f"Error: Trial data file not found at '{TRIAL_DATA_FILE}'")
    exit()

# --- Step 3: Convert Raw Data to Force (Vectorized Method) ---
# This is the corrected, more efficient way to apply the conversion.
# We call the converter function directly on the entire data column.
print("Converting raw sensor data to Newtons...")
trial_df['ATI_Force_N'] = ati_force_converter(trial_df['Fy'])
trial_df['SML_Force_N'] = sml_force_converter(trial_df['SML_ADC_Raw'])

# --- Step 4: Calculate Friction ---
trial_df['Friction_N'] = trial_df['ATI_Force_N'] - trial_df['SML_Force_N']
print("Friction calculation complete.")

# --- Step 5: Plot the Results ---
print("Generating plot...")
plt.style.use('seaborn-v0_8-whitegrid')
fig, ax = plt.subplots(figsize=(14, 8))

ax.plot(trial_df['PC_Time_s'], trial_df['Friction_N'], label='Friction Force', color='purple', linewidth=2)
ax.set_title('Calculated Friction Force vs. Time', fontsize=18, fontweight='bold')
ax.set_xlabel('Time (seconds)', fontsize=14)
ax.set_ylabel('Friction Force (Newtons)', fontsize=14)
ax.legend(fontsize=12)
ax.grid(True, which='both', linestyle='--', linewidth=0.5)
ax.axhline(0, color='black', linewidth=0.75, linestyle='-')

plt.tight_layout()
plt.show()
