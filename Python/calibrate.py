import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Configuration ---
# !!! IMPORTANT: Update this to the filename of your NEW cross-calibration trial !!!
# This is the file you record with both sensors connected directly to each other.
CROSS_CALIBRATION_FILE = 'cross-calibration-2025-07-28_02.csv' 

# Degree of the polynomial to fit. 1 (linear) or 2 (quadratic) are good choices.
# Start with 1 for simplicity and robustness.
POLY_DEGREE = 1

# --- Step 1: Load the Cross-Calibration Data ---
try:
    cal_df = pd.read_csv(CROSS_CALIBRATION_FILE)
    print(f"Loaded cross-calibration data from '{CROSS_CALIBRATION_FILE}'.")
except FileNotFoundError:
    print(f"\n--- FILE NOT FOUND ---")
    print(f"Error: The data file was not found at '{CROSS_CALIBRATION_FILE}'")
    print("Please update the CROSS_CALIBRATION_FILE variable in this script with the correct filename.")
    exit()

# --- Step 2: Define the Ground Truth and Raw Data ---
# CORRECTED: The 'Fz' column from the pre-calibrated ATI sensor is our "ground truth" force.
# The 'SML_ADC_Raw' is the raw data we want to calibrate.
ground_truth_force = cal_df['Fz']
sml_raw_output = cal_df['SML_ADC_Raw']

# --- Step 3: Create the New Calibration Model for the SML Sensor ---
# We are fitting a model that maps: SML_ADC_Raw -> Force (Newtons)
# np.polyfit(x, y, degree)
print(f"Fitting a {POLY_DEGREE}-degree polynomial to the SML sensor data...")
sml_coeffs = np.polyfit(sml_raw_output, ground_truth_force, POLY_DEGREE)

# Create a callable polynomial function from the coefficients
sml_force_converter = np.poly1d(sml_coeffs)

print("Successfully created new SML sensor calibration model.")
print("\n--- SML Sensor Calibration Equation ---")
print("Force(N) = \n")
print(sml_force_converter)
print("\n-------------------------------------\n")


# --- Step 4: Plot the Results for Verification ---
print("Generating calibration plot...")

# Generate a smooth line for the fitted curve
x_fit = np.linspace(sml_raw_output.min(), sml_raw_output.max(), 200)
y_fit = sml_force_converter(x_fit)

plt.style.use('seaborn-v0_8-whitegrid')
fig, ax = plt.subplots(figsize=(12, 8))

# Plot the raw data points from the trial
# Using a scatter plot with small, semi-transparent points is good for large datasets
ax.scatter(sml_raw_output, ground_truth_force, label='Measured Data Points', alpha=0.3, s=10)

# Plot the fitted polynomial curve
ax.plot(x_fit, y_fit, label=f'Fitted Polynomial (Deg {POLY_DEGREE})', color='crimson', linestyle='-', linewidth=3)

# Formatting the plot for clarity
ax.set_title('SML Sensor Calibration vs. ATI Sensor', fontsize=18, fontweight='bold')
ax.set_xlabel('SML Sensor Raw Output (ADC)', fontsize=14)
# CORRECTED: Updated the y-axis label to reflect the use of Fz
ax.set_ylabel('ATI Sensor Force (Fz) [N]', fontsize=14)
ax.legend(fontsize=12)
ax.grid(True, which='both', linestyle='--', linewidth=0.5)

plt.tight_layout()
plt.show()

# You can now use the 'sml_force_converter' object in your main analysis script
# to convert SML_ADC_Raw values to Newtons.
