import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Configuration ---
# 1. The data file from your cross-calibration run
CROSS_CALIBRATION_FILE = 'cross-calibration-2025-07-28_02.csv' # <-- UPDATE THIS FILENAME

# 2. The data file from your actual friction experiment
FRICTION_TRIAL_FILE = 'trial_2025-07-28_15-44-47.csv' # <-- UPDATE THIS FILENAME

# 3. The axis on the ATI sensor that measures the force
ATI_FORCE_AXIS = 'Fz'

# 4. Degree for the SML calibration fit (1 is recommended)
POLY_DEGREE = 1

# --- Step 1: Create the SML Calibration Model ---
def create_sml_converter(calibration_file):
    """
    Creates a callable function to convert SML raw ADC values to Newtons
    based on a cross-calibration trial against the ATI sensor.
    """
    try:
        cal_df = pd.read_csv(calibration_file)
    except FileNotFoundError:
        print(f"FATAL ERROR: Calibration file not found at '{calibration_file}'")
        return None

    # Use the specified ATI axis as the ground truth force
    ground_truth_force = cal_df[ATI_FORCE_AXIS]
    sml_raw_output = cal_df['SML_ADC_Raw']
    
    # Fit a model that maps: SML_ADC_Raw -> Force (Newtons)
    sml_coeffs = np.polyfit(sml_raw_output, ground_truth_force, POLY_DEGREE)
    sml_force_converter = np.poly1d(sml_coeffs)
    
    print("Successfully created SML force converter from cross-calibration data.")
    print("SML Conversion Equation: Force(N) =")
    print(sml_force_converter)
    return sml_force_converter

# --- Step 2: Load the Friction Trial Data ---
try:
    trial_df = pd.read_csv(FRICTION_TRIAL_FILE)
    print(f"\nLoaded friction trial data from '{FRICTION_TRIAL_FILE}'.")
except FileNotFoundError:
    print(f"FATAL ERROR: Friction trial file not found at '{FRICTION_TRIAL_FILE}'")
    exit()

# --- Step 3: Apply the New Calibration ---
# Create the converter function
sml_to_newtons = create_sml_converter(CROSS_CALIBRATION_FILE)

if sml_to_newtons is None:
    exit()

# Convert the SML raw data to Newtons
trial_df['SML_Force_N'] = sml_to_newtons(trial_df['SML_ADC_Raw'])

# The ATI force is already calibrated, so we just use its column directly
trial_df['ATI_Force_N'] = trial_df[ATI_FORCE_AXIS]

# --- Step 4: Calculate and Plot Friction ---
# Friction is the difference between the two forces
trial_df['Friction_N'] = trial_df['ATI_Force_N'] - trial_df['SML_Force_N']
print("Friction calculation complete.")

# Plot the results
print("Generating plot...")
plt.style.use('seaborn-v0_8-whitegrid')
fig, ax = plt.subplots(figsize=(14, 8))

ax.plot(trial_df['PC_Time_s'], trial_df['Friction_N'], label='Friction Force', color='green', linewidth=2)
ax.set_title('Final Calculated Friction Force vs. Time', fontsize=18, fontweight='bold')
ax.set_xlabel('Time (seconds)', fontsize=14)
ax.set_ylabel('Friction Force (Newtons)', fontsize=14)
ax.legend(fontsize=12)
ax.grid(True, which='both', linestyle='--', linewidth=0.5)
ax.axhline(0, color='black', linewidth=0.75, linestyle='-')

plt.tight_layout()
plt.show()
