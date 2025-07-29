import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import re

# =============================================================================
# =========================== CONFIGURATION ===================================
# =============================================================================

# 1. The data file from your cross-calibration run.
#    *** IMPORTANT: Update this to your actual cross-calibration filename. ***
CROSS_CALIBRATION_FILE = 'cross-calibration-2025-07-28_02.csv'

# 2. The folder containing your friction trial data.
TRIAL_DATA_FOLDER = 'friction_test_data'

# 3. List of the trial files you want to analyze.
#    (These should be inside the TRIAL_DATA_FOLDER)
TRIAL_FILES = [
    'q4-through-q3-0deg.csv',
    'q4-through-q3-10deg.csv',
    'q4-through-q3-20deg.csv',
    'q4-through-q3-30deg.csv'
]

# 4. The axis on the ATI sensor that measures the force.
ATI_FORCE_AXIS = 'Fz'

# 5. Time (in seconds) to ignore at the start of each trial.
DATA_CUTOFF_SECONDS = 3.0

# 6. Degree for the SML calibration fit (1 is recommended based on your previous results).
POLY_DEGREE = 1

# =============================================================================
# ======================= ANALYSIS FUNCTIONS ==================================
# =============================================================================

def create_sml_converter(calibration_file):
    """
    Creates a callable function to convert SML raw ADC values to Newtons
    based on a cross-calibration trial against the ATI sensor.
    """
    if not os.path.exists(calibration_file):
        print(f"FATAL ERROR: Calibration file not found at '{calibration_file}'")
        print("Please update the CROSS_CALIBRATION_FILE variable.")
        return None

    try:
        cal_df = pd.read_csv(calibration_file)
        # Use the specified ATI axis as the ground truth force
        ground_truth_force = cal_df[ATI_FORCE_AXIS]
        sml_raw_output = cal_df['SML_ADC_Raw']
        
        # Fit a model that maps: SML_ADC_Raw -> Force (Newtons)
        sml_coeffs = np.polyfit(sml_raw_output, ground_truth_force, POLY_DEGREE)
        sml_force_converter = np.poly1d(sml_coeffs)
        
        print("Successfully created SML force converter.")
        return sml_force_converter
    except Exception as e:
        print(f"FATAL ERROR: Could not process calibration file '{calibration_file}': {e}")
        return None

def analyze_trial(filepath, sml_converter):
    """
    Analyzes a single trial file to calculate the average friction.
    """
    try:
        trial_df = pd.read_csv(filepath)
    except FileNotFoundError:
        print(f"  - WARNING: Trial file not found: {filepath}")
        return None, None
    
    # 1. Chop off the first few seconds of data
    stable_df = trial_df[trial_df['PC_Time_s'] >= DATA_CUTOFF_SECONDS].copy()
    if stable_df.empty:
        print(f"  - WARNING: No data remaining in {os.path.basename(filepath)} after removing first {DATA_CUTOFF_SECONDS}s.")
        return None, None

    # 2. Convert raw sensor data to Newtons
    stable_df['SML_Force_N'] = sml_converter(stable_df['SML_ADC_Raw'])
    stable_df['ATI_Force_N'] = stable_df[ATI_FORCE_AXIS]

    # 3. Calculate friction
    stable_df['Friction_N'] = stable_df['ATI_Force_N'] - stable_df['SML_Force_N']

    # 4. Calculate the average friction for the stable period
    average_friction = stable_df['Friction_N'].mean()
    
    # 5. Extract the angle from the filename using regex
    match = re.search(r'(\d+)deg', os.path.basename(filepath))
    if not match:
        print(f"  - WARNING: Could not extract angle from filename: {os.path.basename(filepath)}")
        return None, None
        
    angle = int(match.group(1))
    
    print(f"  - Processed {os.path.basename(filepath)}: Angle={angle}°, Avg Friction={average_friction:.4f} N")
    return angle, average_friction

# =============================================================================
# =========================== MAIN SCRIPT =====================================
# =============================================================================

if __name__ == "__main__":
    # Create the SML-to-Newtons conversion function
    sml_to_newtons = create_sml_converter(CROSS_CALIBRATION_FILE)
    
    if sml_to_newtons is None:
        exit()

    results = []
    print("\nProcessing trial files...")
    # Loop through each trial file and analyze it
    for filename in TRIAL_FILES:
        filepath = os.path.join(TRIAL_DATA_FOLDER, filename)
        angle, avg_friction = analyze_trial(filepath, sml_to_newtons)
        if angle is not None and avg_friction is not None:
            results.append({'angle': angle, 'friction': avg_friction})
            
    if not results:
        print("\nNo trial data was successfully processed. Cannot generate plot.")
        exit()

    # --- Plotting the final results ---
    print("\nGenerating final plot...")
    
    # Convert results to a DataFrame and sort by angle
    results_df = pd.DataFrame(results).sort_values('angle')

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(10, 7))

    ax.bar(results_df['angle'], results_df['friction'], width=5, color='skyblue', edgecolor='black')

    ax.set_title('Average Friction vs. Joint Angle', fontsize=18, fontweight='bold')
    ax.set_xlabel('Joint Angle (Degrees)', fontsize=14)
    ax.set_ylabel('Average Friction (Newtons)', fontsize=14)
    ax.set_xticks(results_df['angle']) # Ensure ticks are exactly at the angle values
    ax.grid(axis='y', linestyle='--', linewidth=0.7)

    # Add text labels on top of each bar
    for index, row in results_df.iterrows():
        ax.text(row['angle'], row['friction'], f"{row['friction']:.3f}", 
                ha='center', va='bottom', fontsize=11, fontweight='bold')

    plt.tight_layout()
    plt.show()
